"""Re-encode the pictures already in public media: task proofs, company logos, avatars.

Uploads are decoded and re-encoded on the way in now (`apps.core.uploads`); this brings older
files up to the same standard once, after the deploy that introduced it. A file that is a
picture is re-encoded as `<uuid>.jpg` without metadata and the row points at it; a file that
isn't (an SVG or HTML "proof") is moved out of public media into
`PRIVATE_MEDIA_ROOT/quarantine/` and the field is cleared. Files already in the clean form are
left alone, so running it again is safe.

    manage.py sanitize_media --dry-run
    manage.py sanitize_media
"""

import io
import re
from pathlib import PurePosixPath

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image

from apps.core.storage import private_storage
from apps.core.uploads import InvalidUpload, sanitize_image

# (model, field, longest side)
TARGETS = (
    ("tasks.Task", "proof_photo", 2560),
    ("companies.Company", "logo", 1024),
    ("accounts.User", "photo", 1024),
)
CLEAN_NAME = re.compile(r"(^|/)[0-9a-f]{32}\.jpg$")


class Command(BaseCommand):
    help = "Re-encode stored proof photos, logos and avatars; move aside non-pictures."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report, change nothing.")
        parser.add_argument(
            "--all", action="store_true", help="Re-encode files that already look clean too."
        )

    def handle(self, *args, **options):
        dry_run, force = options["dry_run"], options["all"]
        totals = {"reencoded": 0, "clean": 0, "moved": 0, "missing": 0}
        for label, field_name, max_side in TARGETS:
            model = apps.get_model(label)
            for outcome in self._sanitize(model, field_name, max_side, dry_run, force):
                totals[outcome] += 1
        prefix = "Would have: " if dry_run else ""
        self.stdout.write(
            f"{prefix}re-encoded {totals['reencoded']}, already clean {totals['clean']}, "
            f"moved aside {totals['moved']}, missing {totals['missing']}."
        )

    def _sanitize(self, model, field_name, max_side, dry_run, force):
        field = model._meta.get_field(field_name)
        rows = model._base_manager.exclude(**{field_name: ""}).exclude(**{field_name: None})
        for instance in rows.iterator():
            name = getattr(instance, field_name).name
            storage = field.storage
            if not storage.exists(name):
                self.stderr.write(f"Missing: {name} ({model._meta.label} {instance.pk})")
                yield "missing"
                continue
            with storage.open(name, "rb") as file:
                data = file.read()
            if not force and _is_clean(name, data, max_side):
                yield "clean"
                continue
            try:
                picture = sanitize_image(data, max_side=max_side)
            except InvalidUpload:
                self.stdout.write(f"Not a picture, moving aside: {name}")
                if not dry_run:
                    private_storage.save(f"quarantine/{name}", ContentFile(data))
                    model._base_manager.filter(pk=instance.pk).update(**{field_name: ""})
                    storage.delete(name)
                yield "moved"
                continue
            if not dry_run:
                new_name = field.generate_filename(instance, picture.name)
                new_name = storage.save(new_name, picture)
                model._base_manager.filter(pk=instance.pk).update(**{field_name: new_name})
                if new_name != name:
                    storage.delete(name)
            yield "reencoded"


def _is_clean(name: str, data: bytes, max_side: int) -> bool:
    """Already what `sanitize_image` writes: a server-named JPEG without metadata."""
    if not CLEAN_NAME.search(PurePosixPath(name).as_posix()):
        return False
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG" or max(image.size) > max_side:
                return False
            markers = {marker for marker, _ in getattr(image, "applist", [])}
            return markers <= {"APP0"} and not (
                {"exif", "icc_profile", "comment", "xmp"} & set(image.info)
            )
    except OSError, ValueError, SyntaxError:
        return False
