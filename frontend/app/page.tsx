"use client";

/**
 * Explore — the primary product surface (ui-context.md §Layout
 * Patterns): full-height MapLibre map, brand + profile controls docked
 * top, legend bottom-left, score drawer opening on location selection —
 * a bottom sheet below `sm`, sliding in from the right at `sm` and up.
 */

import dynamic from "next/dynamic";
import { useRef, useState } from "react";

import { ComparisonTray } from "@/components/locations/ComparisonTray";
import { LocationSearch } from "@/components/locations/LocationSearch";
import { MapLegend } from "@/components/map/MapLegend";
import { ProfileSwitcher } from "@/components/map/ProfileSwitcher";
import { ScoreDrawer } from "@/components/scoring/ScoreDrawer";
import { useCoverage } from "@/lib/api/hooks";
import type { SelectedPoint, StagedLocation } from "@/lib/locations";
import type { BusinessProfile } from "@/lib/api/types";

// MapLibre touches window at module scope — client-only import.
const SuitabilityMap = dynamic(
  () => import("@/components/map/SuitabilityMap").then((m) => m.SuitabilityMap),
  { ssr: false },
);

export default function ExplorePage() {
  const [profile, setProfile] = useState<BusinessProfile>("cafe");
  const [staged, setStaged] = useState<StagedLocation[]>([]);
  const [activeLocation, setActiveLocation] = useState<StagedLocation | null>(
    null,
  );
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [mapFocus, setMapFocus] = useState<SelectedPoint | null>(null);
  const nextLocationId = useRef(1);
  const { data: coverage } = useCoverage();
  const activeIndex = staged.findIndex(
    (location) => location.id === activeLocation?.id,
  );
  const activeIsCompared = activeIndex >= 0;

  function selectLocation(point: SelectedPoint) {
    const id = `location-${nextLocationId.current}`;
    nextLocationId.current += 1;
    setActiveLocation({ id, point });
    setComparisonOpen(false);
  }

  function selectSearchResult(point: SelectedPoint) {
    selectLocation(point);
    setMapFocus(point);
  }

  function toggleActiveComparison() {
    if (!activeLocation) return;

    if (activeIsCompared) {
      setStaged((current) =>
        current.filter((location) => location.id !== activeLocation.id),
      );
      return;
    }

    const next = [...staged, activeLocation];
    setStaged(next);
    if (next.length >= 2) {
      setActiveLocation(null);
      setComparisonOpen(true);
    }
  }

  function removeComparisonLocation(id: string) {
    const removedIndex = staged.findIndex((location) => location.id === id);
    if (removedIndex === -1) return;

    const remaining = staged.filter((location) => location.id !== id);
    setStaged(remaining);

    if (remaining.length < 2) {
      const fallbackIndex = Math.min(removedIndex, remaining.length - 1);
      setActiveLocation(
        fallbackIndex >= 0 ? remaining[fallbackIndex] : null,
      );
      setComparisonOpen(false);
    }
  }

  function openLocationDetails(id: string) {
    const location = staged.find((candidate) => candidate.id === id);
    if (!location) return;
    setActiveLocation(location);
    setComparisonOpen(false);
  }

  function openComparison() {
    setActiveLocation(null);
    setComparisonOpen(true);
  }

  function clearComparison() {
    setStaged([]);
    setActiveLocation(null);
    setComparisonOpen(false);
  }

  return (
    <main className="relative h-dvh w-full overflow-hidden">
      <SuitabilityMap
        activeLocation={activeLocation}
        focusPoint={mapFocus}
        onSelect={selectLocation}
        profile={profile}
        staged={staged}
      />

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
          <LocationSearch bounds={coverage?.bounds} onSelect={selectSearchResult} />
        </div>
        <div className="pointer-events-auto">
          <ProfileSwitcher value={profile} onChange={setProfile} />
        </div>
      </div>

      {/* Bottom-left legend + attribution-adjacent hint */}
      <div
        className={`absolute bottom-6 left-4 z-10 space-y-2 ${
          comparisonOpen ? "sm:hidden" : ""
        } ${activeLocation && !comparisonOpen ? "hidden sm:block" : ""}`}
      >
        <MapLegend />
        {!activeLocation && staged.length === 0 && (
          <p className="max-w-44 rounded-md bg-[var(--bg-surface)]/85 px-2 py-1 text-[11px] leading-snug text-[var(--text-muted)] backdrop-blur">
            Click anywhere on the map to score that location.
          </p>
        )}
        {staged.length === 1 && !comparisonOpen && (
          <p className="max-w-48 rounded-md bg-[var(--bg-surface)]/85 px-2 py-1 text-[11px] leading-snug text-[var(--text-muted)] backdrop-blur">
            One location staged. Select another, then choose Compare.
          </p>
        )}
      </div>

      {/* Score drawer — bottom sheet on mobile, right-side panel from sm up */}
      {activeLocation && !comparisonOpen && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:w-full sm:max-w-md sm:py-4 sm:pr-0">
          <ScoreDrawer
            inComparison={activeIsCompared}
            label={
              activeIsCompared ? `Location ${activeIndex + 1}` : "Selected location"
            }
            onClose={() => setActiveLocation(null)}
            onToggleComparison={toggleActiveComparison}
            point={activeLocation.point}
            profile={profile}
          />
        </div>
      )}

      {/* Desktop comparison bench — columns stay in selection order. */}
      {comparisonOpen && staged.length >= 2 && (
        <div className="pointer-events-none absolute bottom-4 left-4 right-4 z-10 hidden sm:block">
          <ComparisonTray
            activeId={null}
            locations={staged}
            onActivate={openLocationDetails}
            onClear={clearComparison}
            onRemove={removeComparisonLocation}
            profile={profile}
          />
        </div>
      )}

      {/* Comparison is an explicit workspace, never a side effect of map clicks. */}
      {!comparisonOpen && staged.length >= 2 && (
        <button
          className="pointer-events-auto absolute bottom-6 left-1/2 z-10 hidden -translate-x-1/2 rounded-lg border border-[var(--accent-primary)] bg-[var(--bg-surface)] px-4 py-2 text-sm font-semibold text-[var(--accent-primary)] shadow-lg transition-colors hover:bg-[var(--bg-surface-muted)] sm:block"
          onClick={openComparison}
          type="button"
        >
          Compare {staged.length} locations
        </button>
      )}
    </main>
  );
}
