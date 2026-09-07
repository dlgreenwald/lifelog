import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SettingsForm from '../components/SettingsForm';
import type { UserSettings } from '../types';

function setup(props: {
  settings?: Partial<UserSettings>;
  saving?: boolean;
  message?: { type: 'success' | 'error'; text: string } | null;
} = {}) {
  const onChange = vi.fn();
  const onSave = vi.fn();
  const onLogout = vi.fn();
  const settings: UserSettings = {
    language: props.settings?.language ?? 'auto',
    llm_context: props.settings?.llm_context ?? '',
  };
  const view = render(
    <SettingsForm
      settings={settings}
      saving={props.saving ?? false}
      message={props.message ?? null}
      onChange={onChange}
      onSave={onSave}
      onLogout={onLogout}
    />,
  );
  return { ...view, onChange, onSave, onLogout };
}

describe('SettingsForm', () => {
  it('renders the settings card with all sections', () => {
    setup();
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save settings/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('displays the current language and context values', () => {
    setup({ settings: { language: 'en', llm_context: 'I am a developer.' } });
    expect(screen.getByRole('combobox')).toHaveValue('en');
    expect(screen.getByRole('textbox')).toHaveValue('I am a developer.');
  });

  it('calls onSave when Save Settings is clicked', async () => {
    const { onSave } = setup();
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('disables Save button while saving', () => {
    setup({ saving: true });
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
  });

  it('shows success message when provided', () => {
    setup({ message: { type: 'success', text: 'Settings saved successfully.' } });
    expect(screen.getByText('Settings saved successfully.')).toBeInTheDocument();
  });

  it('shows error message when provided', () => {
    setup({ message: { type: 'error', text: 'Failed to save settings.' } });
    expect(screen.getByText('Failed to save settings.')).toBeInTheDocument();
  });

  it('calls onLogout when Sign out is clicked', async () => {
    const { onLogout } = setup();
    await userEvent.click(screen.getByRole('button', { name: /sign out/i }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it('shows injection error when textarea contains script tag', () => {
    setup({ settings: { llm_context: '<script>alert("xss")</script>' } });
    expect(screen.getByText(/potentially harmful|not allowed/i)).toBeInTheDocument();
  });

  it('disables Save button when there is an injection error', () => {
    setup({ settings: { llm_context: '<script>' } });
    expect(screen.getByRole('button', { name: /save settings/i })).toBeDisabled();
  });

  it('shows character count', () => {
    setup({ settings: { llm_context: 'Hello world' } });
    expect(screen.getByText('11 / 2000')).toBeInTheDocument();
  });

  it('calls onChange when language select changes', async () => {
    const { onChange } = setup();
    await userEvent.selectOptions(screen.getByRole('combobox'), 'en');
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ language: 'en' }),
    );
  });

  it('calls onChange when textarea changes', async () => {
    const { onChange } = setup();
    const textarea = screen.getByRole('textbox');
    await userEvent.clear(textarea);
    await userEvent.type(textarea, 'New context');
    // clear() calls onChange with "", then each keystroke fires onChange
    // verify the first keystroke fired onChange
    const calls = onChange.mock.calls;
    const nonempty = calls.filter(([s]) => s.llm_context.length > 0);
    expect(nonempty.length).toBeGreaterThan(0);
    expect(nonempty[0][0]).toMatchObject({ llm_context: expect.any(String) });
  });
});
