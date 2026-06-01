.PHONY: help sync dev test lint format mypy up down logs restart build clean token gpu health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# === Development ===

sync: ## Install/sync dependencies via uv
	uv sync

dev: ## Start server locally (uvicorn with reload)
	uv run uvicorn rest.main:app --host 0.0.0.0 --port 8000 --reload

test: ## Run tests with coverage (80% minimum)
	uv run pytest --cov=rest --cov-report=term-missing --cov-fail-under=80

# === Code quality ===

lint: format mypy ## Run all linters

format: ## Format and check with ruff
	uv run ruff format .
	uv run ruff check --fix .

mypy: ## Type check with mypy
	uv run mypy rest/

# === Docker ===

up: ## Start the service (rebuilds image to pick up code/dependency changes)
	docker compose up -d --build

down: ## Stop the service
	docker compose down

logs: ## Show logs (follow)
	docker compose logs -f stt

restart: ## Restart the service
	docker compose restart stt

build: ## Rebuild and start
	docker compose up -d --build

clean: ## Stop and remove volumes
	docker compose down -v

# === Utilities ===

token: ## Generate a secure token
	@python -c "import secrets; print(secrets.token_urlsafe(32))"

gpu: ## Check GPU status in container
	docker compose exec stt nvidia-smi

health: ## Check server health
	@curl -s http://localhost:8000/health | python -m json.tool
