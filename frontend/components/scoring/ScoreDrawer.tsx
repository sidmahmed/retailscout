"use client";

/**
 * Location result panel. Evidence order is FIXED by architecture §18.3 /
 * ui-context.md and must not be reordered between screens:
 *   1. suitability score + confidence (separate visual systems)
 *   2. one-sentence interpretation
 *   3. component score bars
 *   4. top drivers and risks
 *   5. supporting evidence (raw values behind the components)
 *   6. source freshness / limitations
 * The daypart foot-traffic chart and nearby-business breakdown belong
 * between 4 and 5 once their API endpoints exist — see
 * context/frontend-handoff.md.
 */

import {
  AlertTriangle,
  Info,
  MapPinOff,
  ServerOff,
  TrendingUp,
  X,
} from "lucide-react";

import { OutsideBoundaryError, ServiceUnavailableError } from "@/lib/api/client";
import { useScore } from "@/lib/api/hooks";
import type { BusinessProfile, ScoreResponse } from "@/lib/api/types";
import { scoreBandVar } from "@/lib/tokens";

import { ConfidenceBadge } from "./ConfidenceBadge";
import { ScoreBar } from "./ScoreBar";

const PROFILE_LABELS: Record<BusinessProfile, string> = {
  cafe: "café",
  retail_shop: "retail shop",
  food_truck: "food truck",
  pop_up: "pop-up",
};

const EVIDENCE_LABELS: Record<string, string> = {
  weekday_avg_estimate: "Est. weekday pedestrians/day",
  jobs_800m: "Jobs within 800 m",
  cafe_competitors_400m: "Similar businesses within 400 m",
  transit_stops: "Transit stops nearby",
};

function interpretation(data: ScoreResponse): string {
  const profile = PROFILE_LABELS[data.profile];
  const s = data.score;
  if (s === null || s === undefined) {
    return `Not enough evidence to score this location for a ${profile} — the data gap itself is the finding.`;
  }
  const strength =
    s >= 67
      ? `One of the stronger locations in the municipality for a ${profile}.`
      : s >= 34
        ? `A middling location for a ${profile} — the component breakdown shows where it gains and loses.`
        : `A weak location for a ${profile} relative to the rest of the municipality.`;
  return strength;
}

function formatEvidenceValue(v: number | string | null): string {
  if (v === null) return "not observed";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1);
  }
  return v;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-[var(--border-default)] px-5 py-4">
      <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        {title}
      </h3>
      {children}
    </section>
  );
}

interface Props {
  point: { lat: number; lon: number };
  profile: BusinessProfile;
  onClose: () => void;
}

export function ScoreDrawer({ point, profile, onClose }: Props) {
  const { data, error, isPending } = useScore(point, profile);

  return (
    <aside
      aria-label="Location score"
      className="pointer-events-auto flex h-full w-full max-w-md flex-col overflow-hidden rounded-l-xl border-l border-[var(--border-default)] bg-[var(--bg-surface)] shadow-xl"
    >
      <header className="flex items-center justify-between px-5 py-3.5">
        <div>
          <p className="text-sm font-semibold">Selected location</p>
          <p className="numeric text-xs text-[var(--text-muted)]">
            {point.lat.toFixed(5)}, {point.lon.toFixed(5)}
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]"
        >
          <X className="h-5 w-5" strokeWidth={1.5} />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {isPending && <DrawerSkeleton />}

        {error instanceof OutsideBoundaryError && (
          <EmptyState
            icon={<MapPinOff className="h-5 w-5" strokeWidth={1.5} />}
            title="Outside the analysis area"
            body="RetailScout only scores locations inside the City of Melbourne — its evidence comes from the council's open data, which stops at the municipal boundary. Try a point within the shaded hexes."
          />
        )}

        {error instanceof ServiceUnavailableError && (
          <EmptyState
            icon={<ServerOff className="h-5 w-5" strokeWidth={1.5} />}
            title="Scores temporarily unavailable"
            body="The scoring service can't reach its data right now. Try again shortly."
          />
        )}

        {error &&
          !(error instanceof OutsideBoundaryError) &&
          !(error instanceof ServiceUnavailableError) && (
            <EmptyState
              icon={<AlertTriangle className="h-5 w-5" strokeWidth={1.5} />}
              title="Something went wrong"
              body={error.message}
            />
          )}

        {data && <ScoreContent data={data} />}
      </div>
    </aside>
  );
}

function ScoreContent({ data }: { data: ScoreResponse }) {
  const score = data.score ?? null;
  const drivers = data.top_drivers ?? [];
  const risks = data.top_risks ?? [];
  const evidenced = data.components.filter(
    (c) => c.evidence && Object.keys(c.evidence).some((k) => k !== "note"),
  );

  return (
    <>
      {/* 1 — suitability + confidence */}
      <div className="px-5 pb-4">
        <div className="flex items-end justify-between">
          <div>
            <span
              className="numeric text-5xl font-semibold leading-none"
              style={score !== null ? { color: scoreBandVar(score) } : undefined}
            >
              {score !== null ? Math.round(score) : "—"}
            </span>
            <span className="ml-1.5 text-sm text-[var(--text-muted)]">/ 100</span>
          </div>
          <ConfidenceBadge band={data.confidence.band} />
        </div>
        {/* 2 — one-sentence interpretation */}
        <p className="mt-3 text-sm leading-relaxed text-[var(--text-primary)]">
          {interpretation(data)}
        </p>
      </div>

      {/* 3 — component score bars */}
      <Section title="Score components">
        <div className="space-y-3.5">
          {data.components.map((c) => (
            <ScoreBar key={c.key} component={c} />
          ))}
        </div>
      </Section>

      {/* 4 — drivers and risks */}
      {(drivers.length > 0 || risks.length > 0) && (
        <Section title="What drives this score">
          <ul className="space-y-2 text-sm">
            {drivers.map((d) => (
              <li key={d} className="flex gap-2">
                <TrendingUp
                  className="mt-0.5 h-4 w-4 shrink-0"
                  strokeWidth={1.5}
                  style={{ color: "var(--state-success)" }}
                />
                <span>{d}</span>
              </li>
            ))}
            {risks.map((r) => (
              <li key={r} className="flex gap-2">
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0"
                  strokeWidth={1.5}
                  style={{ color: "var(--state-error)" }}
                />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* 5 — raw evidence behind the components */}
      {evidenced.length > 0 && (
        <Section title="Evidence">
          <dl className="space-y-1.5 text-sm">
            {evidenced.flatMap((c) =>
              Object.entries(c.evidence ?? {})
                .filter(([k]) => k !== "note")
                .map(([k, v]) => (
                  <div key={`${c.key}-${k}`} className="flex justify-between gap-4">
                    <dt className="text-[var(--text-muted)]">
                      {EVIDENCE_LABELS[k] ?? k.replaceAll("_", " ")}
                    </dt>
                    <dd className="numeric font-medium">{formatEvidenceValue(v)}</dd>
                  </div>
                )),
            )}
          </dl>
        </Section>
      )}

      {/* confidence reasons — why to trust (or not) the number above */}
      <Section title="Data confidence">
        <ul className="space-y-1.5 text-sm text-[var(--text-muted)]">
          {data.confidence.reasons.map((r) => (
            <li key={r} className="flex gap-2">
              <Info className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.5} />
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </Section>

      {/* 6 — source freshness / limitations */}
      <Section title="Sources">
        <p className="text-xs leading-relaxed text-[var(--text-muted)]">
          Data release <span className="numeric">{data.data_release}</span> · score
          version <span className="numeric">{data.score_version}</span>. Data: City
          of Melbourne Open Data. Scores are decision-support estimates relative to
          the rest of the municipality, not predictions of business success.
        </p>
      </Section>
    </>
  );
}

function EmptyState({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="px-5 py-8 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--bg-surface-muted)] text-[var(--text-muted)]">
        {icon}
      </div>
      <p className="text-sm font-semibold">{title}</p>
      <p className="mx-auto mt-1.5 max-w-xs text-sm leading-relaxed text-[var(--text-muted)]">
        {body}
      </p>
    </div>
  );
}

function DrawerSkeleton() {
  return (
    <div className="animate-pulse space-y-4 px-5 pb-6">
      <div className="h-12 w-24 rounded-md bg-[var(--bg-surface-muted)]" />
      <div className="h-4 w-3/4 rounded bg-[var(--bg-surface-muted)]" />
      <div className="space-y-3 pt-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-8 rounded bg-[var(--bg-surface-muted)]" />
        ))}
      </div>
    </div>
  );
}
