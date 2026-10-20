import re
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.core.management.commands.perms_ts import render
from apps.members.permissions import Perm


def run(*args) -> str:
    out = StringIO()
    call_command("perms_ts", *args, stdout=out)
    return out.getvalue()


def test_every_permission_is_listed_once_in_registry_order():
    codes = re.findall(r'^  "([^"]+)",$', render(), flags=re.MULTILINE)

    assert codes == [str(perm) for perm in Perm]
    assert "export type Perm = (typeof PERMS)[number];" in render()


def test_writes_and_checks_the_file(tmp_path):
    target = tmp_path / "perms.generated.ts"

    with pytest.raises(CommandError, match="out of date"):
        run("--file", str(target), "--check")

    assert "Wrote" in run("--file", str(target))
    assert target.read_text() == render()
    assert "up to date" in run("--file", str(target), "--check")

    target.write_text(render().replace('"tasks.assign",\n', ""))
    with pytest.raises(CommandError, match="out of date"):
        run("--file", str(target), "--check")


def test_refuses_to_create_folders(tmp_path):
    with pytest.raises(CommandError, match="doesn't exist"):
        run("--file", str(tmp_path / "dashboard" / "src" / "core" / "perms.generated.ts"))
