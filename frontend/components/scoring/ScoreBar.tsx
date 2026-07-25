"use client";

/**
 * One component-score row: label + weight, horizontal bar, value.
 * A null score means the component was NOT computed (evidence missing,
 * reweighted out per architecture §15.5) — it renders as an explicit
 * "Not computed" state, never as an empty/zero bar (invariant 4).
 */

import type { ComponentScore } from "@/lib/api/types";
import { scoreBandVar } from "@/lib/tokens";

const COMPONENT_LABELS: Record<string, string> = {
  pedestrian_demand: "Foot traffic",
  worker_demand: "Worker population",
  competition: "Market openness",
  transport: "Transport access",
  development: "Development pipeline",
};

export function ScoreBar({ component }: { component: ComponentScore }) {
  const label = COMPONENT_LABELS[component.key] ?? component.key;
  const score = component.score ?? null;

  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{label}</span>
        {score === null ? (
          <span className="text-xs italic text-[var(--text-muted)]">
            Not computed — insufficient evidence
          </span>
        ) : (
          <span className="numeric font-semibold">{score}</span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--bg-surface-muted)]">
          {score !== null && (
            <div
              className="h-full rounded-full"
              style={{ width: `${score}%`, background: scoreBandVar(score) }}
            />
          )}
        </div>
        <span className="numeric w-10 text-right text-[11px] text-[var(--text-muted)]">
          {component.weight}%
        </span>
      </div>
    </div>
  );
}
