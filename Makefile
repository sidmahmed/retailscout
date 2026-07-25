# RetailScout developer entry points.
# Every target is safe to run repeatedly. See README.md for prerequisites.

.PHONY: db-up db-down db-migrate db-revision api-dev api-test api-lint \
        jobs-test jobs-lint ingest fe-dev fe-build contracts check

# --- Database -------------------------------------------------------------

db-up:            ## Start local PostGIS via Docker Compose
	docker compose -f infrastructure/docker-compose.yml up -d --wait

db-down:          ## Stop local PostGIS (data volume is preserved)
	docker compose -f infrastructure/docker-compose.yml down

db-migrate:       ## Apply Alembic migrations (uses DATABASE_DIRECT_URL)
	cd db && uv run --with alembic,sqlalchemy,"psycopg[binary]" alembic upgrade head

db-revision:      ## Create a new empty migration: make db-revision M="describe change"
	cd db && uv run --with alembic,sqlalchemy,"psycopg[binary]" alembic revision -m "$(M)"

# --- Backend (runtime API) ------------------------------------------------

api-dev:          ## Run FastAPI locally on :8000 with reload
	cd backend && uv run uvicorn app.main:app --reload --port 8000

api-test:
	cd backend && uv run pytest

api-lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

# --- Jobs (data worker) ---------------------------------------------------

jobs-test:
	cd jobs && uv run pytest

jobs-lint:
	cd jobs && uv run ruff check . && uv run ruff format --check .

ingest:           ## Ingest one source to data/raw/: make ingest SOURCE=<id from sources.yaml>
	cd jobs && uv run python -m retailscout_jobs.cli ingest $(SOURCE)

# --- Frontend -------------------------------------------------------------

fe-dev:
	cd frontend && npm run dev

fe-build:
	cd frontend && npm run build

# --- Contracts ------------------------------------------------------------

contracts:        ## Regenerate the TypeScript client from the running API's OpenAPI schema
	./scripts/generate-contracts.sh

# --- Everything CI runs ---------------------------------------------------

check: api-lint api-test jobs-lint jobs-test fe-build
