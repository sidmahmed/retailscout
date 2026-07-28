"use client";

import { Trash2 } from "lucide-react";

import { LocationColumn } from "@/components/locations/ComparisonColumn";
import type { StagedLocation } from "@/lib/locations";
import type { BusinessProfile } from "@/lib/api/types";

interface Props {
  activeId: string | null;
  locations: StagedLocation[];
  profile: BusinessProfile;
  onActivate: (id: string) => void;
  onClear: () => void;
  onRemove: (id: string) => void;
}

export function ComparisonTray({
  activeId,
  locations,
  profile,
  onActivate,
  onClear,
  onRemove,
}: Props) {
  return (
    <aside
      aria-label="Location comparison"
      className="pointer-events-auto flex max-h-[48dvh] min-h-72 overflow-hidden rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-xl"
    >
      <div className="flex w-44 shrink-0 flex-col justify-between border-r border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--accent-primary)]">
            Compare
          </p>
          <h2 className="mt-1 text-base font-semibold tracking-tight">
            {locations.length} locations
          </h2>
          <p className="mt-2 text-xs leading-relaxed text-[var(--text-muted)]">
            City-wide percentiles paired with the raw evidence behind them.
          </p>
        </div>
        <button
          className="mt-4 inline-flex items-center gap-1.5 self-start rounded-md px-2 py-1.5 text-xs text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]"
          onClick={onClear}
          type="button"
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
          Clear comparison
        </button>
      </div>

      <div className="flex flex-1 overflow-auto">
        {locations.map((location, index) => (
          <LocationColumn
            active={location.id === activeId}
            index={index}
            key={location.id}
            location={location}
            onActivate={() => onActivate(location.id)}
            onRemove={() => onRemove(location.id)}
            profile={profile}
          />
        ))}
      </div>
    </aside>
  );
}
