"use client";

/**
 * Confidence is always shown next to a score, in its own warm/neutral
 * palette (--confidence-*), so a low-confidence high score never reads
 * as a low score (ui-context.md). The filled dot is deliberate — filled
 * icons are reserved for confidence indicators.
 */

import type { ConfidenceBand } from "@/lib/api/types";
import { CONFIDENCE_LABELS, confidenceVar } from "@/lib/tokens";

export function ConfidenceBadge({ band }: { band: ConfidenceBand }) {
  const color = confidenceVar(band);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium"
      style={{ color, borderColor: "var(--border-default)" }}
    >
      <span
        aria-hidden
        className="h-2 w-2 rounded-full"
        style={{ background: color }}
      />
      {CONFIDENCE_LABELS[band]}
    </span>
  );
}
