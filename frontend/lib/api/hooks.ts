/**
 * React Query hooks — the only way components consume server state
 * (code-standards: no ad-hoc fetch in components). Score/coverage data
 * only changes when a new release is published, so staleTime is long.
 */
"use client";

import { useQuery } from "@tanstack/react-query";

import {
  OutsideBoundaryError,
  fetchCoverage,
  fetchProfiles,
  fetchScore,
  geocodeAddress,
} from "./client";
import type { BusinessProfile } from "./types";

const RELEASE_STALE_MS = 60 * 60 * 1000;

export function useProfiles() {
  return useQuery({
    queryKey: ["profiles"],
    queryFn: fetchProfiles,
    staleTime: RELEASE_STALE_MS,
  });
}

export function useCoverage() {
  return useQuery({
    queryKey: ["coverage"],
    queryFn: fetchCoverage,
    staleTime: RELEASE_STALE_MS,
  });
}

export function useGeocode(query: string | null, bounds: number[] | undefined) {
  return useQuery({
    queryKey: ["geocode", query, bounds?.join(",")],
    queryFn: () => {
      if (!query || !bounds) throw new Error("search is not ready");
      return geocodeAddress(query, bounds);
    },
    enabled: query !== null && bounds !== undefined,
    staleTime: 24 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    retry: 1,
  });
}

export function useScore(
  point: { lat: number; lon: number } | null,
  profile: BusinessProfile,
) {
  return useQuery({
    queryKey: ["score", profile, point?.lat, point?.lon],
    queryFn: () => {
      if (!point) throw new Error("no point selected");
      return fetchScore(point.lat, point.lon, profile);
    },
    enabled: point !== null,
    staleTime: RELEASE_STALE_MS,
    // An out-of-area click is a definitive answer, not a transient fault.
    retry: (failureCount, error) =>
      !(error instanceof OutsideBoundaryError) && failureCount < 2,
  });
}
