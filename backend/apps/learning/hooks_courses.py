"""Registrations of package Q1 (courses, lessons, videos, who watched what).

Imported by `hooks.py`; register a function only once it exists (inbox kinds and actions,
pulse keys, search, streams, file checks, setup steps, company facts, signal receivers).
"""

from apps.core.files import register_file_check
from apps.learning import media

# Lesson videos and their posters: managers of learning, and whoever may open a lesson with it.
register_file_check("learning.video", media.may_open_video)
