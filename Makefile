.PHONY: help sync dev test lint format mypy up down logs restart build clean db shell token gpu health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# === Development ===

sync: ## Install/sync dependencies via uv
	uv sync

dev: ## Start server locally (requires DB running)
	uv run python server.py

test: ## Run tests with coverage (80% minimum)
	uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=80

# === Code quality ===

lint: format mypy ## Run all linters

format: ## Format and check with ruff
	uv run ruff format .
	uv run ruff check --fix .

mypy: ## Type check with mypy
	uv run mypy .

# === Docker ===

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

logs: ## Show logs (follow)
	docker compose logs -f whisper-server

restart: ## Restart whisper-server
	docker compose restart whisper-server

build: ## Rebuild and start
	docker compose up -d --build

clean: ## Stop and remove volumes
	docker compose down -v

# === Utilities ===

db: ## Start only PostgreSQL
	docker compose up -d db

shell: ## Open shell in whisper-server container
	docker compose exec whisper-server bash

token: ## Generate a secure token
	@python -c "import secrets; print(secrets.token_urlsafe(32))"

gpu: ## Check GPU status in container
	docker compose exec whisper-server nvidia-smi

health: ## Check server health
	@curl -s http://localhost:8000/health | python -m json.tool
