"use client";

/**
 * Mobile comparison — a separate full screen, not an overlay
 * (ui-context.md §Layout Patterns), reusing the same LocationColumn as
 * the desktop tray so percentiles and raw evidence never drift between
 * screens. Columns are swipe/scroll-snapped one at a time on narrow
 * viewports; tapping a location's header drops back into its full
 * single-location detail (the bottom sheet from ScoreDrawer).
 */

import { ArrowLeft, Trash2 } from "lucide-react";

import { LocationColumn } from "@/components/locations/ComparisonColumn";
import type { StagedLocation } from "@/lib/locations";
import type { BusinessProfile } from "@/lib/api/types";

interface Props {
  locations: StagedLocation[];
  profile: BusinessProfile;
  onActivate: (id: string) => void;
  onClear: () => void;
  onClose: () => void;
  onRemove: (id: string) => void;
}

export function MobileComparisonScreen({
  locations,
  profile,
  onActivate,
  onClear,
  onClose,
  onRemove,
}: Props) {
  return (
    <div
      aria-label="Location comparison"
      className="pointer-events-auto fixed inset-0 z-30 flex flex-col bg-[var(--bg-base)]"
      role="dialog"
    >
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-3">
        <button
          aria-label="Back to map"
          className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]"
          onClick={onClose}
          type="button"
        >
          <ArrowLeft className="h-5 w-5" strokeWidth={1.5} />
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--accent-primary)]">
            Compare
          </p>
          <h2 className="truncate text-sm font-semibold tracking-tight">
            {locations.length} locations
          </h2>
        </div>
        <button
          aria-label="Clear comparison"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]"
          onClick={onClear}
          type="button"
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
          Clear
        </button>
      </header>

      <div className="flex flex-1 snap-x snap-mandatory overflow-x-auto overflow-y-hidden">
        {locations.map((location, index) => (
          <div className="h-full snap-center overflow-y-auto" key={location.id}>
            <LocationColumn
              active
              index={index}
              location={location}
              onActivate={() => onActivate(location.id)}
              onRemove={() => onRemove(location.id)}
              profile={profile}
              widthClassName="w-[88vw] max-w-sm"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
