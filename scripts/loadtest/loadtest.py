#!/usr/bin/env python3
"""Load test: N people open the mini app at once, M managers work in the dashboard.

Each mini app person signs in with Telegram launch data signed by the employee bot (exactly what
Telegram hands the app), then does what a shift does at the start of the day: opens the app
(me, the day's numbers, their board), opens a task (its card and comments), finishes it, writes
a comment, and the app refreshes the board. Each dashboard manager signs in the way the
dashboard does inside Telegram and goes through the task list, the numbers, the reviews queue
and the overview a few times.

The people come from `manage.py loadtest_people` (a company of their own; see docs/DEPLOY.md
"Load test"). Run that first, and again before every run: it gives everyone fresh tasks.

    EMPLOYEE_BOT_TOKEN=... python scripts/loadtest/loadtest.py --base-url https://example.uz \\
        --users 300 --dashboard-users 20

The bot token is read from the environment variable named by --token-env and never printed.
Only aiohttp is needed (it comes with aiogram, so it's in the app's environment and image).
Exit status 0 means no request failed; any 429, 5xx, timeout or connection error is a failure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlencode

import aiohttp

API = "/api/v1"
FIRST_ID = 990_000_000_001  # manage.py loadtest_people's default
COMMENT = "Bajarildi, tekshirib ko‘ring."


# Telegram launch data ----------------------------------------------------------------------


def init_data(token: str, telegram_id: int, first_name: str, language: str = "uz") -> str:
    """`Telegram.WebApp.initData` for `telegram_id`, signed as Telegram signs it for the bot."""
    user = {"id": telegram_id, "first_name": first_name, "language_code": language}
    fields = {
        "query_id": f"LOADTEST{telegram_id}",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


# Measuring ---------------------------------------------------------------------------------


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    statuses: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    failures: Counter = field(default_factory=Counter)
    examples: dict[str, str] = field(default_factory=dict)
    sessions: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    stopped: Counter = field(default_factory=Counter)
    started: float = 0.0
    finished: float = 0.0

    def record(self, name: str, status: int | str, seconds: float, body: str = "") -> None:
        self.latencies[name].append(seconds)
        self.statuses[name][status] += 1
        failed = not isinstance(status, int) or status == 429 or status >= 500
        if failed:
            self.failures[f"{name} {status}"] += 1
            self.examples.setdefault(f"{name} {status}", body[:300])
        elif status >= 400:
            # A 4xx other than 429 is the test's own mistake (or a rule): shown, not failed.
            self.examples.setdefault(f"{name} {status}", body[:300])


class Failed(Exception):
    """A step can't go on (sign-in refused, no task to open)."""


class Client:
    """One person's browser: its own connections (a phone opens at most six to one host)."""

    def __init__(
        self, base_url: str, stats: Stats, timeout: float, host: str | None, address: str | None
    ):
        self.base_url = base_url.rstrip("/")
        self.stats = stats
        self.headers = {"Host": host} if host else {}
        if address:
            # Local runs without a proxy only: the backend takes the last X-Forwarded-For hop
            # as the client (NUM_PROXIES=1), so each person looks like their own address.
            self.headers["X-Forwarded-For"] = address
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=6, ssl=None),
            timeout=aiohttp.ClientTimeout(total=timeout),
        )
        self.token: str | None = None

    async def close(self) -> None:
        await self.session.close()

    async def call(self, name: str, method: str, path: str, json_body=None, expect=(200,)):
        headers = dict(self.headers)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        started = time.perf_counter()
        try:
            async with self.session.request(
                method, f"{self.base_url}{API}{path}", json=json_body, headers=headers
            ) as response:
                text = await response.text()
                status = response.status
        except TimeoutError:
            self.stats.record(name, "timeout", time.perf_counter() - started)
            raise Failed(f"{name}: timeout") from None
        except aiohttp.ClientError as exc:
            self.stats.record(name, type(exc).__name__, time.perf_counter() - started, str(exc))
            raise Failed(f"{name}: {exc}") from None
        self.stats.record(name, status, time.perf_counter() - started, text)
        if status not in expect:
            raise Failed(f"{name}: HTTP {status}")
        return json.loads(text) if text else None


async def think(mean: float) -> None:
    if mean > 0:
        await asyncio.sleep(random.uniform(0.5 * mean, 1.5 * mean))


# What people do ----------------------------------------------------------------------------


def address_of(args, telegram_id: int) -> str | None:
    if not args.distinct_ips:
        return None
    number = telegram_id - args.first_id + 1
    return f"10.{number // 65536 % 256}.{number // 256 % 256}.{number % 256}"


async def mini_app_session(args, token: str, telegram_id: int, stats: Stats) -> None:
    client = Client(args.base_url, stats, args.timeout, args.host, address_of(args, telegram_id))
    started = time.perf_counter()
    try:
        signed = init_data(token, telegram_id, f"Test {telegram_id - args.first_id + 1}")
        answer = await client.call("app sign-in", "POST", "/auth/telegram/", {"init_data": signed})
        client.token = answer["access"]
        me = await client.call("app me", "GET", "/me/")
        companies = [m["company"]["id"] for m in me["memberships"] if m["status"] == "approved"]
        if not companies:
            raise Failed("no company")
        company = me.get("bot_company") or companies[0]
        base = f"/companies/{company}"
        _summary, board = await asyncio.gather(
            client.call("app summary", "GET", f"{base}/summary/"),
            client.call("app board", "GET", f"{base}/tasks/?scope=board&page_size=200"),
        )
        stats.sessions["app open (sign-in to board)"].append(time.perf_counter() - started)
        todo = [task for task in board["results"] if task["status"] == "todo"]
        if not todo:
            raise Failed("no open task left: run manage.py loadtest_people again")
        task = random.choice(todo)
        await think(args.think)
        await asyncio.gather(
            client.call("app task", "GET", f"{base}/tasks/{task['id']}/"),
            client.call("app comments", "GET", f"{base}/tasks/{task['id']}/comments/"),
        )
        await think(args.think)
        await client.call(
            "app complete", "POST", f"{base}/tasks/{task['id']}/complete/", {"proof_text": ""}
        )
        await asyncio.gather(
            client.call("app summary", "GET", f"{base}/summary/"),
            client.call("app board", "GET", f"{base}/tasks/?scope=board&page_size=200"),
        )
        await think(args.think)
        await client.call(
            "app comment",
            "POST",
            f"{base}/tasks/{task['id']}/comments/",
            {"text": COMMENT},
            expect=(201,),
        )
        stats.sessions["app whole session"].append(time.perf_counter() - started)
    except Failed as exc:
        stats.stopped[str(exc)] += 1
    finally:
        await client.close()


async def dashboard_session(args, token: str, telegram_id: int, stats: Stats) -> None:
    client = Client(args.base_url, stats, args.timeout, args.host, address_of(args, telegram_id))
    started = time.perf_counter()
    try:
        signed = init_data(token, telegram_id, f"Manager {telegram_id}")
        answer = await client.call(
            "dash sign-in", "POST", "/owner/auth/telegram/", {"init_data": signed}
        )
        client.token = answer["access"]
        me = await client.call("dash me", "GET", "/owner/me/")
        company = _dashboard_company(me)
        base = f"/owner/companies/{company}"
        for round_number in range(args.dashboard_rounds):
            await asyncio.gather(
                client.call("dash pulse", "GET", f"{base}/pulse/"),
                client.call(
                    "dash task list",
                    "GET",
                    f"{base}/tasks/?page=1&page_size=50&routines=without",
                ),
                client.call("dash task numbers", "GET", f"{base}/tasks/summary/?routines=without"),
            )
            if round_number == 0:
                stats.sessions["dash open (sign-in to task list)"].append(
                    time.perf_counter() - started
                )
            await think(args.think)
            await client.call(
                "dash reviews", "GET", f"{base}/tasks/reviews/?page_size=100&routines=without"
            )
            await think(args.think)
            await asyncio.gather(
                client.call("dash overview branches", "GET", f"{base}/branches/today/"),
                client.call("dash overview stream", "GET", f"{base}/stream/?limit=20"),
            )
            await think(args.think)
    except Failed as exc:
        stats.stopped[str(exc)] += 1
    finally:
        await client.close()


def _dashboard_company(me: dict) -> int:
    """The load test managers work in the load test company only."""
    if not me.get("companies"):
        raise Failed("dash me: no company")
    return me["companies"][0]["id"]


# Running -----------------------------------------------------------------------------------


async def run(args, token: str) -> Stats:
    stats = Stats()
    people = [args.first_id + index for index in range(args.users)]
    managers = [args.first_id + args.people_in_db + index for index in range(args.dashboard_users)]
    jobs = []

    async def later(delay: float, job):
        await asyncio.sleep(delay)
        await job

    for telegram_id in people:
        delay = random.uniform(0, args.ramp)
        jobs.append(later(delay, mini_app_session(args, token, telegram_id, stats)))
    for telegram_id in managers:
        delay = random.uniform(0, args.ramp)
        jobs.append(later(delay, dashboard_session(args, token, telegram_id, stats)))
    random.shuffle(jobs)
    stats.started = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=args.max_seconds)
    except TimeoutError:
        stats.failures[f"run cut off after {args.max_seconds:.0f} s"] += 1
    stats.finished = time.perf_counter()
    return stats


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def report(stats: Stats, args) -> dict:
    elapsed = max(stats.finished - stats.started, 1e-9)
    every = [value for values in stats.latencies.values() for value in values]
    rows = []
    for name in sorted(stats.latencies):
        values = stats.latencies[name]
        rows.append(
            {
                "endpoint": name,
                "count": len(values),
                "p50_ms": round(percentile(values, 0.50) * 1000),
                "p95_ms": round(percentile(values, 0.95) * 1000),
                "p99_ms": round(percentile(values, 0.99) * 1000),
                "max_ms": round(max(values) * 1000),
                "statuses": dict(stats.statuses[name]),
            }
        )
    sessions = {
        name: {
            "count": len(values),
            "p50_s": round(percentile(values, 0.50), 2),
            "p95_s": round(percentile(values, 0.95), 2),
            "p99_s": round(percentile(values, 0.99), 2),
        }
        for name, values in stats.sessions.items()
    }
    failures = {key: count for key, count in stats.failures.items() if count}
    summary = {
        "base_url": args.base_url,
        "users": args.users,
        "dashboard_users": args.dashboard_users,
        "ramp_s": args.ramp,
        "think_s": args.think,
        "distinct_ips": args.distinct_ips,
        "elapsed_s": round(elapsed, 1),
        "requests": len(every),
        "throughput_rps": round(len(every) / elapsed, 1),
        "p50_ms": round(percentile(every, 0.50) * 1000),
        "p95_ms": round(percentile(every, 0.95) * 1000),
        "p99_ms": round(percentile(every, 0.99) * 1000),
        "mean_ms": round(statistics.fmean(every) * 1000) if every else 0,
        "failures": failures,
        "failed_requests": sum(failures.values()),
        "sessions_stopped": dict(stats.stopped),
        "endpoints": rows,
        "sessions": sessions,
        "examples": stats.examples,
    }
    return summary


def print_report(summary: dict) -> None:
    print(
        f"\n{summary['users']} app users + {summary['dashboard_users']} dashboard users, "
        f"ramp {summary['ramp_s']} s, think {summary['think_s']} s, "
        f"{'one address each' if summary['distinct_ips'] else 'all from one address'}, "
        f"{summary['elapsed_s']} s in all"
    )
    print(
        f"{summary['requests']} requests, {summary['throughput_rps']} req/s; "
        f"p50 {summary['p50_ms']} ms, p95 {summary['p95_ms']} ms, p99 {summary['p99_ms']} ms; "
        f"failed {summary['failed_requests']}"
    )
    print(f"\n{'endpoint':28} {'n':>5} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}  statuses")
    for row in summary["endpoints"]:
        statuses = ", ".join(f"{code}×{count}" for code, count in row["statuses"].items())
        print(
            f"{row['endpoint']:28} {row['count']:>5} {row['p50_ms']:>6}ms {row['p95_ms']:>6}ms "
            f"{row['p99_ms']:>6}ms {row['max_ms']:>6}ms  {statuses}"
        )
    print(f"\n{'session':34} {'n':>5} {'p50':>7} {'p95':>7} {'p99':>7}")
    for name, row in summary["sessions"].items():
        p50, p95, p99 = row["p50_s"], row["p95_s"], row["p99_s"]
        print(f"{name:34} {row['count']:>5} {p50:>6}s {p95:>6}s {p99:>6}s")
    if summary["sessions_stopped"]:
        print("\nSessions that stopped early:")
        for key, count in summary["sessions_stopped"].items():
            print(f"  {key}: {count}")
    if summary["failures"]:
        print("\nFailures:")
        for key, count in summary["failures"].items():
            print(f"  {key}: {count}")
    shown = {key: text for key, text in summary["examples"].items() if text}
    if shown:
        print("\nExample answers:")
        for key, text in list(shown.items())[:12]:
            print(f"  {key}: {text[:160]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True, help="https://your.domain (no /api/v1)")
    parser.add_argument("--users", type=int, default=300, help="mini app users (default 300)")
    parser.add_argument("--dashboard-users", type=int, default=20)
    parser.add_argument(
        "--people-in-db",
        type=int,
        default=300,
        help="workers loadtest_people made (--people); the managers' ids follow them",
    )
    parser.add_argument("--first-id", type=int, default=FIRST_ID)
    parser.add_argument("--ramp", type=float, default=10.0, help="seconds over which they start")
    parser.add_argument("--think", type=float, default=0.5, help="mean pause between steps (s)")
    parser.add_argument("--dashboard-rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0, help="per request (s)")
    parser.add_argument("--max-seconds", type=float, default=180.0, help="cut the run off")
    parser.add_argument("--token-env", default="EMPLOYEE_BOT_TOKEN")
    parser.add_argument("--host", help="Host header, when the URL is an address")
    parser.add_argument(
        "--distinct-ips",
        action="store_true",
        help="local runs straight at gunicorn only: give each person their own X-Forwarded-For "
        "address (by default everyone shares this machine's address, as behind a carrier NAT)",
    )
    parser.add_argument("--json", help="also write the results to this file")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"Set {args.token_env} to the employee bot's token.", file=sys.stderr)
        return 2
    if args.users > args.people_in_db:
        print("--users can't be more than --people-in-db.", file=sys.stderr)
        return 2
    random.seed(args.seed)
    stats = asyncio.run(run(args, token))
    summary = report(stats, args)
    print_report(summary)
    if args.json:
        with open(args.json, "w") as out:
            json.dump(summary, out, indent=2)
    return 1 if summary["failed_requests"] else 0


if __name__ == "__main__":
    sys.exit(main())
