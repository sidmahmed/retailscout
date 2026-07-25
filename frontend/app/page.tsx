"use client";

/**
 * Explore — the primary product surface (ui-context.md §Layout
 * Patterns): full-height MapLibre map, brand + profile controls docked
 * top, legend bottom-left, score drawer sliding in from the right on
 * location selection. Desktop-first; the mobile bottom-sheet variant is
 * tracked in context/frontend-handoff.md.
 */

import dynamic from "next/dynamic";
import { useState } from "react";

import { MapLegend } from "@/components/map/MapLegend";
import { ProfileSwitcher } from "@/components/map/ProfileSwitcher";
import type { SelectedPoint } from "@/components/map/SuitabilityMap";
import { ScoreDrawer } from "@/components/scoring/ScoreDrawer";
import { useCoverage } from "@/lib/api/hooks";
import type { BusinessProfile } from "@/lib/api/types";

// MapLibre touches window at module scope — client-only import.
const SuitabilityMap = dynamic(
  () => import("@/components/map/SuitabilityMap").then((m) => m.SuitabilityMap),
  { ssr: false },
);

export default function ExplorePage() {
  const [profile, setProfile] = useState<BusinessProfile>("cafe");
  const [selected, setSelected] = useState<SelectedPoint | null>(null);
  const { data: coverage } = useCoverage();

  return (
    <main className="relative h-dvh w-full overflow-hidden">
      <SuitabilityMap profile={profile} selected={selected} onSelect={setSelected} />

      {/* Top-docked controls */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex flex-wrap items-center gap-3 p-4">
        <div className="pointer-events-auto flex items-center gap-2.5 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3.5 py-2 shadow-sm">
          <span
            aria-hidden
            className="h-2.5 w-2.5 rounded-sm"
            style={{ background: "var(--accent-primary)" }}
          />
          <h1 className="text-sm font-semibold tracking-tight">RetailScout</h1>
          <span className="hidden text-xs text-[var(--text-muted)] sm:inline">
            {coverage?.municipality ?? "City of Melbourne"}
          </span>
        </div>
        <div className="pointer-events-auto">
          <ProfileSwitcher value={profile} onChange={setProfile} />
        </div>
      </div>

      {/* Bottom-left legend + attribution-adjacent hint */}
      <div className="absolute bottom-6 left-4 z-10 space-y-2">
        <MapLegend />
        {!selected && (
          <p className="max-w-44 rounded-md bg-[var(--bg-surface)]/85 px-2 py-1 text-[11px] leading-snug text-[var(--text-muted)] backdrop-blur">
            Click anywhere on the map to score that location.
          </p>
        )}
      </div>

      {/* Right-side score drawer */}
      {selected && (
        <div className="pointer-events-none absolute inset-y-0 right-0 z-20 flex w-full max-w-md py-0 sm:py-4 sm:pr-0">
          <ScoreDrawer
            point={selected}
            profile={profile}
            onClose={() => setSelected(null)}
          />
        </div>
      )}
    </main>
  );
}
