#!/usr/bin/env bash
# Regenerate the TypeScript API client from the FastAPI OpenAPI schema.
# Contract flow (vercel-template.md): Pydantic schemas -> OpenAPI ->
# openapi-typescript -> frontend/lib/api/schema.ts (+ contracts/generated).
#
# Requires the backend venv to exist (cd backend && uv sync).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Exporting OpenAPI schema from backend..."
(cd backend && uv run python -c "
import json
from app.main import app
print(json.dumps(app.openapi(), indent=2))
") > contracts/generated/openapi.json

echo "Generating TypeScript types..."
npx --yes openapi-typescript contracts/generated/openapi.json \
  --output frontend/lib/api/schema.ts

echo "Done: contracts/generated/openapi.json + frontend/lib/api/schema.ts"
echo "Commit both files together with the backend schema change."
