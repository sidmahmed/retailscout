# frontend/lib/api

API access layer. Contents once wired (Phase 3):

- `schema.ts` — **generated** from the FastAPI OpenAPI spec via
  `make contracts` (openapi-typescript). Never hand-edit; regenerate
  whenever `backend/app/schemas/` changes.
- `client.ts` — thin typed fetch wrapper over `/api/v1` (same-origin;
  the Next.js rewrite proxies to FastAPI in local dev).
- `hooks.ts` — React Query hooks (`useScore`, `useGeocode`, …). All server
  state goes through React Query; no ad-hoc `useEffect` fetching
  (code-standards.md).

Address search uses the configurable `NEXT_PUBLIC_GEOCODER_URL`
(Nominatim JSONv2-compatible). The public default is for moderate,
explicit user submissions only: never turn it into autocomplete, keep
the one-request-per-second guard, caching, and OpenStreetMap attribution.

Validation rule: anything arriving from outside the type system (URL
params, map-click coordinates, form input) is parsed with `zod` before
use — the generated types cover responses, not user input.
