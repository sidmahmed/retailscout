"use client";

/**
 * Segmented control over the published business profiles
 * (/api/v1/business-profiles — DB-driven, so a newly published profile
 * appears without a frontend change).
 */

import { useProfiles } from "@/lib/api/hooks";
import type { BusinessProfile } from "@/lib/api/types";

interface Props {
  value: BusinessProfile;
  onChange: (profile: BusinessProfile) => void;
}

export function ProfileSwitcher({ value, onChange }: Props) {
  const { data: profiles, isPending, isError } = useProfiles();

  if (isPending) {
    return (
      <div className="h-9 w-64 animate-pulse rounded-md bg-[var(--bg-surface-muted)]" />
    );
  }
  if (isError || !profiles) return null;

  return (
    <div
      role="radiogroup"
      aria-label="Business profile"
      className="flex rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] p-0.5 shadow-sm"
    >
      {profiles.map((p) => {
        const active = p.id === value;
        return (
          <button
            key={p.id}
            role="radio"
            aria-checked={active}
            title={p.description}
            onClick={() => onChange(p.id as BusinessProfile)}
            className={
              "rounded-[5px] px-3 py-1.5 text-sm font-medium transition-colors " +
              (active
                ? "bg-[var(--accent-primary)] text-white"
                : "text-[var(--text-muted)] hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]")
            }
          >
            {p.label}
          </button>
        );
      })}
    </div>
  );
}
