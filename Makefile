.DEFAULT_GOAL := help
MANAGE := uv run backend/manage.py

.PHONY: help up down install migrate makemigrations superuser shell run worker beat bot stack stack-down test lint fmt check

help: ## Show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start Postgres and Redis
	docker compose up -d db redis

down: ## Stop all containers
	docker compose --profile app down

install: ## Install dependencies into .venv
	uv sync

migrate: ## Apply migrations
	$(MANAGE) migrate

makemigrations: ## Create migrations
	$(MANAGE) makemigrations

superuser: ## Create an admin user
	$(MANAGE) createsuperuser

shell: ## Django shell
	$(MANAGE) shell

run: ## Django dev server on :28000
	$(MANAGE) runserver 127.0.0.1:28000

worker: ## Celery worker
	cd backend && uv run celery -A config worker -l info

beat: ## Celery beat
	cd backend && uv run celery -A config beat -l info

bot: ## Employee bot (polling)
	cd employee_bot && uv run python main.py

stack: ## Whole stack in Docker (backend, worker, beat, bot)
	docker compose --profile app up -d --build

stack-down: ## Stop the Docker stack
	docker compose --profile app down

test: ## Run tests (needs `make up`)
	uv run pytest

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-fix lint and format
	uv run ruff check --fix .
	uv run ruff format .

check: lint test ## Lint, Django checks, tests
	$(MANAGE) check
