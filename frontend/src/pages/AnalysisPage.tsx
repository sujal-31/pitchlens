import { useState, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAnalysisWebSocket } from '../hooks/useAnalysisWebSocket';
import { apiClient } from '../lib/api';
import type { PipelineStage, PartialResult } from '../types/websocket';

const SCORERS = ['market', 'team', 'business_model', 'competition'] as const;
const SCORER_LABELS: Record<string, string> = {
  market: 'Market', team: 'Team', business_model: 'Business Model', competition: 'Competition',
};

function ScorerIcon({ cat, className }: { cat: string; className?: string }) {
  const cls = className ?? 'h-4 w-4';
  switch (cat) {
    case 'market':
      return (
        <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
        </svg>
      );
    case 'team':
      return (
        <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
        </svg>
      );
    case 'business_model':
      return (
        <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
        </svg>
      );
    case 'competition':
      return (
        <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
        </svg>
      );
    default:
      return <span className="h-4 w-4 rounded-full bg-zinc-300 dark:bg-zinc-600 shrink-0" />;
  }
}

function scoreColor(s: number) {
  if (s >= 7) return 'text-emerald-600 dark:text-emerald-400';
  if (s >= 4) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-600 dark:text-red-400';
}

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [restLoading, setRestLoading] = useState(false);
  const [restError, setRestError] = useState<string | null>(null);

  const { currentStage, partialResults, isComplete, error, connectionStatus, finalData } = useAnalysisWebSocket(id);

  const completedScorers = useMemo(() => new Set(partialResults.map(r => r.category)), [partialResults]);
  const resultsByCategory = useMemo(() => {
    const m = new Map<string, PartialResult>();
    partialResults.forEach(r => m.set(r.category, r));
    return m;
  }, [partialResults]);

  const isScoringPhase = useMemo(() => {
    const ss: PipelineStage[] = ['scoring_market', 'scoring_team', 'scoring_business_model', 'scoring_competition'];
    return currentStage !== null && ss.includes(currentStage);
  }, [currentStage]);

  const handleRefresh = useCallback(async () => {
    if (!id) return;
    setRestLoading(true); setRestError(null);
    try {
      const res = await apiClient(`/api/decks/${id}/scorecard`);
      if (res.ok) navigate(`/scorecard/${id}`);
      else if (res.status === 404) setRestError('Results not ready yet.');
      else setRestError('Failed to fetch.');
    } catch { setRestError('Network error.'); }
    finally { setRestLoading(false); }
  }, [id, navigate]);

  // Progress calculation — must stay above early return (hooks rule)
  const progressPercent = useMemo(() => {
    if (!currentStage) return 0;
    if (currentStage === 'extracting') return 12;
    if (isScoringPhase) return 20 + (completedScorers.size / 4) * 55;
    if (currentStage === 'aggregating') return 85;
    if (currentStage === 'complete') return 100;
    return 0;
  }, [currentStage, isScoringPhase, completedScorers.size]);

  const phase = useMemo(() => {
    if (!currentStage) return 0;
    if (currentStage === 'extracting') return 1;
    if (isScoringPhase) return 2;
    if (currentStage === 'aggregating') return 3;
    return 4;
  }, [currentStage, isScoringPhase]);

  // Complete state
  if (isComplete || currentStage === 'complete') {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
        <div className="w-full max-w-md surface-elevated p-8 text-center animate-in">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/30">
            <svg className="h-6 w-6 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold">Analysis complete</h2>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Your scorecard is ready.</p>
          <button onClick={() => navigate(`/scorecard/${(finalData?.deck_id as string) ?? id}`)} className="btn-brand mt-5 min-h-[40px] px-6">
            View scorecard
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-start justify-center px-4 py-10">
      <div className="w-full max-w-xl animate-in">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">Analyzing deck</h1>
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
              connectionStatus === 'connected' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
              : connectionStatus === 'failed' ? 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
              : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full ${
                connectionStatus === 'connected' ? 'bg-emerald-500' : connectionStatus === 'failed' ? 'bg-red-500' : 'bg-zinc-400 animate-pulse'
              }`} />
              {connectionStatus === 'connected' ? 'Live' : connectionStatus === 'failed' ? 'Disconnected' : 'Connecting'}
            </span>
          </div>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            {isScoringPhase ? `Scoring dimensions (${completedScorers.size}/4)` :
             currentStage === 'extracting' ? 'Extracting content from slides…' :
             currentStage === 'aggregating' ? 'Generating final verdict…' : 'Initializing…'}
          </p>
        </div>

        {/* Progress bar */}
        <div className="mb-8">
          <div className="flex justify-between text-[11px] text-zinc-400 mb-1.5">
            <span>Progress</span>
            <span className="tabular-nums font-medium">{Math.round(progressPercent)}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
            <div className="h-full rounded-full bg-[var(--brand)] transition-all duration-700 ease-out" style={{ width: `${progressPercent}%` }} />
          </div>
        </div>

        {/* Pipeline steps */}
        <div className="surface-elevated divide-y divide-[var(--border)]">
          <Step n={1} label="Extract content" detail="Parsing PDF slides" status={phase > 1 ? 'done' : phase === 1 ? 'active' : 'pending'} />
          
          {/* Scoring — expanded */}
          <div className="p-4">
            <StepHeader n={2} label="Score dimensions" detail="4 parallel AI agents" status={phase > 2 ? 'done' : phase === 2 ? 'active' : 'pending'} />
            {(phase >= 2) && (
              <div className="mt-3 ml-8 grid grid-cols-2 gap-2">
                {SCORERS.map(cat => {
                  const done = completedScorers.has(cat);
                  const active = isScoringPhase && !done;
                  const result = resultsByCategory.get(cat);
                  return (
                    <div key={cat} className={`flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] transition-all ${
                      done ? 'bg-emerald-50 dark:bg-emerald-900/20' : active ? 'bg-zinc-50 dark:bg-zinc-800/50' : 'bg-zinc-50/50 dark:bg-zinc-800/30'
                    }`}>
                      {done ? (
                        <svg className="h-4 w-4 text-emerald-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      ) : active ? (
                        <span className="spinner shrink-0 text-zinc-400" style={{ width: 14, height: 14 }} />
                      ) : (
                        <span className="h-4 w-4 rounded-full border border-zinc-300 dark:border-zinc-600 shrink-0" />
                      )}
                      <ScorerIcon cat={cat} className={`h-4 w-4 shrink-0 ${done ? 'text-emerald-600 dark:text-emerald-400' : active ? 'text-zinc-500 dark:text-zinc-400' : 'text-zinc-400 dark:text-zinc-500'}`} />
                      <span className={done ? 'font-medium text-zinc-900 dark:text-zinc-100' : 'text-zinc-500 dark:text-zinc-400'}>
                        {SCORER_LABELS[cat]}
                      </span>
                      {done && result && (
                        <span className={`ml-auto tabular-nums font-semibold ${scoreColor(result.score)}`}>{result.score}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <Step n={3} label="Generate verdict" detail="Synthesizing final assessment" status={phase > 3 ? 'done' : phase === 3 ? 'active' : 'pending'} />
        </div>

        {/* Partial results */}
        {partialResults.length > 0 && (
          <div className="mt-6 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Results</h2>
            {partialResults.map((r, i) => (
              <div key={i} className="surface-card p-4 animate-in" style={{ animationDelay: `${i * 80}ms` }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">{SCORER_LABELS[r.category] ?? r.category}</span>
                  <span className={`text-lg tabular-nums font-bold ${scoreColor(r.score)}`}>{r.score}<span className="text-xs font-normal text-zinc-400">/10</span></span>
                </div>
                {r.reasoning && <p className="text-[13px] text-zinc-500 dark:text-zinc-400 leading-relaxed">{r.reasoning}</p>}
                {r.suggestions && r.suggestions.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {r.suggestions.map((s, j) => (
                      <li key={j} className="text-[12px] text-zinc-500 dark:text-zinc-400 flex gap-1.5">
                        <span className="text-[var(--brand)] mt-px">→</span>{s}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {(connectionStatus === 'failed' && error) && (
          <div className="mt-6 space-y-3">
            <div className="rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 px-3 py-2.5" role="alert">
              <p className="text-[13px] text-red-700 dark:text-red-300">{error}</p>
            </div>
            <button onClick={handleRefresh} disabled={restLoading} className="btn-primary w-full min-h-[40px]">
              {restLoading ? 'Loading…' : 'Refresh results'}
            </button>
            {restError && <p className="text-[12px] text-red-600 text-center">{restError}</p>}
          </div>
        )}

        {currentStage === 'failed' && connectionStatus !== 'failed' && (
          <div className="mt-6 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 px-3 py-2.5" role="alert">
            <p className="text-[13px] text-red-700 dark:text-red-300">{error ?? 'Analysis failed. Please try again.'}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Step({ n, label, detail, status }: { n: number; label: string; detail: string; status: 'done' | 'active' | 'pending' }) {
  return (
    <div className="p-4">
      <StepHeader n={n} label={label} detail={detail} status={status} />
    </div>
  );
}

function StepHeader({ n, label, detail, status }: { n: number; label: string; detail: string; status: 'done' | 'active' | 'pending' }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold shrink-0 ${
        status === 'done' ? 'bg-emerald-500 text-white' :
        status === 'active' ? 'bg-[var(--brand)] text-white' :
        'bg-zinc-100 dark:bg-zinc-800 text-zinc-400'
      }`}>
        {status === 'done' ? (
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        ) : n}
      </div>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium ${status === 'pending' ? 'text-zinc-400 dark:text-zinc-500' : ''}`}>{label}</p>
        <p className="text-[12px] text-zinc-400 dark:text-zinc-500">{detail}</p>
      </div>
      {status === 'active' && <span className="spinner text-[var(--brand)]" />}
    </div>
  );
}
