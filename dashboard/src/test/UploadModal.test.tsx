import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import UploadModal from '../components/UploadModal';
import { api } from '../api/client';

// Mock shadcn Dialog to avoid Radix Portal rendering in jsdom.
// Use plain divs so buttons are in the normal DOM flow and clickable.
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children?: React.ReactNode; open: boolean }) =>
    open ? <div data-testid="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="dialog-content">{children}</div>
  ),
  DialogHeader: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="dialog-header">{children}</div>
  ),
  DialogTitle: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="dialog-title">{children}</div>
  ),
  DialogFooter: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="dialog-footer">{children}</div>
  ),
}));

vi.mock('../api/client', () => ({
  api: {
    uploadRecording: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

// jsdom requires Object.defineProperty to set input.files to a FileList
function setFileInput(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, 'files', {
    value: [file],
    configurable: true,
  });
  fireEvent.change(input);
}

describe('UploadModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderModal(open = true) {
    return render(
      <UploadModal open={open} onOpenChange={vi.fn()} onUploaded={vi.fn()} />
    );
  }

  it('renders dialog with title and form elements when open', () => {
    renderModal();
    expect(screen.getByTestId('dialog-title')).toBeInTheDocument();
    expect(screen.getByText('Upload Recording')).toBeInTheDocument();
    expect(screen.getByLabelText(/recording start time/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload/i })).toBeInTheDocument();
  });

  it('shows drop zone prompt when no file selected', () => {
    renderModal();
    expect(screen.getByText(/drop an audio file here/i)).toBeInTheDocument();
    expect(screen.getByText(/supports m4a, mp3, wav/i)).toBeInTheDocument();
  });

  it('shows error when submitting without a file', async () => {
    renderModal();
    const uploadBtn = screen.getByRole('button', { name: /upload/i });
    // Upload button is disabled until a file is selected
    expect(uploadBtn).toBeDisabled();
    // A hint message is shown
    expect(screen.getByText(/select an audio file below/i)).toBeInTheDocument();
  });

  it('calls uploadRecording with file and epoch when submitting', async () => {
    const user = userEvent.setup();
    const file = new File(['abc'], 'recording.m4a', { type: 'audio/m4a' });
    renderModal();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    setFileInput(input, file);
    await waitFor(() => {
      expect(screen.getByText('recording.m4a')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /upload/i }));
    await waitFor(() => {
      expect(mockApi.uploadRecording).toHaveBeenCalledTimes(1);
    });
    const call = mockApi.uploadRecording.mock.calls[0] as [File, number] | undefined;
    const [sentFile, epoch] = call!;
    expect(sentFile.name).toBe('recording.m4a');
    expect(typeof epoch).toBe('number');
    expect(epoch).toBeGreaterThan(0);
  });

  it('closes modal and calls onUploaded after successful upload', async () => {
    const onOpenChange = vi.fn();
    const onUploaded = vi.fn();
    mockApi.uploadRecording.mockResolvedValueOnce({ status: 'ok', session_id: 1, recording_id: 2 });
    const user = userEvent.setup();
    render(
      <UploadModal open={true} onOpenChange={onOpenChange} onUploaded={onUploaded} />
    );
    const file = new File(['abc'], 'recording.m4a', { type: 'audio/m4a' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    setFileInput(input, file);
    await waitFor(() => {
      expect(screen.getByText('recording.m4a')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /upload/i }));
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
      expect(onUploaded).toHaveBeenCalledTimes(1);
    });
  });

  it('shows error message when upload fails', async () => {
    const user = userEvent.setup();
    mockApi.uploadRecording.mockRejectedValueOnce(new Error('Server error'));
    renderModal();
    const file = new File(['abc'], 'recording.m4a', { type: 'audio/m4a' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    setFileInput(input, file);
    await waitFor(() => {
      expect(screen.getByText('recording.m4a')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /upload/i }));
    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument();
    });
  });

  it('disables upload button while uploading', async () => {
    const deferred: { promise: Promise<{ status: string; session_id: number; recording_id: number }>; resolve: (v: { status: string; session_id: number; recording_id: number }) => void } = {
      promise: null as unknown as Promise<{ status: string; session_id: number; recording_id: number }>,
      resolve: () => {},
    };
    deferred.promise = new Promise<{ status: string; session_id: number; recording_id: number }>((resolve) => {
      deferred.resolve = resolve;
    });
    mockApi.uploadRecording.mockReturnValue(deferred.promise);
    const user = userEvent.setup();
    renderModal();
    const file = new File(['abc'], 'recording.m4a', { type: 'audio/m4a' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    setFileInput(input, file);
    await waitFor(() => {
      expect(screen.getByText('recording.m4a')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /upload/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /uploading/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /upload/i })).toBeDisabled();
    });
    deferred.resolve({ status: 'ok', session_id: 1, recording_id: 2 });
  });

  it('shows file name and hides drop zone prompt after file selection', async () => {
    renderModal();
    const file = new File(['abc'], 'recording.m4a', { type: 'audio/m4a' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    setFileInput(input, file);
    await waitFor(() => {
      expect(screen.getByText('recording.m4a')).toBeInTheDocument();
      expect(screen.queryByText(/drop an audio file here/i)).not.toBeInTheDocument();
    });
  });

  it('closes modal on Cancel click', () => {
    const onOpenChange = vi.fn();
    render(
      <UploadModal open={true} onOpenChange={onOpenChange} onUploaded={vi.fn()} />
    );
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('accepts various audio MIME types and displays file name', async () => {
    renderModal();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const types = ['audio/mp4', 'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/flac'];
    for (const type of types) {
      const f = new File(['test'], `test.${type.split('/')[1]}`, { type });
      setFileInput(input, f);
      await waitFor(() => {
        const ext = type.split('/')[1];
        expect(screen.getByText(new RegExp(`test\\.${ext}`))).toBeInTheDocument();
      });
    }
  });

  it('renders nothing when closed', () => {
    renderModal(false);
    expect(screen.queryByTestId('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText('Upload Recording')).not.toBeInTheDocument();
  });
});
