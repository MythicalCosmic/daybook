"""``koz-agent``: the command line of the Ko‘z box (contract §10).

koz-agent pair https://daybook.example KOZ-7F3K-92QD   # once, stores the token locally
koz-agent nvr set 192.168.0.250                        # asks for the NVR user and password
koz-agent sources                                      # NVR channels, RTSP sources, scenes
koz-agent run                                          # the service; status page on :8737
koz-agent run --scene rush                             # the generated scene, no cameras needed
koz-agent selftest                                     # model, speed, server reachability
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import platform
import socket
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .clock import SystemClock
from .paths import data_dir

log = logging.getLogger("koz_agent")


def _paths() -> dict[str, Path]:
    root = data_dir()
    return {
        "root": root,
        "settings": root / "agent.json",
        "config": root / "config.json",
        "outbox": root / "outbox.sqlite3",
        "recordings": root / "recordings",
        "logs": root / "logs",
    }


def _store():
    from .secretstore import SecretStore

    return SecretStore(data_dir())


def _host_info() -> dict:
    system = platform.system()
    release = platform.release()
    if system == "Windows":
        try:
            build = int(platform.version().split(".")[-1])
            release = "11" if build >= 22000 else release
        except ValueError:
            pass
    return {
        "hostname": socket.gethostname(),
        "os": f"{system} {release}".strip(),
        "version": __version__,
    }


def _print(text: str = "") -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:  # an old console code page
        print(text.encode("ascii", "replace").decode(), flush=True)


# --- pair ---------------------------------------------------------------------------------


def cmd_pair(args) -> int:
    from .client import DaybookClient, DaybookError
    from .settings import Settings

    paths = _paths()
    server = args.server.rstrip("/")
    if not server.startswith(("https://", "http://")):
        server = "https://" + server
    client = DaybookClient(server)
    try:
        reply = client.pair(args.code.strip().upper(), _host_info())
    except DaybookError as exc:
        if exc.code == "bad_code":
            _print("This pairing code is unknown, used or expired. Create a new one in Daybook.")
        else:
            _print(f"Pairing failed: {exc}")
        return 2
    finally:
        client.close()
    token = reply.get("token")
    if not token:
        _print("Daybook did not return a token.")
        return 2
    _store().set("token", token)
    settings = Settings.load(paths["settings"])
    settings.server = server
    settings.agent = reply.get("agent")
    settings.save(paths["settings"])
    paths["config"].unlink(missing_ok=True)
    agent = reply.get("agent") or {}
    company = (agent.get("company") or {}).get("name", "")
    branch = (agent.get("branch") or {}).get("name", "")
    _print(f"Paired: {agent.get('name', 'Ko‘z box')} · {branch} ({company})")
    _print("Next: `koz-agent nvr set <host>` if the cameras are on an NVR, then `koz-agent run`.")
    return 0


# --- nvr ----------------------------------------------------------------------------------


def cmd_nvr(args) -> int:
    from .nvr import NvrAuthError, NvrClient, NvrError, parse_offset
    from .settings import NvrSettings, Settings

    paths = _paths()
    settings = Settings.load(paths["settings"])
    store = _store()
    if args.nvr_cmd == "list":
        if not settings.nvrs:
            _print("No NVR yet. Add one with `koz-agent nvr set <host>`.")
        for nvr in settings.nvrs:
            state = "wrong login — run `nvr set` again" if nvr.auth_failed_at else "ok"
            _print(
                f"{nvr.host}:{nvr.port}  user {nvr.user}  time {nvr.time}  "
                f"{len(nvr.channels)} channels  {state}"
            )
        return 0
    if args.nvr_cmd == "remove":
        settings.nvrs = [n for n in settings.nvrs if n.host != args.host]
        settings.save(paths["settings"])
        store.delete(f"nvr:{args.host}:password")
        _print(f"Removed {args.host}.")
        return 0

    # nvr set: the user types the login; it is tried once, never guessed or repeated
    if args.time != "auto":
        try:
            parse_offset(args.time)
        except ValueError:
            _print("--time is auto, utc or an offset such as +05:00")
            return 2
    default_user = settings.nvr(args.host).user if settings.nvr(args.host) else "admin"
    user = args.user or input(f"NVR user [{default_user}]: ").strip() or default_user
    password = getpass.getpass("NVR password (not shown): ")
    if not password:
        _print("No password given; nothing changed.")
        return 2
    nvr = settings.nvr(args.host) or NvrSettings(host=args.host)
    nvr.port, nvr.rtsp_port, nvr.user, nvr.time = args.port, args.rtsp_port, user, args.time
    client = NvrClient(args.host, user, password, port=args.port)
    try:
        channels = client.channels()
    except NvrAuthError:
        _print("Wrong NVR login: the NVR refused this user and password. Nothing was saved.")
        _print("Hikvision locks an account after a few wrong logins, so check it before retrying.")
        return 2
    except NvrError as exc:
        _print(
            f"Could not check the login now ({exc}). Saved anyway; the agent will try when it runs."
        )
        channels = None
    finally:
        client.close()
    if channels is not None:
        nvr.channels = [{"id": c.id, "name": c.name} for c in channels]
        _print(
            f"Login OK. {len(channels)} channels: "
            + ", ".join(f"{c.id} {c.name}" for c in channels[:12])
            + (" …" if len(channels) > 12 else "")
        )
    nvr.auth_failed_at = None
    if settings.nvr(args.host) is None:
        settings.nvrs.append(nvr)
    store.set(nvr.secret_name, password)
    settings.save(paths["settings"])
    return 0


# --- sources ------------------------------------------------------------------------------


def cmd_sources(args) -> int:
    from .scene import CAMERAS, SCENES, suggest_zones
    from .settings import Settings, SourceSettings
    from .sources import KEY, slug

    paths = _paths()
    settings = Settings.load(paths["settings"])
    if args.suggest_zones:
        _print(zones_json(suggest_zones()))
        return 0
    if args.src_cmd == "add":
        key = f"{args.kind}:{slug(args.name)}"
        if not KEY.match(key) or any(s.key == key for s in settings.sources):
            _print(f"{key} is taken or not a valid camera key.")
            return 2
        source = SourceSettings(key=key, kind=args.kind, name=args.name)
        if args.kind == "rtsp":
            _store().set(source.secret_name, args.target)
        else:
            source.target = args.target
        settings.sources.append(source)
        settings.save(paths["settings"])
        _print(f"Added {key}.")
        return 0
    if args.src_cmd == "remove":
        settings.sources = [s for s in settings.sources if s.key != args.key]
        settings.save(paths["settings"])
        _store().delete(f"source:{args.key}")
        _print(f"Removed {args.key}.")
        return 0

    _print("NVR channels")
    if not settings.nvrs:
        _print("  none (koz-agent nvr set <host>)")
    for index, nvr in enumerate(settings.nvrs):
        prefix = "nvr" if index == 0 else f"nvr{index + 1}"
        channels = nvr.channels
        if args.refresh and not nvr.auth_failed_at:
            channels = _refresh_channels(settings, nvr) or channels
            settings.save(paths["settings"])
        note = "  (wrong login: run `nvr set` again)" if nvr.auth_failed_at else ""
        _print(f"  {nvr.host}{note}")
        for ch in channels:
            _print(f"    {prefix}:{ch['id']:<4} {ch['name']}")
    _print("Other sources")
    if not settings.sources:
        _print("  none (koz-agent sources add rtsp|file <name> <url|path>)")
    for source in settings.sources:
        _print(f"  {source.key:<20} {source.name}")
    _print("Generated scene (koz-agent run --scene <name>)")
    _print(f"  scenes: {', '.join(SCENES)}")
    for key, (_view, name, role) in CAMERAS.items():
        _print(f"  {key:<20} {name} ({role})")
    return 0


def _refresh_channels(settings, nvr) -> list[dict] | None:
    from .nvr import NvrAuthError, NvrClient, NvrError

    password = _store().get(nvr.secret_name)
    if not password:
        return None
    client = NvrClient(nvr.host, nvr.user, password, port=nvr.port)
    try:
        channels = [{"id": c.id, "name": c.name} for c in client.channels()]
        nvr.channels = channels
        return channels
    except NvrAuthError:
        nvr.auth_failed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        log.error("%s: wrong NVR login; run `koz-agent nvr set %s`", nvr.host, nvr.host)
        return None
    except NvrError as exc:
        log.warning("%s: %s", nvr.host, exc)
        return None
    finally:
        client.close()


# --- run ----------------------------------------------------------------------------------


def _build_sources(settings, clock, store, args):
    from .settings import Settings  # noqa: F401  (typing aid)
    from .sources import FileSource, NvrSource, RtspSource, WebcamSource, make_sim_sources

    if args.scene:
        start = int(clock.time()) - max(0.0, args.at)
        return make_sim_sources(args.scene, args.seed, clock, threaded=True, start=start), {}
    sources, nvr_of = [], {}
    from .nvr import live_url

    for index, nvr in enumerate(settings.nvrs):
        if nvr.auth_failed_at:
            log.error(
                "%s: wrong NVR login; run `koz-agent nvr set %s` (not retrying)", nvr.host, nvr.host
            )
            continue
        password = store.get(nvr.secret_name)
        if not password:
            log.error("%s: no NVR password stored; run `koz-agent nvr set %s`", nvr.host, nvr.host)
            continue
        channels = _refresh_channels(settings, nvr) or nvr.channels
        if nvr.auth_failed_at:
            continue
        prefix = "nvr" if index == 0 else f"nvr{index + 1}"
        for ch in channels:
            key = f"{prefix}:{ch['id']}"
            url = live_url(nvr.host, int(ch["id"]), nvr.user, password, port=nvr.rtsp_port)
            sources.append(NvrSource(key, ch["name"], url, int(ch["id"]), clock=clock))
            nvr_of[key] = (nvr, password)
    for source in settings.sources:
        if source.kind == "rtsp":
            url = store.get(source.secret_name)
            if url:
                sources.append(RtspSource(source.key, source.name, url, clock=clock))
        elif source.kind == "file":
            sources.append(FileSource(source.key, source.name, source.target, clock=clock))
        elif source.kind == "webcam":
            sources.append(
                WebcamSource(
                    source.key,
                    source.name,
                    int(source.target or 0),
                    allow=settings.allow_webcam,
                    clock=clock,
                )
            )
    return sources, nvr_of


def cmd_run(args) -> int:
    from .agent import Agent, CameraConfig
    from .client import DaybookClient
    from .detectors import SimDetector, YoloxDetector
    from .logutil import setup_logging
    from .model import ModelError, ensure_model
    from .outbox import Outbox
    from .recorder import Recorder, ffmpeg_exe, pick_encoder
    from .scene import suggest_zones
    from .settings import Settings
    from .status import StatusServer

    paths = _paths()
    setup_logging(paths["logs"], verbose=args.verbose)
    try:
        import cv2

        cv2.setNumThreads(2)
    except Exception:  # pragma: no cover
        pass
    settings = Settings.load(paths["settings"])
    store = _store()
    clock = SystemClock()
    sources, nvr_of = _build_sources(settings, clock, store, args)
    if not sources:
        _print(
            "No cameras. Add an NVR (`koz-agent nvr set <host>`) or a source, or try "
            "`koz-agent run --scene demo`."
        )
        return 2

    detector_name = args.detector or ("sim" if args.scene else settings.detector)
    sim = SimDetector()
    yolox = None
    if detector_name == "yolox":
        try:
            yolox = YoloxDetector(ensure_model(paths["root"]), legacy_norm=settings.legacy_norm)
        except (ModelError, OSError) as exc:
            _print(f"The detector cannot start: {exc}")
            return 2

    def detector_for(source):
        if source.kind == "sim" and detector_name == "sim":
            return sim
        return yolox or sim

    token = store.get("token")
    client = None
    if settings.server and token and not args.offline:
        client = DaybookClient(settings.server, token, clock=clock)
    outbox = Outbox(paths["outbox"]) if client else None
    ffmpeg = ffmpeg_exe()
    encoder = pick_encoder(ffmpeg)
    recorder = Recorder(
        paths["recordings"], clock, ffmpeg=ffmpeg, encoder=encoder, fps=settings.record_fps
    )
    defaults = {
        key: CameraConfig(name=s["name"], role=s["role"], enabled=True, zones=s["zones"])
        for key, s in suggest_zones().items()
    }

    nvr_clip = nvr_snapshot = None
    if nvr_of:
        nvr_clip, nvr_snapshot = _nvr_callbacks(nvr_of, ffmpeg, encoder)

    agent = Agent(
        clock=clock,
        sources=sources,
        detector_for=detector_for,
        client=client,
        outbox=outbox,
        recorder=recorder,
        defaults=defaults,
        max_inferences_per_s=settings.max_inferences_per_s,
        lang=args.lang or settings.language,
        config_cache=paths["config"],
        nvr_clip=nvr_clip,
        nvr_snapshot=nvr_snapshot,
        detector_name=detector_name,
        encoder=encoder,
    )
    status = StatusServer(agent, port=args.port or settings.status_port)
    try:
        port = status.start()
    except OSError as exc:
        _print(f"The status page cannot start on port {args.port or settings.status_port}: {exc}")
        return 2
    agent.start()
    what = f"scene {args.scene}" if args.scene else f"{len(sources)} cameras"
    server = settings.server if client else "not paired (local only)"
    _print(
        f"Ko‘z agent {__version__} · {what} · detector {detector_name} · "
        f"encoder {encoder or 'none'}"
    )
    _print(f"Daybook: {server}")
    _print(f"Status page: http://127.0.0.1:{port}   (Ctrl+C to stop)")
    stop = threading.Event()
    try:
        while not stop.wait(1.0):
            if args.duration and time.monotonic() - _START > args.duration:
                break
    except KeyboardInterrupt:
        pass
    _print("Stopping…")
    agent.stop()
    status.stop()
    if client:
        client.close()
    if outbox:
        outbox.close()
    return 0


def _nvr_callbacks(nvr_of: dict, ffmpeg: str | None, encoder: str | None):
    from .nvr import NvrAuthError, NvrClient, NvrError, parse_offset, playback_url
    from .recorder import ClipError, cut_nvr_clip

    offsets: dict[str, int] = {}

    def offset_for(nvr, password) -> int:
        if nvr.time != "auto":
            return parse_offset(nvr.time)
        if nvr.host not in offsets:
            client = NvrClient(nvr.host, nvr.user, password, port=nvr.port)
            try:
                offsets[nvr.host] = client.time().offset_s
            finally:
                client.close()
        return offsets[nvr.host]

    def nvr_clip(cam, start: float, end: float):
        nvr, password = nvr_of[cam.key]
        if not ffmpeg or not encoder:
            raise ClipError("nvr_error", "no H.264 encoder on this PC")
        try:
            offset = offset_for(nvr, password)
        except NvrAuthError as exc:
            raise ClipError("nvr_error", str(exc)) from exc
        except NvrError as exc:
            raise ClipError("nvr_error", str(exc)) from exc
        url = playback_url(
            nvr.host,
            cam.source.channel,
            start,
            end,
            nvr.user,
            password,
            offset_s=offset,
            port=nvr.rtsp_port,
        )
        return cut_nvr_clip(ffmpeg, encoder, url, min(60.0, end - start))

    def nvr_snapshot(cam) -> bytes | None:
        nvr, password = nvr_of[cam.key]
        client = NvrClient(nvr.host, nvr.user, password, port=nvr.port)
        try:
            return client.snapshot(cam.source.channel)
        finally:
            client.close()

    return nvr_clip, nvr_snapshot


# --- selftest -----------------------------------------------------------------------------


def cmd_selftest(args) -> int:
    import numpy as np

    from .client import DaybookClient, DaybookError, OfflineError, RevokedError
    from .detectors import YoloxDetector
    from .model import MODEL_SHA256, ModelError, ensure_model
    from .recorder import ffmpeg_exe, listed_encoders, pick_encoder
    from .settings import Settings

    paths = _paths()
    ok = True
    _print(
        f"Ko‘z agent {__version__} on {platform.system()} {platform.release()}, "
        f"Python {platform.python_version()}"
    )
    _print(f"Data folder: {paths['root']}")

    shown = [-1]

    def progress(done: int, total: int | None) -> None:
        percent = done * 100 // total if total else -1
        if percent // 10 != shown[0] // 10 or percent == 100:
            shown[0] = percent
            sys.stdout.write(f"\r  downloading the model… {percent}%")
            sys.stdout.flush()

    try:
        started = time.perf_counter()
        model = ensure_model(paths["root"], download=not args.no_download, progress=progress)
        took = time.perf_counter() - started
        if took > 2:
            _print("")
        _print(
            f"Model: {model.name} ({model.stat().st_size / 1e6:.1f} MB), "
            f"SHA-256 {MODEL_SHA256[:12]}… ok"
        )
        load_started = time.perf_counter()
        detector = YoloxDetector(model)
        load_ms = (time.perf_counter() - load_started) * 1000
        blank = np.zeros((540, 960, 3), np.uint8)
        first_started = time.perf_counter()
        detector.detect_image(blank)
        first_ms = (time.perf_counter() - first_started) * 1000
        median_ms = detector.benchmark(blank, runs=args.runs, warmup=1)
        _print(
            f"Inference (YOLOX-tiny 416×416, CPU, 2 threads) on a blank 960×540 frame: "
            f"{median_ms:.1f} ms median of {args.runs} (first {first_ms:.0f} ms, "
            f"load {load_ms:.0f} ms) → up to {1000 / median_ms:.0f} frames/s"
        )
    except (ModelError, OSError) as exc:
        ok = False
        _print(f"Model: FAILED — {exc}")

    ffmpeg = ffmpeg_exe()
    if ffmpeg:
        listed = listed_encoders(ffmpeg)
        have = [n for n in ("h264_mf", "libopenh264", "libx264") if n in listed]
        chosen = pick_encoder(ffmpeg)
        _print(
            f"ffmpeg: {Path(ffmpeg).name}; H.264 encoders in this build: "
            f"{', '.join(have) or 'none'}; recorder uses: {chosen or 'none (no recording)'}"
        )
    else:
        _print("ffmpeg: not available on this platform (no recording)")

    settings = Settings.load(paths["settings"])
    token = _store().get("token")
    if settings.server and token:
        client = DaybookClient(settings.server, token, retries=1)
        try:
            client.config()
            _print(f"Daybook: {settings.server} reachable, token accepted")
        except RevokedError:
            ok = False
            _print(f"Daybook: {settings.server} refused the token (pair this box again)")
        except OfflineError as exc:
            ok = False
            _print(f"Daybook: {settings.server} not reachable ({exc.detail})")
        except DaybookError as exc:
            ok = False
            _print(f"Daybook: {settings.server} answered {exc}")
        finally:
            client.close()
    else:
        _print("Daybook: not paired yet (koz-agent pair <url> <code>)")
    for nvr in settings.nvrs:
        stored = "password stored" if _store().get(nvr.secret_name) else "no password"
        state = "wrong login" if nvr.auth_failed_at else stored
        _print(f"NVR {nvr.host}: {len(nvr.channels)} channels, {state}")
    return 0 if ok else 1


# --- devserver ----------------------------------------------------------------------------


def cmd_devserver(args) -> int:
    from .devserver import FakeDaybook

    fake = FakeDaybook(auto_setup=args.auto_setup)
    code = fake.new_code()
    server = fake.serve(port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    _print(f"Fake Daybook on {url} (device API only, in memory)")
    _print(f"Pair a box with:  koz-agent pair {url} {code}")
    started = time.monotonic()
    try:
        while not args.duration or time.monotonic() - started < args.duration:
            time.sleep(5)
            _print(
                f"  cameras {len(fake.cameras)} · live reports {len(fake.lives)} · "
                f"stat rows {len(fake.stats)} · events {len(fake.events)} · "
                f"snapshots {len(fake.snapshots)}"
            )
    except KeyboardInterrupt:
        pass
    server.shutdown()
    return 0


# --- the parser ---------------------------------------------------------------------------

_START = time.monotonic()


def build_parser() -> argparse.ArgumentParser:
    from .scene import SCENES

    parser = argparse.ArgumentParser(prog="koz-agent", description="Daybook Ko‘z box")
    parser.add_argument("--version", action="version", version=f"koz-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pair", help="pair this PC with Daybook (once)")
    p.add_argument("server", help="Daybook's address, e.g. https://daybook.example")
    p.add_argument("code", help="the pairing code from Daybook, e.g. KOZ-7F3K-92QD")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("nvr", help="the NVR's login")
    nvr_sub = p.add_subparsers(dest="nvr_cmd", required=True)
    s = nvr_sub.add_parser("set", help="store the NVR's user and password (asked, not shown)")
    s.add_argument("host")
    s.add_argument("--port", type=int, default=80, help="ISAPI (HTTP) port, default 80")
    s.add_argument("--rtsp-port", type=int, default=554)
    s.add_argument("--user", help="the NVR user (asked when left out)")
    s.add_argument(
        "--time",
        default="auto",
        help="how the NVR reads playback times: auto (its own zone), utc, or +05:00",
    )
    nvr_sub.add_parser("list", help="the NVRs this box knows")
    r = nvr_sub.add_parser("remove", help="forget an NVR and its password")
    r.add_argument("host")
    p.set_defaults(func=cmd_nvr)

    p = sub.add_parser("sources", help="NVR channels, RTSP sources and scenes")
    p.add_argument(
        "--suggest-zones", action="store_true", help="print zone JSON that fits the generated scene"
    )
    p.add_argument("--refresh", action="store_true", help="ask the NVRs for their channels now")
    src_sub = p.add_subparsers(dest="src_cmd")
    a = src_sub.add_parser("add", help="add an RTSP stream or a video file")
    a.add_argument("kind", choices=("rtsp", "file"))
    a.add_argument("name")
    a.add_argument("target", help="rtsp://… or a file path")
    r = src_sub.add_parser("remove", help="remove a source")
    r.add_argument("key")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("run", help="the service, with the status page on :8737")
    p.add_argument("--scene", choices=SCENES, help="the generated scene instead of cameras")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument(
        "--at",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="start the scene this many seconds into its loop (e.g. 150: the rush)",
    )
    p.add_argument("--detector", choices=("yolox", "sim"))
    p.add_argument("--port", type=int, help="status page port (default 8737)")
    p.add_argument("--lang", choices=("uz", "ru", "en"))
    p.add_argument("--offline", action="store_true", help="do not talk to Daybook")
    p.add_argument("--duration", type=float, default=0, help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("selftest", help="model, inference speed, encoder, server reachability")
    p.add_argument("--no-download", action="store_true")
    p.add_argument("--runs", type=int, default=20)
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("devserver", help="a fake Daybook for trying a box locally")
    p.add_argument("--port", type=int, default=8780)
    p.add_argument(
        "--auto-setup",
        action="store_true",
        help="enable scene cameras with their suggested zones as they arrive",
    )
    p.add_argument("--duration", type=float, default=0, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_devserver)
    return parser


def _utf8_output() -> None:
    """A pipe on Windows gets the ANSI code page; write UTF-8 so ‘ and Cyrillic survive."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty() and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def zones_json(suggestion: dict) -> str:
    """The suggested zones, one zone per line, ready to paste."""
    lines = ["{"]
    keys = list(suggestion)
    for i, key in enumerate(keys):
        cam = suggestion[key]
        lines.append(
            f'  "{key}": {{"name": {json.dumps(cam["name"], ensure_ascii=False)}, '
            f'"role": "{cam["role"]}", "zones": ['
        )
        for j, zone in enumerate(cam["zones"]):
            comma = "," if j < len(cam["zones"]) - 1 else ""
            lines.append("    " + json.dumps(zone, ensure_ascii=False) + comma)
        lines.append("  ]}" + ("," if i < len(keys) - 1 else ""))
    lines.append("}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
