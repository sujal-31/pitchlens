import { useState, useRef, useCallback, type DragEvent, type ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';

const MAX_FILE_SIZE = 20 * 1024 * 1024;

interface UploadResponse { deck_id: string; analysis_id: string; file_name: string; page_count: number; }

export default function UploadPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const validateFile = useCallback((f: File): string | null => {
    if (f.type !== 'application/pdf') return 'Only PDF files are accepted.';
    if (f.size > MAX_FILE_SIZE) return `File exceeds 20 MB limit (${(f.size / 1048576).toFixed(1)} MB).`;
    return null;
  }, []);

  const handleFile = useCallback((f: File) => {
    setError(null);
    const err = validateFile(f);
    if (err) { setError(err); setFile(null); return; }
    setFile(f);
  }, [validateFile]);

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => { e.preventDefault(); setIsDragging(true); }, []);
  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => { e.preventDefault(); setIsDragging(false); }, []);
  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); setIsDragging(false);
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
  }, [handleFile]);
  const handleFileSelect = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) handleFile(e.target.files[0]);
  }, [handleFile]);

  const handleUpload = useCallback(() => {
    if (!file) return;
    const token = localStorage.getItem('access_token');
    if (!token) { setError('Please sign in first.'); return; }
    setUploading(true); setProgress(0); setError(null);

    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append('file', file);
    xhr.upload.addEventListener('progress', (e) => { if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100)); });
    xhr.addEventListener('load', () => {
      setUploading(false);
      if (xhr.status >= 200 && xhr.status < 300) {
        try { const r: UploadResponse = JSON.parse(xhr.responseText); navigate(`/analysis/${r.analysis_id}`); }
        catch { setError('Unexpected server response.'); }
      } else if (xhr.status === 401) setError('Session expired. Please sign in again.');
      else if (xhr.status === 413) setError('File too large.');
      else setError(`Upload failed (${xhr.status}).`);
    });
    xhr.addEventListener('error', () => { setUploading(false); setError('Network error.'); });
    xhr.open('POST', '/api/decks');
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  }, [file, navigate]);

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg animate-in">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight">Upload pitch deck</h1>
          <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
            Get a comprehensive AI analysis of your deck in under 60 seconds
          </p>
        </div>

        <div className="surface-elevated p-6 space-y-5">
          {/* Drop zone */}
          <div
            onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
            role="button" tabIndex={0} aria-label="Drop PDF or click to browse"
            className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 cursor-pointer transition-all ${
              isDragging
                ? 'border-[var(--brand)] bg-[var(--brand-subtle)]'
                : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600 bg-[var(--surface-1)]'
            }`}
          >
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-800">
              <svg className="h-5 w-5 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
              </svg>
            </div>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              <span className="font-medium text-zinc-900 dark:text-zinc-100">Click to upload</span> or drag and drop
            </p>
            <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">PDF up to 20 MB</p>
            <input ref={fileInputRef} type="file" accept="application/pdf,.pdf" onChange={handleFileSelect} className="hidden" />
          </div>

          {/* File preview */}
          {file && !uploading && (
            <div className="flex items-center gap-3 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-[var(--surface-1)] p-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 dark:bg-red-950/30">
                <svg className="h-4 w-4 text-red-600 dark:text-red-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{file.name}</p>
                <p className="text-xs text-zinc-400">{(file.size / 1048576).toFixed(2)} MB</p>
              </div>
              <button onClick={() => { setFile(null); setError(null); }} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 p-1" aria-label="Remove">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
          )}

          {/* Progress */}
          {uploading && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-zinc-500">Uploading…</span>
                <span className="tabular-nums font-medium">{progress}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                <div className="h-full rounded-full bg-[var(--brand)] transition-all duration-300" style={{ width: `${progress}%` }} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} />
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 px-3 py-2.5" role="alert">
              <p className="text-[13px] text-red-700 dark:text-red-300">{error}</p>
            </div>
          )}

          <button onClick={handleUpload} disabled={!file || uploading} className="btn-brand w-full min-h-[40px]">
            {uploading ? 'Uploading…' : 'Analyze deck'}
          </button>
        </div>
      </div>
    </div>
  );
}
