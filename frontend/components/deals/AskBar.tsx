"use client";
import { useState } from "react";
import { Sparkles, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AskResponse } from "@/types";
import api from "@/lib/api";

interface AskBarProps {
  onResult: (result: AskResponse) => void;
  onClear: () => void;
  hasResult: boolean;
}

export function AskBar({ onResult, onClear, hasResult }: AskBarProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.post<AskResponse>("/api/deals/ask", { query: q });
      onResult(data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "AI unavailable — is Ollama running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shrink-0 border-b border-[var(--border)] px-3 py-2 bg-[var(--bg-elevated)]">
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Sparkles size={14} className="text-[var(--green)] shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask AI: cheapest chicken, organic deals under $3, what's on sale at HEB…"
          className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none"
        />
        {hasResult && (
          <button
            type="button"
            aria-label="Clear AI results"
            onClick={() => { setQuery(""); onClear(); }}
            className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
          >
            <X size={13} />
          </button>
        )}
        <button
          type="submit"
          disabled={!query.trim() || loading}
          className={cn(
            "shrink-0 flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold transition-colors",
            query.trim() && !loading
              ? "bg-[var(--green)] text-black hover:opacity-90"
              : "bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]"
          )}
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : "Ask"}
        </button>
      </form>
      {error && <p className="mt-1 pl-5 text-xs text-red-400">{error}</p>}
    </div>
  );
}
