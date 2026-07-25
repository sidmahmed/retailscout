# Frontend Handoff — remaining work and how to do it

The hard core of the frontend is DONE and verified end-to-end. This
document tells the next developer (human or model) exactly what exists,
the patterns to copy, and what remains — in priority order. Read
`ui-context.md` and `code-standards.md` first; they are binding.

## What exists (do not rebuild)

| Piece | File | Notes |
| --- | --- | --- |
| Typed API layer | `frontend/lib/api/client.ts` | zod-validated fetch; typed errors `OutsideBoundaryError` (400/FR-02) and `ServiceUnavailableError` (503) |
| Type aliases | `frontend/lib/api/types.ts` | ONLY import types from here, never from `schema.ts` (which `make contracts` regenerates) |
| React Query hooks | `frontend/lib/api/hooks.ts` | `useProfiles`, `useCoverage`, `useScore(point, profile)`; 1 h staleTime (data changes only on release publish) |
| Design tokens in JS | `frontend/lib/tokens.ts` | reads CSS custom properties at runtime; `scoreBandVar`, `confidenceVar`. NEVER hardcode hex — globals.css is the single source of truth |
| Map | `frontend/components/map/SuitabilityMap.tsx` | MapLibre + OpenFreeMap positron (key-free); MVT source `suitability`, props `cell_id`, `total_score`, `confidence_score`; profile switch swaps tile URL via `setTiles()` without rebuilding the map |
| Profile switcher | `frontend/components/map/ProfileSwitcher.tsx` | driven by `/api/v1/business-profiles` (DB-driven — new profiles appear automatically) |
| Legend | `frontend/components/map/MapLegend.tsx` | same tokens as the tile ramp |
| Score drawer | `frontend/components/scoring/ScoreDrawer.tsx` | §18.3 FIXED evidence order — never reorder; includes the daypart chart; null component score renders "Not computed", never 0 (invariant 4) |
| Daypart chart | `frontend/components/charts/DaypartChart.tsx` | Weekday/Saturday/Sunday tabs over modelled hourly estimates; sensor confidence remains separate |
| Comparison tray | `frontend/components/locations/ComparisonTray.tsx` | Desktop-only comparison bench after 2+ map selections; selection-order columns pair percentiles with raw evidence |
| Location search | `frontend/components/locations/LocationSearch.tsx` | Explicit-submit Nominatim search bounded to API coverage; selecting a result recentres the map and opens details |
| Score bar / badge | `frontend/components/scoring/{ScoreBar,ConfidenceBadge}.tsx` | score palette and confidence palette are separate systems — never substitute |
| Shell | `frontend/app/{layout,providers,page}.tsx` | Inter via next/font; QueryClientProvider; map is `dynamic(..., {ssr:false})` |

Verified: `npm run typecheck` and `npm run build` green; live smoke via
the dev proxy (`page:200`, profiles JSON, CBD z14 tile 15,744 bytes,
Bourke St Mall café score 77.2/high).

## Non-negotiable invariants (from architecture.md)

1. **Null ≠ 0.** A component with `score: null` was not computed. Show
   an explicit "Not computed" state. Never render an empty bar as zero.
2. **Confidence is separate from suitability.** `--confidence-*` colors
   for confidence, `--score-*` for scores. A low-confidence high score
   must never look like a low score.
3. **Every number needs its evidence.** Never show a ranked list or a
   score without the raw values behind it being reachable.
4. **All colors via CSS variables** in `app/globals.css`. MapLibre paint
   needs literals — get them with `lib/tokens.ts` `cssVar()`, at runtime.
5. **All server state through React Query hooks** in `lib/api/hooks.ts`;
   all responses zod-validated in `lib/api/client.ts`. No ad-hoc fetch.

## Remaining work, in order

### Completed: daypart foot-traffic chart
`ScoreResponse.daypart_foot_traffic` now exposes the matching
`analytics.cell_pedestrian_daypart` baseline through the existing
repository→service→schema path. The drawer renders a dependency-free
bar chart in the §18.3 slot with day-type tabs, confidence dots, and the
raw sensor-count/nearest-sensor evidence. A null series explicitly says
that the estimate is unavailable; it is never shown as zero.

### Completed: comparison tray (§18.1)
`app/page.tsx` keeps ordinary map selection separate from the staged
comparison list: clicking the map only selects/switches the evidence
drawer, and the drawer's explicit Compare action stages that location.
Adding the second location opens a mutually exclusive, bottom-docked
desktop comparison workspace; it never overlaps the detail drawer.
Selection-order component columns reuse the drawer's React Query score
keys, every percentile is paired with its raw metric, and locations are
never auto-ranked. Numbered map markers match the staged columns, which
can reopen details or be removed individually. Mobile comparison
remains a separate-screen task per the architecture.

### Completed: search / geocoding
The top-docked search uses Nominatim's JSONv2 endpoint, restricted to
the bounds from `useCoverage()`. It is deliberately explicit-submit,
not autocomplete (the public service forbids client-side autocomplete),
rate-limited to ≤1 request/second, cached through React Query for 24
hours, runtime-validated with zod, and visibly attributed to
OpenStreetMap. Selecting a result recentres the map and opens that
location's detail drawer without changing comparison state. Set
`NEXT_PUBLIC_GEOCODER_URL` to switch to another compatible provider or
self-hosted Nominatim endpoint.

### 1. Mobile bottom sheet
`ScoreDrawer` is already a self-contained panel; on `< sm` render it in
a bottom-sheet container (e.g. 60dvh, drag handle) instead of the right
overlay in `app/page.tsx`. Keep the §18.3 order identical.

### 2. Confidence map overlay (§18.2)
A toggle that recolors the fill layer by `confidence_score` using the
`--confidence-*` tokens (the tile already carries the property — no
backend change). Implement as a second paint expression swapped with
`map.setPaintProperty`.

### 3. Raw point layers on zoom (§18.2)
Sensors / individual businesses / developments as point layers visible
only at high zoom. Needs new tile or GeoJSON endpoints — follow the MVT
pattern in `backend/app/repositories/scores.py::get_suitability_tile`.

### Deliberately out of scope for now
Projects/saved searches + auth (architecture Phase 4), shadcn/ui CLI
adoption (current primitives are small and hand-rolled; adopt shadcn
when a real form/dialog need appears).

## Working rules for whoever continues

- After ANY backend schema change: `make contracts`, commit the
  regenerated `contracts/generated/openapi.json` +
  `frontend/lib/api/schema.ts` together with the change.
- Verify with `npm run typecheck && npm run build` in `frontend/`, and
  smoke against the real stack: `make api` (or
  `uv run uvicorn app.main:app --port 8000` in backend/) + `npm run dev`,
  then click the CBD. Golden checks: Bourke St Mall café ≈ 77 "high"
  band; a click in Richmond must show the friendly out-of-area state.
- Update `context/progress-tracker.md` after each meaningful change.
