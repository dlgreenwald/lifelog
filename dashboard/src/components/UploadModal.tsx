import { useState, useRef, useCallback } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '../api/client';

interface UploadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful upload — lets the parent refresh recordings. */
  onUploaded?: () => void;
}

const ACCEPTED_EXTENSIONS = '.m4a,.mp3,.wav,.3gp,.aac,.amr,.ogg,.opus,.flac,.caf';

function toDatetimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const d = date;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function datetimeLocalToEpoch(value: string): number {
  // Parse as local time and convert to UTC epoch seconds
  const [datePart, timePart] = value.split('T');
  const [year, month, day] = datePart.split('-').map(Number);
  const [hour, minute] = timePart.split(':').map(Number);
  const d = new Date(year, month - 1, day, hour, minute);
  return Math.floor(d.getTime() / 1000);
}

export default function UploadModal({ open, onOpenChange, onUploaded }: UploadModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [recordedAt, setRecordedAt] = useState<string>(toDatetimeLocal(new Date()));
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      setSelectedFile(file);
      setError(null);
    }
  }, []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setError(null);
    }
  }, []);

  const handleFileClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!selectedFile) {
      setError('Please select an audio file.');
      return;
    }
    setError(null);
    setIsUploading(true);
    try {
      const recordedAtEpoch = datetimeLocalToEpoch(recordedAt);
      await api.uploadRecording(selectedFile, recordedAtEpoch);
      setSelectedFile(null);
      setRecordedAt(toDatetimeLocal(new Date()));
      onOpenChange(false);
      onUploaded?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setIsUploading(false);
    }
  }, [selectedFile, recordedAt, onOpenChange, onUploaded]);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (!nextOpen) {
      // Reset state when closing
      setSelectedFile(null);
      setError(null);
      setIsDragging(false);
      setRecordedAt(toDatetimeLocal(new Date()));
    }
    onOpenChange(nextOpen);
  }, [onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Upload Recording</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Start time */}
          <div className="space-y-1.5">
            <label htmlFor="recorded-at" className="text-sm font-medium">
              Recording start time
            </label>
            <Input
              id="recorded-at"
              type="datetime-local"
              value={recordedAt}
              onChange={(e) => setRecordedAt(e.target.value)}
              max={toDatetimeLocal(new Date())}
            />
          </div>

          {!selectedFile && (
            <p className="text-sm text-muted-foreground">
              Select an audio file below, then click Upload.
            </p>
          )}

          {/* Drop zone */}
          <div
            role="button"
            tabIndex={0}
            onClick={handleFileClick}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleFileClick(); }}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={`
              relative flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6
              cursor-pointer transition-colors select-none
              ${isDragging
                ? 'border-primary bg-primary/5'
                : 'border-muted-foreground/30 hover:border-muted-foreground/60'}
              ${selectedFile ? 'border-primary/50 bg-primary/5' : ''}
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              className="sr-only"
              onChange={handleFileChange}
            />

            {selectedFile ? (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-8 w-8 text-primary">
                  <path d="M9 18V5l12-2v13" />
                  <circle cx="6" cy="18" r="3" />
                  <circle cx="18" cy="16" r="3" />
                </svg>
                <p className="text-sm font-medium text-center">{selectedFile.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
                </p>
                <p className="text-xs text-muted-foreground">Click to change file</p>
              </>
            ) : (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-8 w-8 text-muted-foreground">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <p className="text-sm text-muted-foreground text-center">
                  Drop an audio file here, or <span className="text-primary font-medium">click to browse</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Supports M4A, MP3, WAV, 3GP, AAC, AMR, OGG, Opus, FLAC
                </p>
              </>
            )}
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={isUploading}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!selectedFile || isUploading}
          >
            {isUploading ? 'Uploading…' : 'Upload'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
