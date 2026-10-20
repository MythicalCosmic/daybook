.DEFAULT_GOAL := help
MANAGE := uv run backend/manage.py

.PHONY: help up down install migrate makemigrations superuser shell demo run worker beat bot app app-build api-types stack stack-down test lint fmt check

help: ## Show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start Postgres and Redis
	docker compose up -d db redis

down: ## Stop all containers
	docker compose --profile app down

install: ## Install backend and mini app dependencies
	uv sync
	cd miniapp && npm install

migrate: ## Apply migrations
	$(MANAGE) migrate

makemigrations: ## Create migrations
	$(MANAGE) makemigrations

superuser: ## Create an admin user
	$(MANAGE) createsuperuser

shell: ## Django shell
	$(MANAGE) shell

demo: ## Rebuild the Demo Shop company (development only)
	$(MANAGE) seed_demo --reset

run: ## Django dev server on :28000
	$(MANAGE) runserver 127.0.0.1:28000

worker: ## Celery worker
	cd backend && uv run celery -A config worker -l info

beat: ## Celery beat
	cd backend && uv run celery -A config beat -l info

bot: ## Employee bot (polling)
	cd employee_bot && uv run python main.py

app: ## Mini app dev server on :28173/app/ (proxies /api to :28000)
	cd miniapp && npm run dev

app-build: ## Build the mini app into miniapp/dist
	cd miniapp && npm run build

api-types: ## Regenerate the mini app's API types from the backend schema
	$(MANAGE) spectacular --file miniapp/src/api/openapi.yaml
	cd miniapp && npm run api:types

stack: ## Whole stack in Docker (backend, worker, beat, bot)
	docker compose --profile app up -d --build

stack-down: ## Stop the Docker stack
	docker compose --profile app down

test: ## Run backend, bot and mini app tests (needs `make up`)
	uv run pytest
	cd miniapp && npm test

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-fix lint and format
	uv run ruff check --fix .
	uv run ruff format .

check: lint test ## Lint, type checks, tests
	$(MANAGE) check
	cd miniapp && npm run typecheck
