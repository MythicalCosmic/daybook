"""What happens to time off, for other apps to react to. Every signal is sent on commit.

    time_off_approved   time_off, by   timeoff.services (approval)
    time_off_cancelled  time_off, by   timeoff.services (cancel, revoke) and, once per row,
                                       members.services._wind_down when someone leaves

`by` is the acting Membership, or None when the system did it.
"""

from django.dispatch import Signal

time_off_approved = Signal()
time_off_cancelled = Signal()
