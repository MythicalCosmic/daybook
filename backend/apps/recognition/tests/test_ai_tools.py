"""The recognition AI tools, run as the assistant runs them: permission, module, branch scope."""

import pytest

from apps.ai.tools.testing import call_tool
from apps.recognition.tests.conftest import DAY, at
from apps.recognition.tests.factories import BadgeAwardFactory, PointsEntryFactory

pytestmark = pytest.mark.django_db


def test_leaderboard_in_the_asker_s_scope(shop, owner, head, ali, nigora):
    PointsEntryFactory(membership=ali, points=30, reason="task", at=at(DAY))
    PointsEntryFactory(membership=nigora, points=50, reason="lesson", at=at(DAY))
    result = call_tool("recognition_leaderboard", owner)
    assert [row["name"] for row in result["rows"]] == ["Nigora Azimova", "Alisher Valiyev"]
    assert result["rows"][0]["points"] == 50 and result["data"]["period"] == "week"
    learning = call_tool("recognition_leaderboard", owner, kind="learning")
    assert [row["name"] for row in learning["rows"]] == ["Nigora Azimova"]
    assert [row["name"] for row in call_tool("recognition_leaderboard", head)["rows"]] == [
        "Alisher Valiyev"
    ]


def test_person_and_permissions(shop, owner, head, ali, nigora):
    PointsEntryFactory(membership=ali, points=120, reason="quiz", at=at(DAY))
    BadgeAwardFactory(membership=ali, badge="first_quiz")
    result = call_tool("recognition_person", owner, member_id=ali.pk)
    data = result["data"]
    assert (data["points"], data["level"], data["level_name"]) == (120, 2, "Learner")
    assert data["badges"] == ["First test"] and data["recent"][0]["for"] == "Quiz passed"
    assert "error" in call_tool("recognition_person", head, member_id=nigora.pk)
    assert call_tool("recognition_person", ali, member_id=ali.pk) == {"error": "not_allowed"}


def test_nothing_while_the_module_is_off(shop, owner, ali):
    shop.features = ["learning"]
    shop.save(update_fields=["features"])
    assert "error" in call_tool("recognition_leaderboard", owner)
