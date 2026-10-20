"""Inline-button callback data of projects (the employee bot's update conversation)."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class UpdateStep(StrEnum):
    HEALTH = "health"  # picked how the project is going
    SKIP = "skip"  # post without a text
    STOP = "stop"  # never mind


class ProjectUpdateCallback(CallbackData, prefix="prjupd"):
    step: UpdateStep
    project_id: int
    health: str = ""
