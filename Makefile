# ===========================================================================
# JobHub developer commands. Run `make help` for the list.
#
# Most targets shell into the running compose containers, so `make up` first.
# ===========================================================================

# Use bash and fail fast.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE := docker compose

# `docker compose exec` on the api container. Falls back to `run` if not up.
API_EXEC := $(COMPOSE) exec api

## ---------------------------------------------------------------------------
## Stack lifecycle
## ---------------------------------------------------------------------------

.PHONY: up
up: ## Start db + api + worker
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop containers (keeps the database volume)
	$(COMPOSE) down

.PHONY: nuke
nuke: ## Stop containers AND delete the database volume
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail all logs
	$(COMPOSE) logs -f

.PHONY: shell
shell: ## Open a shell in the api container
	$(API_EXEC) bash

## ---------------------------------------------------------------------------
## Database
## ---------------------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply all migrations
	$(API_EXEC) alembic upgrade head

.PHONY: migration
migration: ## Create a migration: make migration m="add x to jobs"
	$(API_EXEC) alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: ## Roll back one migration
	$(API_EXEC) alembic downgrade -1

.PHONY: seed
seed: ## Load taxonomy + source registry seed data
	$(API_EXEC) python -m app.seeds.run

.PHONY: psql
psql: ## Open a psql prompt
	$(COMPOSE) exec db psql -U jobhub -d jobhub

.PHONY: create-admin
create-admin: ## Provision an admin account (prompts for a password)
	$(API_EXEC) python -m app.seeds.create_admin --email $(email)

## ---------------------------------------------------------------------------
## Ingestion
## ---------------------------------------------------------------------------

.PHONY: ingest
ingest: ## Run one source now: make ingest SOURCE=remotive
	$(API_EXEC) python -m app.ingestion.run --source $(SOURCE)

.PHONY: ingest-all
ingest-all: ## Run every enabled source once
	$(API_EXEC) python -m app.ingestion.run --all

.PHONY: recategorize
recategorize: ## Re-run the keyword classifier over all jobs
	$(API_EXEC) python -m app.categorization.run

## ---------------------------------------------------------------------------
## Quality
## ---------------------------------------------------------------------------

.PHONY: test
test: ## Run the test suite
	$(API_EXEC) pytest -q

.PHONY: lint
lint: ## Ruff lint + format check
	$(API_EXEC) ruff check .
	$(API_EXEC) ruff format --check .

.PHONY: fmt
fmt: ## Auto-format
	$(API_EXEC) ruff check --fix .
	$(API_EXEC) ruff format .

## ---------------------------------------------------------------------------
## Frontend
## ---------------------------------------------------------------------------

.PHONY: frontend-build
frontend-build: ## Compile Tailwind + inject API_BASE_URL
	cd frontend && npm install && npm run build

.PHONY: frontend-serve
frontend-serve: ## Serve the static frontend on :5173
	cd frontend && npm run serve

## ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
