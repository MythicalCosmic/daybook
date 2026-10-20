from django.db import models

from apps.members.models import Membership


class MorningDigest(models.Model):
    """Someone's day was already handled by the morning digest, sent or with nothing to send."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="+")
    day = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "day"], name="one_digest_per_day"),
        ]

    def __str__(self):
        return f"{self.day} → {self.membership}"


class WeeklyReport(models.Model):
    """A weekly report someone already got, so each one goes out once."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="+")
    week_start = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "week_start"], name="one_report_per_week"
            ),
        ]

    def __str__(self):
        return f"{self.week_start} → {self.membership}"
