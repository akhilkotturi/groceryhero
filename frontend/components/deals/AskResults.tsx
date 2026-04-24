"use client";
import { useState } from "react";
import { Sparkles, Plus, Check } from "lucide-react";
import type { AskResponse, AskSuggestedAction } from "@/types";
import { DealCard } from "./DealCard";
import { useGroceryStore } from "@/lib/grocery-store";

interface AskResultsProps {
  result: AskResponse;
}

export function AskResults({ result }: AskResultsProps) {
  const { addItem } = useGroceryStore();
  const [doneActions, setDoneActions] = useState<Set<number>>(new Set());

  const dealsWithObjects = result.deals.filter((r) => r.deal != null);

  async function handleAction(action: AskSuggestedAction, idx: number) {
    if (action.action === "add_to_plan") {
      const deals = dealsWithObjects
        .filter((r) => action.deal_ids.includes(r.deal_id))
        .map((r) => r.deal!);
      await Promise.allSettled(deals.map((d) => addItem(d)));
      setDoneActions((prev) => new Set(prev).add(idx));
    }
  }

  if (dealsWithObjects.length === 0 && !result.answer) return null;

  return (
    <div className="border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[var(--radius)] px-3 py-3 space-y-3 mb-3">
      {/* Answer */}
      <div className="flex items-start gap-2">
        <Sparkles size={13} className="text-[var(--green)] mt-0.5 shrink-0" />
        <p className="text-sm text-[var(--text-primary)] leading-snug">{result.answer}</p>
      </div>

      {/* Deal cards */}
      {dealsWithObjects.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {dealsWithObjects.map((ref, i) => (
            <DealCard key={ref.deal_id} deal={ref.deal!} index={i} />
          ))}
        </div>
      )}

      {/* Suggested actions */}
      {result.suggested_actions.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {result.suggested_actions.map((action, i) => (
            <button
              key={i}
              onClick={() => handleAction(action, i)}
              disabled={doneActions.has(i)}
              className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold bg-[var(--green)] text-black hover:opacity-90 transition-opacity disabled:opacity-60"
            >
              {doneActions.has(i) ? <Check size={10} strokeWidth={3} /> : <Plus size={10} />}
              {doneActions.has(i) ? "Done!" : action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
