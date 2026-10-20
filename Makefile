.DEFAULT_GOAL := help
# PKG=<package> gives a command that package's database, Redis database and ports (§2.4).
include deploy/dev-packages.mk

MANAGE := uv run backend/manage.py
# Collects the translatable strings of the backend and the bots into backend/locale.
MAKEMESSAGES := PYTHONPATH=backend DJANGO_SETTINGS_MODULE=config.settings.dev uv run django-admin \
	makemessages -l uz -l ru -i miniapp -i dashboard -i node_modules -i tests -i staticfiles \
	-i media -i private_media --add-location=file --no-obsolete
HAS_DASHBOARD := $(wildcard dashboard/package.json)

.PHONY: help up down install migrate makemigrations superuser shell messages demo run worker \
	ai-worker beat stream bot owner-bot app app-build dashboard dashboard-test dashboard-build \
	api-types owner-schema perms-ts guard pkg-db pkg-env test-app stack stack-down test lint fmt \
	check prod-up prod-logs prod-manage prod-backup

help: ## Show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo "  Most targets take PKG=<package> (deploy/dev-packages.mk), e.g. make run PKG=e"

up: ## Start Postgres and Redis
	docker compose up -d db redis

down: ## Stop all containers
	docker compose --profile app down

# Exactly what the lockfiles say: they change only at integration (docs/PLAN-OWNER.md §2.3).
install: ## Install backend, mini app and dashboard dependencies
	uv sync --frozen
	cd miniapp && npm ci
ifneq ($(HAS_DASHBOARD),)
	cd dashboard && npm ci
endif

migrate: ## Apply migrations [PKG]
	$(PKG_ENV) $(MANAGE) migrate

makemigrations: ## Create migrations
	$(PKG_ENV) $(MANAGE) makemigrations

superuser: ## Create an admin user [PKG]
	$(PKG_ENV) $(MANAGE) createsuperuser

shell: ## Django shell [PKG]
	$(PKG_ENV) $(MANAGE) shell

messages: ## Collect new bot and API texts into the uz/ru .po files and compile them
	$(MAKEMESSAGES)
	cd backend && uv run python manage.py compilemessages

demo: ## Rebuild Demo Shop and Demo Café [PKG, DEMO_APPS=sales,finance, OWNER_TG=<telegram id>]
	$(PKG_ENV) $(MANAGE) seed_demo --reset $(if $(DEMO_APPS),--only $(DEMO_APPS)) \
		$(if $(OWNER_TG),--owner-tg $(OWNER_TG))

run: ## Django dev server (:28000) [PKG]
	$(PKG_ENV) $(MANAGE) runserver 127.0.0.1:$(BACKEND_PORT)

worker: ## Celery worker for the celery and default queues [PKG]
	cd backend && $(PKG_ENV) uv run celery -A config worker -Q celery,default -l info

ai-worker: ## Celery worker for the ai queue [PKG]
	cd backend && $(PKG_ENV) uv run celery -A config worker -Q ai -c 4 -l info

beat: ## Celery beat [PKG]
	cd backend && $(PKG_ENV) uv run celery -A config beat -l info \
		--schedule celerybeat-schedule$(if $(PKG),-$(PKG))

stream: ## AI answer streams, uvicorn with reload (:28001) [PKG]
	cd backend && $(PKG_ENV) DJANGO_SETTINGS_MODULE=config.settings.dev DB_CONN_MAX_AGE=0 \
		uv run uvicorn config.asgi:application --host 127.0.0.1 --port $(STREAM_PORT) --reload

bot: ## Employee bot (polling; one copy per token) [PKG]
	cd employee_bot && $(PKG_ENV) uv run python main.py

owner-bot: ## Owner bot (polling; one copy per token) [PKG]
	cd owner_bot && $(PKG_ENV) uv run python -m ownerbot

app: ## Mini app dev server on :28173/app/ (proxies /api to the backend) [PKG]
	cd miniapp && DEV_PORT=$(MINIAPP_PORT) $(VITE_ENV) npm run dev

app-build: ## Build the mini app into miniapp/dist
	cd miniapp && npm run build

dashboard: ## Dashboard dev server on :28174/dashboard/ (proxies /api to the backend) [PKG]
	cd dashboard && DEV_PORT=$(DASHBOARD_PORT) DASHBOARD_PORT=$(DASHBOARD_PORT) $(VITE_ENV) \
		npm run dev

dashboard-test: ## Dashboard typecheck and tests [MODULE=finance for one module]
	cd dashboard && npm run typecheck
	cd dashboard && npx vitest run $(if $(MODULE),src/modules/$(MODULE))

dashboard-build: ## Build the dashboard into dashboard/dist
	cd dashboard && npm run build

api-types: ## Regenerate the mini app's API types from the employee schema
	SCHEMA_AUDIENCE=employee $(MANAGE) spectacular --file miniapp/src/api/openapi.yaml
	cd miniapp && npm run api:types

owner-schema: ## Write the owner schema to dashboard/openapi.owner.yaml (integration)
	SCHEMA_AUDIENCE=owner $(MANAGE) spectacular --file dashboard/openapi.owner.yaml

perms-ts: ## Regenerate dashboard/src/core/perms.generated.ts from the Perm registry
	$(MANAGE) perms_ts

guard: ## Django checks and no missing migrations [PKG]
	$(PKG_ENV) $(MANAGE) check
	$(PKG_ENV) $(MANAGE) makemigrations --check --dry-run

pkg-db: ## Create the package's database and migrate it (PKG required)
	$(if $(PKG),,$(error Usage: make pkg-db PKG=<package>))
	docker compose exec -T db psql -U trello -d postgres -tAc \
		"SELECT 1 FROM pg_database WHERE datname = '$(PKG_DB)'" | grep -q 1 \
		|| docker compose exec -T db createdb -U trello $(PKG_DB)
	$(PKG_ENV) $(MANAGE) migrate

pkg-env: ## Print the package's settings as shell exports (PKG required)
	$(if $(PKG),,$(error Usage: make pkg-env PKG=<package>))
	@for pair in $(PKG_ENV) BACKEND_PORT=$(BACKEND_PORT) DASHBOARD_PORT=$(DASHBOARD_PORT) \
		MINIAPP_PORT=$(MINIAPP_PORT) STREAM_PORT=$(STREAM_PORT); do echo "export $$pair"; done

test-app: ## Tests of one app with the package's test database [APP=sales PKG=e]
	$(if $(APP),,$(error Usage: make test-app APP=<app> PKG=<package>))
	$(PKG_ENV) uv run pytest backend/apps/$(APP)

PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app

prod-up: ## Production: build and start everything behind HTTPS (needs DOMAIN in .env)
	$(PROD) up -d --build

prod-logs: ## Production: follow the logs
	$(PROD) logs -f --tail=100

prod-manage: ## Production: run a manage.py command, e.g. make prod-manage cmd=createsuperuser
	$(PROD) exec backend python manage.py $(cmd)

prod-backup: ## Production: dump the database to ./backups now
	$(PROD) exec backup sh -c 'pg_dump --no-owner | gzip > /backups/trello-$$(date +%F-%H%M).sql.gz'

stack: ## Whole stack in Docker (backend, workers, beat, stream, both bots)
	docker compose --profile app up -d --build

stack-down: ## Stop the Docker stack
	docker compose --profile app down

test: ## Backend, bot, mini app and dashboard tests (needs `make up`) [PKG]
	$(PKG_ENV) uv run pytest
	cd miniapp && npm test
ifneq ($(HAS_DASHBOARD),)
	cd dashboard && npm test
endif

# docs/ holds the plans: ruff would reformat the Python sketches inside their Markdown.
RUFF_SKIP := --extend-exclude docs

lint: ## Lint and check formatting
	uv run ruff check $(RUFF_SKIP) .
	uv run ruff format --check $(RUFF_SKIP) .

fmt: ## Auto-fix lint and format
	uv run ruff check --fix $(RUFF_SKIP) .
	uv run ruff format $(RUFF_SKIP) .

check: lint test ## Lint, Django checks, migrations, type checks, tests [PKG]
	$(PKG_ENV) $(MANAGE) check
	$(PKG_ENV) $(MANAGE) makemigrations --check --dry-run
	cd miniapp && npm run typecheck
ifneq ($(HAS_DASHBOARD),)
	cd dashboard && npm run typecheck
	$(MANAGE) perms_ts --check
endif
