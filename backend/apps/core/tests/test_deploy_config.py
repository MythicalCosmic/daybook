"""The production serving setup (docs/DEPLOY.md "Performance"): gunicorn's config, how the stack
starts it, and whether Postgres has room for every connection the stack keeps."""

import re
import runpy
from pathlib import Path

import pytest
import yaml
from django.conf import settings

ROOT = Path(settings.BASE_DIR).parent
GUNICORN = Path(settings.BASE_DIR) / "config" / "gunicorn.conf.py"


def gunicorn_config(monkeypatch, **env) -> dict:
    for name in (
        "GUNICORN_WORKERS",
        "GUNICORN_THREADS",
        "GUNICORN_BIND",
        "GUNICORN_TIMEOUT",
        "GUNICORN_KEEPALIVE",
        "GUNICORN_MAX_REQUESTS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return runpy.run_path(str(GUNICORN))


class ComposeLoader(yaml.SafeLoader):
    """Reads Compose's `!reset` (drop what the base file set) as the plain value."""


ComposeLoader.add_constructor(
    "!reset", lambda loader, node: loader.construct_sequence(node) if node.value else []
)


def compose(name: str) -> dict:
    return yaml.load((ROOT / name).read_text(), Loader=ComposeLoader)


def test_gunicorn_runs_threaded_workers_sized_for_the_server(monkeypatch):
    config = gunicorn_config(monkeypatch)

    assert config["worker_class"] == "gthread"
    assert 1 <= config["workers"] <= 12
    assert config["threads"] == 4
    assert config["bind"] == "0.0.0.0:8000"
    assert config["timeout"] >= 30
    # Workers are replaced now and then, never all at once.
    assert config["max_requests"] > 0
    assert 0 < config["max_requests_jitter"] < config["max_requests"]
    assert config["control_socket_disable"] is True
    assert config["accesslog"] == "-"


def test_every_gunicorn_number_comes_from_the_environment(monkeypatch):
    config = gunicorn_config(
        monkeypatch,
        GUNICORN_WORKERS="6",
        GUNICORN_THREADS="8",
        GUNICORN_BIND="127.0.0.1:9000",
        GUNICORN_TIMEOUT="90",
        GUNICORN_KEEPALIVE="120",
        GUNICORN_MAX_REQUESTS="100",
    )

    assert (config["workers"], config["threads"]) == (6, 8)
    assert config["bind"] == "127.0.0.1:9000"
    assert (config["timeout"], config["keepalive"], config["max_requests"]) == (90, 120, 100)


def test_gunicorn_outlasts_caddys_idle_connections(monkeypatch):
    """Caddy must drop an idle upstream connection before gunicorn does, or a request sent on
    a connection gunicorn just closed fails with a 502."""
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    caddy_keepalive = int(re.search(r"keepalive (\d+)s", caddy).group(1))

    assert gunicorn_config(monkeypatch)["keepalive"] > caddy_keepalive


def test_the_backend_and_the_image_start_gunicorn_with_the_config():
    backend = compose("docker-compose.yml")["services"]["backend"]["command"]
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "exec gunicorn -c config/gunicorn.conf.py config.wsgi" in backend
    assert "--workers" not in backend
    assert 'CMD ["gunicorn", "-c", "config/gunicorn.conf.py", "config.wsgi"]' in dockerfile


def _setting(command: list[str], name: str) -> str:
    for item in command:
        if str(item).startswith(f"{name}="):
            return str(item).split("=", 1)[1]
    raise AssertionError(f"{name} isn't set")


def _default(value: str) -> int:
    """`${VAR:-200}` → 200."""
    found = re.fullmatch(r"\$\{\w+:-(\d+)\}", value)
    return int(found.group(1)) if found else int(value)


def test_postgres_has_room_for_every_connection_the_stack_keeps(monkeypatch):
    prod = compose("docker-compose.prod.yml")["services"]
    base = compose("docker-compose.yml")["services"]
    max_connections = _default(_setting(prod["db"]["command"], "max_connections"))
    web = gunicorn_config(monkeypatch)
    worker = re.search(r"CELERY_CONCURRENCY:-(\d+)", base["worker"]["command"])
    ai_worker = re.search(r"-c (\d+)", base["ai-worker"]["command"])

    kept = (
        web["workers"] * web["threads"]  # one per gunicorn thread
        + int(worker.group(1))
        + int(ai_worker.group(1))
        + 2 * settings.BOT_DB_THREADS  # both bots
        + 10  # the stream, beat, the backup and a manage.py shell
    )

    # A deploy briefly runs the old and the new backend side by side.
    assert kept + web["workers"] * web["threads"] <= max_connections


def test_the_apps_logs_rotate():
    """gunicorn logs every request; Docker would keep them all."""
    services = compose("docker-compose.yml")["services"]
    app = [name for name, service in services.items() if service.get("image") == "trello911:latest"]

    assert {"backend", "worker", "employee_bot", "owner_bot", "stream", "beat"} <= set(app)
    for name in app:
        assert services[name]["logging"]["options"]["max-size"], name


@pytest.mark.parametrize("service", ["worker", "ai-worker"])
def test_celery_workers_take_one_job_at_a_time(service):
    command = compose("docker-compose.yml")["services"][service]["command"]

    assert re.search(r"--prefetch-multiplier (\$+\{CELERY_PREFETCH:-1\}|1)( |$)", command)
