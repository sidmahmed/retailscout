"use client";

import { AlertTriangle, ArrowUpRight, Trash2, X } from "lucide-react";

import { ConfidenceBadge } from "@/components/scoring/ConfidenceBadge";
import { OutsideBoundaryError } from "@/lib/api/client";
import { useScore } from "@/lib/api/hooks";
import type { StagedLocation } from "@/lib/locations";
import type {
  BusinessProfile,
  ComponentScore,
  ScoreResponse,
} from "@/lib/api/types";
import { scoreBandVar } from "@/lib/tokens";

const COMPONENT_LABELS: Record<string, string> = {
  pedestrian_demand: "Foot traffic",
  worker_demand: "Worker population",
  competition: "Market openness",
  transport: "Transport access",
  development: "Development pipeline",
};

const EVIDENCE_LABELS: Record<string, string> = {
  weekday_avg_estimate: "estimated pedestrians / hr",
  jobs_800m: "jobs within 800 m",
  cafe_competitors_400m: "similar businesses within 400 m",
  transit_stops: "nearby transit stops",
  pipeline_people_800m: "pipeline people within 800 m",
  pipeline_projects_800m: "pipeline projects within 800 m",
};

interface Props {
  activeId: string | null;
  locations: StagedLocation[];
  profile: BusinessProfile;
  onActivate: (id: string) => void;
  onClear: () => void;
  onRemove: (id: string) => void;
}

function formatValue(value: number | string | null): string {
  if (value === null) return "not observed";
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
  return value;
}

function percentile(score: number): string {
  const rounded = Math.round(score);
  const remainder = rounded % 100;
  const suffix =
    remainder >= 11 && remainder <= 13
      ? "th"
      : rounded % 10 === 1
        ? "st"
        : rounded % 10 === 2
          ? "nd"
          : rounded % 10 === 3
            ? "rd"
            : "th";
  return `${rounded}${suffix} percentile`;
}

function RawEvidence({ component }: { component: ComponentScore }) {
  const entries = Object.entries(component.evidence ?? {}).filter(
    ([key]) => key !== "note",
  );

  if (entries.length === 0) {
    return (
      <p className="mt-1 text-[11px] italic text-[var(--text-muted)]">
        Raw evidence unavailable
      </p>
    );
  }

  return (
    <dl className="mt-1 space-y-0.5">
      {entries.map(([key, value]) => (
        <div className="flex items-baseline justify-between gap-2" key={key}>
          <dt className="truncate text-[11px] text-[var(--text-muted)]">
            {EVIDENCE_LABELS[key] ?? key.replaceAll("_", " ")}
          </dt>
          <dd className="numeric shrink-0 text-[11px] font-medium">
            {formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ComponentComparison({ component }: { component: ComponentScore }) {
  const score = component.score ?? null;

  return (
    <div className="min-h-24 border-t border-[var(--border-default)] px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-xs font-medium">
          {COMPONENT_LABELS[component.key] ?? component.key.replaceAll("_", " ")}
        </p>
        {score === null ? (
          <span className="text-[11px] italic text-[var(--text-muted)]">
            Not computed
          </span>
        ) : (
          <span className="numeric shrink-0 text-xs font-semibold">
            {percentile(score)}
          </span>
        )}
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--bg-surface-muted)]">
        {score !== null && (
          <div
            className="h-full rounded-full"
            style={{ background: scoreBandVar(score), width: `${score}%` }}
          />
        )}
      </div>
      <RawEvidence component={component} />
    </div>
  );
}

function LocationColumn({
  active,
  index,
  location,
  profile,
  onActivate,
  onRemove,
}: {
  active: boolean;
  index: number;
  location: StagedLocation;
  profile: BusinessProfile;
  onActivate: () => void;
  onRemove: () => void;
}) {
  const { data, error, isPending } = useScore(location.point, profile);
  const label = `Location ${index + 1}`;

  return (
    <article
      aria-label={`${label} comparison`}
      className={`relative w-64 shrink-0 border-l border-[var(--border-default)] ${
        active ? "bg-[var(--bg-surface)]" : "bg-[var(--bg-base)]"
      }`}
    >
      {active && (
        <span
          aria-hidden
          className="absolute inset-x-0 top-0 h-0.5 bg-[var(--accent-primary)]"
        />
      )}
      <header className="sticky top-0 z-10 border-b border-[var(--border-default)] bg-[inherit] px-3 py-3">
        <div className="flex items-start justify-between gap-2">
          <button
            aria-label={`Open ${label} details`}
            className="group min-w-0 text-left"
            onClick={onActivate}
            type="button"
          >
            <span className="flex items-center gap-1 text-xs font-semibold">
              <span className="flex h-5 w-5 items-center justify-center rounded-full border border-[var(--accent-primary)] text-[10px] text-[var(--accent-primary)]">
                {index + 1}
              </span>
              {label}
              <ArrowUpRight
                className="h-3.5 w-3.5 text-[var(--text-muted)] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                strokeWidth={1.5}
              />
            </span>
            <span className="numeric mt-1 block truncate text-[10px] text-[var(--text-muted)]">
              {location.point.lat.toFixed(5)}, {location.point.lon.toFixed(5)}
            </span>
          </button>
          <button
            aria-label={`Remove ${label} from comparison`}
            className="rounded-md p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]"
            onClick={onRemove}
            type="button"
          >
            <X className="h-4 w-4" strokeWidth={1.5} />
          </button>
        </div>

        {data && <ScoreSummary data={data} />}
        {isPending && (
          <div className="mt-3 h-8 animate-pulse rounded-md bg-[var(--bg-surface-muted)]" />
        )}
      </header>

      {data &&
        data.components.map((component) => (
          <ComponentComparison component={component} key={component.key} />
        ))}

      {error && (
        <div className="flex min-h-48 flex-col items-center justify-center px-4 text-center">
          <AlertTriangle
            className="mb-2 h-5 w-5 text-[var(--state-error)]"
            strokeWidth={1.5}
          />
          <p className="text-xs font-semibold">
            {error instanceof OutsideBoundaryError
              ? "Outside the analysis area"
              : "Score unavailable"}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-muted)]">
            Remove this location or choose another point within the scored hexes.
          </p>
        </div>
      )}
    </article>
  );
}

function ScoreSummary({ data }: { data: ScoreResponse }) {
  const score = data.score ?? null;

  return (
    <div className="mt-3 flex items-end justify-between gap-2">
      <div>
        <span
          className="numeric text-3xl font-semibold leading-none"
          style={score !== null ? { color: scoreBandVar(score) } : undefined}
        >
          {score !== null ? Math.round(score) : "—"}
        </span>
        <span className="ml-1 text-[11px] text-[var(--text-muted)]">/ 100</span>
      </div>
      <ConfidenceBadge band={data.confidence.band} />
    </div>
  );
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
