SHELL := /bin/bash
PYTHON := /opt/homebrew/bin/python3.12
VENV := .venv

# Docker Desktop Keychain workaround: processes started inside the DSH sandbox
# cannot read the macOS Keychain, so image pulls fail with "Keychain Error (-67674)".
# We point Docker at a credential helper that stores nothing (public registries only).
export DOCKER_CONFIG := $(CURDIR)/.docker
export PATH := $(CURDIR)/bin:$(PATH)

.PHONY: help init up down restart logs psql minio-console bucket scrape scrape-dry load venv install test lint fmt precommit clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

init: ## Create .env and the sandbox-safe Docker config
	@test -f .env || (cp .env.example .env && echo "created .env")
	@mkdir -p .docker
	@printf '{"auths":{},"credsStore":"null"}' > .docker/config.json
	@ln -sfn "$$HOME/.docker/cli-plugins" .docker/cli-plugins

up: init ## Start Postgres + MinIO
	docker compose up -d
	@docker compose ps

down: ## Stop containers (data is kept)
	docker compose down

restart: down up ## Restart containers

logs: ## Tail container logs
	docker compose logs -f --tail=100

psql: ## Open a psql shell
	docker compose exec postgres psql -U $${POSTGRES_USER:-djm} -d $${POSTGRES_DB:-jobmarket}

bucket: ## Create the raw S3 bucket (run after make install)
	$(VENV)/bin/python -m ingestion.ensure_bucket

scrape: ## Crawl TopDev into MinIO raw zone (PAGES=20, DATE=today)
	$(VENV)/bin/python -m ingestion.scrape --pages $${PAGES:-20} $${DATE:+--date $$DATE}

scrape-dry: ## Show what a crawl would do, without network calls
	$(VENV)/bin/python -m ingestion.scrape --pages $${PAGES:-20} --dry-run

load: ## Load raw jobs into Postgres (DATE=YYYY-MM-DD or ALL=1)
	$(VENV)/bin/python -m ingestion.load $${DATE:+--date $$DATE} $${ALL:+--all}

venv: ## Create the Python 3.12 virtualenv
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)

install: venv ## Install Python dependencies
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt -r requirements-dev.txt

test: ## Run tests
	$(VENV)/bin/pytest -q

lint: ## Lint with ruff
	$(VENV)/bin/ruff check .

fmt: ## Format with ruff
	$(VENV)/bin/ruff format .

precommit: ## Install git hooks
	PRE_COMMIT_HOME=$(CURDIR)/.cache/pre-commit $(VENV)/bin/pre-commit install
	PRE_COMMIT_HOME=$(CURDIR)/.cache/pre-commit $(VENV)/bin/pre-commit install-hooks

clean: ## Remove containers AND volumes (destructive)
	docker compose down -v
