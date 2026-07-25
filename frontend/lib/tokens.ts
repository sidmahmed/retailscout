/**
 * Design-token access for code that can't use CSS variables directly —
 * MapLibre paint expressions need literal color strings. Values are read
 * from the CSS custom properties at runtime so globals.css stays the
 * single source of truth (ui-context.md: hardcoded hex is a violation).
 */
import type { ConfidenceBand } from "./api/types";

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function scoreColors(): { low: string; mid: string; high: string } {
  return {
    low: cssVar("--score-low"),
    mid: cssVar("--score-mid"),
    high: cssVar("--score-high"),
  };
}

/** Score bands per ui-context.md: 0-33 low, 34-66 mid, 67-100 high. */
export function scoreBandVar(score: number): string {
  if (score <= 33) return "var(--score-low)";
  if (score <= 66) return "var(--score-mid)";
  return "var(--score-high)";
}

export function confidenceVar(band: ConfidenceBand): string {
  return `var(--confidence-${band})`;
}

export const CONFIDENCE_LABELS: Record<ConfidenceBand, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
  insufficient: "Insufficient data",
};
