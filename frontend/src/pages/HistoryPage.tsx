import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../lib/api';
import { getScoreColor, getScoreTextColorClass } from '../lib/scoreUtils';

interface EvaluationListItem { id: string; deck_name: string; overall_score: number; created_at: string; }
interface PaginatedEvaluations { items: EvaluationListItem[]; total: number; page: number; page_size: number; }

function scoreBg(score: number) {
  const c = getScoreColor(score);
  return c === 'high' ? 'bg-emerald-50 dark:bg-emerald-900/20' : c === 'mid' ? 'bg-amber-50 dark:bg-amber-900/20' : 'bg-red-50 dark:bg-red-900/20';
}

function fmtDate(d: string) {
  return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function HistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<EvaluationListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;

  const fetch_ = useCallback(async (p: number) => {
    setLoading(true); setError(null);
    try {
      const res = await apiClient(`/api/evaluations?page=${p}&page_size=${pageSize}`);
      if (!res.ok) { if (res.status === 401) { navigate('/login'); return; } throw new Error(res.status === 404 ? 'Evaluation history endpoint not available. Is the backend running?' : `Error ${res.status}`); }
      const data: PaginatedEvaluations = await res.json();
      setItems(data.items); setTotal(data.total);
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to load'); }
    finally { setLoading(false); }
  }, [navigate]);

  useEffect(() => { fetch_(page); }, [page, fetch_]);

  const totalPages = Math.ceil(total / pageSize);
  const filtered = filter.trim() ? items.filter(e => e.deck_name.toLowerCase().includes(filter.toLowerCase())) : items;

  if (loading && !items.length) {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
        <div className="text-center"><span className="spinner text-zinc-400 mx-auto block" style={{ width: 24, height: 24 }} /><p className="mt-3 text-sm text-zinc-400">Loading…</p></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
        <div className="surface-elevated p-6 max-w-md w-full text-center">
          <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>
          <button onClick={() => fetch_(page)} className="btn-ghost text-sm">Try again</button>
        </div>
      </div>
    );
  }

  if (!total) {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
        <div className="surface-elevated p-8 max-w-sm w-full text-center animate-in">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-zinc-100 dark:bg-zinc-800">
            <svg className="h-6 w-6 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></svg>
          </div>
          <h2 className="font-semibold">No evaluations yet</h2>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Upload a deck to get started.</p>
          <button onClick={() => navigate('/upload')} className="btn-brand mt-4 min-h-[36px]">Upload deck</button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 animate-in">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-lg font-semibold">History</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{total} evaluation{total !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={() => navigate('/upload')} className="btn-brand text-[13px] min-h-[36px]">+ New</button>
      </div>

      <div className="surface-elevated overflow-hidden">
        <div className="border-b border-[var(--border)] p-3">
          <input type="text" placeholder="Search decks…" value={filter} onChange={e => setFilter(e.target.value)}
            className="input-field text-[13px]" aria-label="Filter by name" />
        </div>

        <div className="divide-y divide-[var(--border)]">
          {filtered.length === 0 ? (
            <p className="py-8 text-center text-sm text-zinc-400">No matches for "{filter}"</p>
          ) : filtered.map(ev => (
            <button key={ev.id} onClick={() => navigate(`/scorecard/${ev.id}`)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-[var(--surface-1)] transition-colors group">
              <div className={`flex h-9 w-9 items-center justify-center rounded-lg shrink-0 ${scoreBg(ev.overall_score)}`}>
                <span className={`text-sm font-bold tabular-nums ${getScoreTextColorClass(ev.overall_score)}`}>{ev.overall_score}</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate group-hover:text-[var(--brand)] transition-colors">{ev.deck_name}</p>
                <p className="text-[12px] text-zinc-400">{fmtDate(ev.created_at)}</p>
              </div>
              <svg className="h-4 w-4 text-zinc-300 dark:text-zinc-600 group-hover:text-zinc-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
            </button>
          ))}
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-3">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="text-[13px] font-medium text-zinc-500 disabled:text-zinc-300 dark:disabled:text-zinc-600">← Prev</button>
            <span className="text-[12px] text-zinc-400 tabular-nums">Page {page} of {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="text-[13px] font-medium text-zinc-500 disabled:text-zinc-300 dark:disabled:text-zinc-600">Next →</button>
          </div>
        )}
      </div>
    </div>
  );
}
