import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '../lib/api';
import { getScoreTextColorClass, isValidScore } from '../lib/scoreUtils';
import ScoreGauge from '../components/ScoreGauge';
import ChatInterface from '../components/ChatInterface';
import type { Scorecard, CategoryScore } from '../types/scorecard';

export default function ScorecardPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true); setError(null);
      try {
        const res = await apiClient(`/api/decks/${id}/scorecard`);
        if (!res.ok) throw new Error(`Error ${res.status}`);
        setScorecard(await res.json());
      } catch (e) { setError(e instanceof Error ? e.message : 'Failed'); }
      finally { setLoading(false); }
    })();
  }, [id]);

  const handleDownload = useCallback(() => {
    if (!scorecard) return;
    const html = buildReportHtml(scorecard);
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `PitchLens-Report-${new Date().toISOString().split('T')[0]}.html`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
  }, [scorecard]);

  if (loading) return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
      <span className="spinner text-zinc-400" style={{ width: 24, height: 24 }} />
    </div>
  );

  if (error || !scorecard) return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
      <div className="surface-elevated p-6 max-w-sm w-full text-center">
        <p className="text-sm text-red-600 dark:text-red-400">{error ?? 'No data found'}</p>
      </div>
    </div>
  );

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-6 animate-in">
      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <button onClick={() => navigate('/upload')} className="btn-brand text-[13px] min-h-[36px]">+ New analysis</button>
        <button onClick={handleDownload} className="btn-ghost text-[13px] min-h-[36px]">↓ Download report</button>
        <button onClick={() => navigate('/history')} className="btn-ghost text-[13px] min-h-[36px]">History</button>
      </div>

      {/* Overall score */}
      <div className="surface-elevated p-6 text-center">
        <p className="text-xs font-medium uppercase tracking-wider text-zinc-400 mb-3">Overall Score</p>
        {isValidScore(scorecard.overall_score) ? (
          <>
            <div className={`inline-flex items-center justify-center h-20 w-20 rounded-2xl border-2 ${
              scorecard.overall_score >= 7 ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20' :
              scorecard.overall_score >= 4 ? 'border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20' :
              'border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20'
            }`}>
              <span className={`text-3xl font-bold tabular-nums ${getScoreTextColorClass(scorecard.overall_score)}`}>{scorecard.overall_score}</span>
            </div>
            <p className="mt-2 text-xs text-zinc-400">out of 10</p>
            <div className="mt-4 max-w-xs mx-auto"><ScoreGauge score={scorecard.overall_score} /></div>
          </>
        ) : <p className="text-red-600">Invalid score: {scorecard.overall_score}</p>}
      </div>

      {/* Verdict */}
      <div className="surface-card p-5">
        <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-400 mb-2">Verdict</h2>
        <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{scorecard.verdict_summary}</p>
      </div>

      {/* Ranking */}
      <div className="surface-card p-5">
        <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-400 mb-3">Ranking</h2>
        <div className="space-y-1.5">
          {scorecard.category_ranking.map((cat, i) => (
            <div key={cat} className={`flex items-center gap-3 rounded-lg px-3 py-2 ${i === 0 ? 'bg-emerald-50 dark:bg-emerald-900/10' : ''}`}>
              <span className={`flex h-6 w-6 items-center justify-center rounded-md text-[11px] font-bold ${
                i === 0 ? 'bg-emerald-500 text-white' : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'
              }`}>{i + 1}</span>
              <span className="text-sm capitalize">{cat.replace(/_/g, ' ')}</span>
              {scorecard.failed_categories.includes(cat) && (
                <span className="ml-auto text-[10px] font-semibold uppercase text-red-600 bg-red-50 dark:bg-red-900/20 px-1.5 py-0.5 rounded">Failed</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Category details */}
      <div className="space-y-3">
        <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-400">Detailed Scores</h2>
        {scorecard.category_scores.map(cat => <CategoryCard key={cat.category} category={cat} />)}
      </div>

      {/* Chat */}
      {id && <ChatInterface deckId={id} />}
    </div>
  );
}

function CategoryCard({ category }: { category: CategoryScore }) {
  const valid = isValidScore(category.score);
  const textColor = valid ? getScoreTextColorClass(category.score) : 'text-red-600';

  return (
    <div className="surface-card p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold capitalize">{category.category.replace(/_/g, ' ')}</h3>
        <span className={`text-xl tabular-nums font-bold ${textColor}`}>
          {category.score}<span className="text-xs font-normal text-zinc-400">/10</span>
        </span>
      </div>
      <ScoreGauge score={category.score} />
      {category.reasoning && <p className="mt-3 text-[13px] text-zinc-600 dark:text-zinc-400 leading-relaxed">{category.reasoning}</p>}
      {category.suggestions?.length > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--border)]">
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400 mb-2">Suggestions</p>
          <ul className="space-y-1.5">
            {category.suggestions.map((s, i) => (
              <li key={i} className="text-[13px] text-zinc-600 dark:text-zinc-400 flex gap-2">
                <span className="text-[var(--brand)] shrink-0">→</span><span>{s}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function buildReportHtml(sc: Scorecard): string {
  const cats = sc.category_scores.map(c => {
    const color = c.score >= 7 ? '#10b981' : c.score >= 4 ? '#f59e0b' : '#ef4444';
    return `<div style="margin-bottom:20px;padding:20px;background:#f8fafc;border-radius:12px;border-left:4px solid ${color}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <strong style="text-transform:capitalize">${c.category.replace(/_/g,' ')}</strong>
        <span style="font-size:20px;font-weight:700;color:${color}">${c.score}/10</span>
      </div>
      <p style="color:#475569;font-size:13px;line-height:1.6">${c.reasoning}</p>
      ${c.suggestions.length ? `<ul style="margin-top:8px;padding-left:16px">${c.suggestions.map(s=>`<li style="font-size:12px;color:#475569">${s}</li>`).join('')}</ul>` : ''}
    </div>`;
  }).join('');
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>PitchLens Report</title></head><body style="font-family:system-ui;max-width:700px;margin:0 auto;padding:40px 20px">
    <h1 style="font-size:22px;margin-bottom:4px">PitchLens Report</h1>
    <p style="color:#94a3b8;font-size:12px;margin-bottom:30px">${new Date().toLocaleDateString()}</p>
    <div style="text-align:center;padding:24px;background:#f8fafc;border-radius:16px;margin-bottom:24px">
      <p style="color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Overall</p>
      <span style="font-size:36px;font-weight:800;color:${sc.overall_score>=7?'#10b981':sc.overall_score>=4?'#f59e0b':'#ef4444'}">${sc.overall_score}</span><span style="color:#94a3b8">/10</span>
    </div>
    <div style="padding:16px;background:#f8fafc;border-radius:12px;margin-bottom:24px"><p style="color:#475569;font-size:13px;line-height:1.7">${sc.verdict_summary}</p></div>
    ${cats}
    <p style="margin-top:32px;text-align:center;color:#94a3b8;font-size:11px">Generated by PitchLens</p>
  </body></html>`;
}
