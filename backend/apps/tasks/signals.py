"""Signals of the tasks app, for other apps to react to (connected in their hooks.py).

completed_with_photo(sender=Task, task_id=int, completed_at=str)
    sent once a completion with a proof photo is committed; `completed_at` (ISO) names that
    completion, so a receiver acting later can tell an undone Done from the one it was sent
    for (apps.ai's photo checker reads the photo after the undo window).
"""

from django.dispatch import Signal

completed_with_photo = Signal()
