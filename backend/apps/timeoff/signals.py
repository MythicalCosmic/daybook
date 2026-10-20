"""What happens to time off, for other apps to react to. Every signal is sent on commit
(apps.core.signals.send_on_commit), with `sender=TimeOff`.

    time_off_approved   time_off, by   timeoff.services (approval, and someone who approves
                                       time off taking it themselves)
    time_off_cancelled  time_off, by,  timeoff.services (cancel, revoke) and, once per row,
                        previous_status  members.services._wind_down when someone leaves;
                                       previous_status is "pending" or "approved" (only
                                       approved days were taken)

`by` is the acting Membership, or None when the system or a platform admin did it.
"""

from django.dispatch import Signal

time_off_approved = Signal()
time_off_cancelled = Signal()
