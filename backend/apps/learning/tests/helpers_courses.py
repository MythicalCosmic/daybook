"""Helpers for package Q1's tests (courses, lessons, videos): a module, not a conftest, so the
two learning packages never touch the same file."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from apps.companies.models import Feature
from apps.members.models import AccessRole

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg isn't installed")


def turn_on(company, *features: str):
    """Switch learning (and `features`) on for `company`."""
    company.features = sorted({*company.features, Feature.LEARNING, *features})
    company.save(update_fields=["features"])
    return company


def role(company, name: str, *codes: str, branches_all: bool = False) -> AccessRole:
    permissions = ["dashboard.access", *codes]
    if branches_all:
        permissions.append("branches.all")
    found, _ = AccessRole.objects.get_or_create(
        company=company, name=name, defaults={"permissions": permissions}
    )
    return found


def manager(company, member, *, branches=None, **kwargs):
    """A learning manager; `branches` limits what they see (every branch when None)."""
    if branches is None:
        made = role(company, "Training lead", "learning.view", "learning.manage", branches_all=True)
    else:
        made = role(company, "Branch training lead", "learning.view", "learning.manage")
    person = member(company, made.name, **kwargs)
    if branches:
        person.branches.set(branches)
    return person


def make_mp4(path: Path, *, seconds: int = 2, size: str = "320x240", rate: int = 10) -> Path:
    """A real little video with sound (ffmpeg's test pattern and a tone)."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size={size}:rate={rate}",
            "-f",
            "lavfi",
            "-i",
            f"sine=duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return path
