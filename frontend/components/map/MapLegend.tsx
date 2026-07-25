"use client";

/**
 * Suitability color legend. Uses the same three band tokens as the tile
 * layer ramp so the legend can never drift from the map.
 */

export function MapLegend() {
  return (
    <div className="rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 shadow-sm">
      <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
        Suitability
      </p>
      <div
        className="h-2 w-36 rounded-full"
        style={{
          background:
            "linear-gradient(to right, var(--score-low), var(--score-mid), var(--score-high))",
        }}
      />
      <div className="mt-1 flex justify-between text-[11px] text-[var(--text-muted)]">
        <span className="numeric">0</span>
        <span className="numeric">50</span>
        <span className="numeric">100</span>
      </div>
    </div>
  );
}
