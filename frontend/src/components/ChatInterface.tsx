import { useState, useRef, useEffect, type FormEvent, type KeyboardEvent } from 'react';
import { apiClient } from '../lib/api';

interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; cited_sections?: string[]; created_at: string; }
const MAX_LEN = 1000;

export default function ChatInterface({ deckId }: { deckId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const disabled = !input.trim() || input.length > MAX_LEN || loading;

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    if (disabled) return;
    const msg: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: input.trim(), created_at: new Date().toISOString() };
    setMessages(p => [...p, msg]); setInput(''); setError(null); setLoading(true);
    try {
      const res = await apiClient(`/api/decks/${deckId}/chat`, { method: 'POST', body: JSON.stringify({ message: msg.content }) });
      if (!res.ok) { const d = await res.json().catch(() => null); throw new Error(d?.detail || `Error ${res.status}`); }
      const data = await res.json();
      setMessages(p => [...p, { id: crypto.randomUUID(), role: 'assistant', content: data.response, cited_sections: data.cited_sections, created_at: new Date().toISOString() }]);
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to send.'); }
    finally { setLoading(false); }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };

  return (
    <div className="surface-card flex flex-col max-h-[500px] overflow-hidden">
      <div className="border-b border-[var(--border)] px-4 py-3">
        <h3 className="text-sm font-semibold">Ask about this deck</h3>
        <p className="text-[12px] text-zinc-400">Answers grounded in deck content</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {!messages.length && !loading && (
          <p className="text-center text-sm text-zinc-400 py-8">Ask a question to get started.</p>
        )}
        {messages.map(m => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-xl px-3.5 py-2.5 ${
              m.role === 'user' ? 'bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900' : 'bg-[var(--surface-1)] border border-[var(--border)]'
            }`}>
              <p className="text-[13px] whitespace-pre-wrap break-words leading-relaxed">{m.content}</p>
              {m.cited_sections?.length ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {m.cited_sections.map((s, i) => <span key={i} className="text-[10px] rounded px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-500 font-medium">{s}</span>)}
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-xl px-3.5 py-2.5 bg-[var(--surface-1)] border border-[var(--border)]">
              <div className="flex gap-1"><span className="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:0ms]" /><span className="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:150ms]" /><span className="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:300ms]" /></div>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <div className="px-4 py-2 border-t border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30"><p className="text-[12px] text-red-600 dark:text-red-400">{error}</p></div>}

      <form onSubmit={send} className="border-t border-[var(--border)] p-3 flex gap-2 items-end">
        <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={onKey}
          placeholder="Ask a question…" rows={2} disabled={loading}
          className="input-field flex-1 resize-none text-[13px]" />
        <button type="submit" disabled={disabled}
          className="btn-primary min-h-[40px] min-w-[40px] px-3 shrink-0">
          {loading ? <span className="spinner" style={{ width: 14, height: 14 }} /> : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" /></svg>
          )}
        </button>
      </form>
    </div>
  );
}
