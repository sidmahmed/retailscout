"use client";

import { useState } from "react";

import type {
  DaypartEstimate,
  DaypartFootTraffic,
} from "@/lib/api/types";
import { CONFIDENCE_LABELS, confidenceVar } from "@/lib/tokens";

const DAY_TYPE_ORDER = ["weekday", "saturday", "sunday"];
const DAYPART_ORDER = ["morning", "lunch", "afternoon", "evening"];

const LABELS: Record<string, string> = {
  weekday: "Weekday",
  saturday: "Saturday",
  sunday: "Sunday",
  morning: "Morning",
  lunch: "Lunch",
  afternoon: "Afternoon",
  evening: "Evening",
};

function ordered(values: string[], preferred: string[]): string[] {
  return [...values].sort((a, b) => {
    const aIndex = preferred.indexOf(a);
    const bIndex = preferred.indexOf(b);
    if (aIndex === -1 && bIndex === -1) return a.localeCompare(b);
    if (aIndex === -1) return 1;
    if (bIndex === -1) return -1;
    return aIndex - bIndex;
  });
}

function preferredIndex(value: string, preferred: string[]): number {
  const index = preferred.indexOf(value);
  return index === -1 ? preferred.length : index;
}

function label(value: string): string {
  return LABELS[value] ?? value.replaceAll("_", " ");
}

function sensorSummary(estimates: DaypartEstimate[]): string {
  const sensorCounts = estimates.map((estimate) => estimate.n_sensors);
  const nearestDistance = Math.min(
    ...estimates.map((estimate) => estimate.nearest_sensor_m),
  );
  const minSensors = Math.min(...sensorCounts);
  const maxSensors = Math.max(...sensorCounts);
  const count =
    minSensors === maxSensors ? String(minSensors) : `${minSensors}–${maxSensors}`;

  return `Modelled from ${count} nearby ${maxSensors === 1 ? "sensor" : "sensors"}; nearest is ${Math.round(nearestDistance).toLocaleString()} m away.`;
}

export function DaypartChart({
  traffic,
}: {
  traffic: DaypartFootTraffic | null;
}) {
  const [requestedDayType, setRequestedDayType] = useState("weekday");

  if (!traffic || traffic.estimates.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface-muted)] px-3 py-3">
        <p className="text-sm font-medium">No foot-traffic estimate</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--text-muted)]">
          No pedestrian sensor is close enough to model this location reliably.
          Missing evidence is not treated as zero.
        </p>
      </div>
    );
  }

  const dayTypes = ordered(
    [...new Set(traffic.estimates.map((estimate) => estimate.day_type))],
    DAY_TYPE_ORDER,
  );
  const selectedDayType = dayTypes.includes(requestedDayType)
    ? requestedDayType
    : dayTypes[0];
  const estimates = traffic.estimates
    .filter((estimate) => estimate.day_type === selectedDayType)
    .sort(
      (a, b) =>
        preferredIndex(a.daypart, DAYPART_ORDER) -
          preferredIndex(b.daypart, DAYPART_ORDER) ||
        a.daypart.localeCompare(b.daypart),
    );
  const maxEstimate = Math.max(
    ...estimates.map((estimate) => estimate.pedestrian_estimate),
    1,
  );

  return (
    <div>
      <div
        aria-label="Day type"
        className="mb-4 grid grid-flow-col auto-cols-fr gap-1 rounded-lg bg-[var(--bg-surface-muted)] p-1"
        role="group"
      >
        {dayTypes.map((dayType) => {
          const selected = dayType === selectedDayType;
          return (
            <button
              aria-pressed={selected}
              className={`rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                selected
                  ? "bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-sm"
                  : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              }`}
              key={dayType}
              onClick={() => setRequestedDayType(dayType)}
              type="button"
            >
              {label(dayType)}
            </button>
          );
        })}
      </div>

      <div
        aria-label={`${label(selectedDayType)} modelled foot traffic by daypart`}
        className="space-y-3"
        role="group"
      >
        {estimates.map((estimate) => {
          const width = `${(estimate.pedestrian_estimate / maxEstimate) * 100}%`;
          const confidenceColor = confidenceVar(estimate.confidence);
          return (
            <div key={`${estimate.day_type}-${estimate.daypart}`}>
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="text-xs font-medium">{label(estimate.daypart)}</span>
                <span className="numeric text-xs font-semibold">
                  {Math.round(estimate.pedestrian_estimate).toLocaleString()}
                  <span className="ml-1 font-normal text-[var(--text-muted)]">/ hr</span>
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[var(--bg-surface-muted)]">
                  <div
                    className="h-full min-w-1 rounded-full bg-[var(--accent-primary)] transition-[width] duration-300"
                    style={{ width }}
                  />
                </div>
                <span
                  aria-label={CONFIDENCE_LABELS[estimate.confidence]}
                  className="h-2 w-2 shrink-0 rounded-full"
                  role="img"
                  style={{ background: confidenceColor }}
                  title={CONFIDENCE_LABELS[estimate.confidence]}
                />
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-xs leading-relaxed text-[var(--text-muted)]">
        {sensorSummary(estimates)} Estimates are typical hourly activity, not
        observed storefront counts.
      </p>
    </div>
  );
}
