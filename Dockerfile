FROM node:22-alpine AS miniapp

WORKDIR /miniapp
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY miniapp ./
RUN npm run build


# The owner dashboard (Vue), served at /dashboard/.
FROM node:22-alpine AS dashboard

WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard ./
RUN npm run build


FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# WeasyPrint renders payslips, contracts and invoices through Pango and HarfBuzz. The PDFs embed
# their own Noto Sans; DejaVu (Latin and Cyrillic) is only the fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY backend ./backend
COPY employee_bot ./employee_bot
COPY owner_bot ./owner_bot
COPY --from=miniapp /miniapp/dist ./miniapp/dist
COPY --from=dashboard /dashboard/dist ./dashboard/dist
# Pre-compressed copies next to each file; WhiteNoise serves them to browsers that accept them.
RUN python -m whitenoise.compress miniapp/dist \
    && python -m whitenoise.compress dashboard/dist

WORKDIR /app/backend

# Throwaway values: collectstatic only needs settings to import.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=collectstatic \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgres://u:p@localhost/db \
    REDIS_URL=redis://localhost:6379/0 \
    CELERY_BROKER_URL=redis://localhost:6379/1 \
    python manage.py collectstatic --noinput

# media: public uploads (proof photos, logos). private_media: receipts, documents, exports and
# PDFs, only ever served through signed links. Both are volumes in docker-compose.yml.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p media private_media \
    && chown app media private_media
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3"]
