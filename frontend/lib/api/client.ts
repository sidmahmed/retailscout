/**
 * Fetch layer for the RetailScout API. Every response crosses this
 * boundary through a zod schema (code-standards: validate external data
 * at the boundary) and is then returned under the generated OpenAPI
 * types, so components get both runtime safety and static types.
 *
 * Same-origin paths only — next.config.mjs rewrites /api/v1/* to the
 * FastAPI dev server locally and the platform routes it in production.
 */
import { z } from "zod";

import type {
  BusinessProfile,
  Coverage,
  ProfileInfo,
  ScoreResponse,
} from "./types";

/** FR-02: the point is outside the City of Melbourne analysis area. */
export class OutsideBoundaryError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "OutsideBoundaryError";
  }
}

/** 503 — no database / no published release behind the API. */
export class ServiceUnavailableError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "ServiceUnavailableError";
  }
}

const componentScoreSchema = z.object({
  key: z.string(),
  // null = not computed (§15.5 reweighting) — distinct from 0, always.
  score: z.number().nullish(),
  weight: z.number(),
  evidence: z.record(z.union([z.number(), z.string(), z.null()])).optional(),
});

const daypartEstimateSchema = z.object({
  day_type: z.string(),
  daypart: z.string(),
  pedestrian_estimate: z.number().nonnegative(),
  confidence: z.enum(["high", "medium", "low", "insufficient"]),
  n_sensors: z.number().int().positive(),
  nearest_sensor_m: z.number().nonnegative(),
});

const scoreResponseSchema = z.object({
  location: z.object({ lat: z.number(), lon: z.number(), cell_id: z.string() }),
  profile: z.enum(["cafe", "retail_shop", "food_truck", "pop_up"]),
  score: z.number().nullish(),
  confidence: z.object({
    score: z.number(),
    band: z.enum(["high", "medium", "low", "insufficient"]),
    reasons: z.array(z.string()),
  }),
  components: z.array(componentScoreSchema),
  top_drivers: z.array(z.string()).optional(),
  top_risks: z.array(z.string()).optional(),
  daypart_foot_traffic: z
    .object({
      baseline_version: z.string(),
      estimates: z.array(daypartEstimateSchema),
    })
    .nullable(),
  score_version: z.string(),
  data_release: z.string(),
  generated_at: z.string(),
});

const profilesSchema = z.array(
  z.object({ id: z.string(), label: z.string(), description: z.string() }),
);

const coverageSchema = z.object({
  municipality: z.string(),
  data_release: z.string(),
  boundary: z.record(z.unknown()),
  bounds: z.array(z.number()).length(4),
});

async function detailOf(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string") return d;
    }
  } catch {
    // fall through — non-JSON error body
  }
  return `Request failed (${res.status})`;
}

async function getJson(path: string): Promise<unknown> {
  const res = await fetch(path);
  if (res.ok) return res.json();
  const detail = await detailOf(res);
  if (res.status === 400) throw new OutsideBoundaryError(detail);
  if (res.status === 503) throw new ServiceUnavailableError(detail);
  throw new Error(detail);
}

export async function fetchScore(
  lat: number,
  lon: number,
  profile: BusinessProfile,
): Promise<ScoreResponse> {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    profile,
  });
  const data = await getJson(`/api/v1/locations/score?${params}`);
  return scoreResponseSchema.parse(data) as ScoreResponse;
}

export async function fetchProfiles(): Promise<ProfileInfo[]> {
  const data = await getJson("/api/v1/business-profiles");
  return profilesSchema.parse(data);
}

export async function fetchCoverage(): Promise<Coverage> {
  const data = await getJson("/api/v1/coverage");
  return coverageSchema.parse(data) as Coverage;
}

/** Tile URL template for the MapLibre vector source (layer "suitability",
 * feature props: cell_id, total_score, confidence_score). */
export function suitabilityTileUrl(profile: BusinessProfile): string {
  return `${window.location.origin}/api/v1/tiles/suitability/${profile}/{z}/{x}/{y}.mvt`;
}
