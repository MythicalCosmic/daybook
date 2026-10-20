"""What happens to a membership, for other apps to react to. Every signal is sent on commit
(apps.core.signals.send_on_commit), with `sender=Membership`.

    member_approved    membership, by                  members.services.approve
    member_left        membership, reason, by,         offboard ("left") and block ("blocked",
                       details, terminated_on          only for someone who was a member);
                                                       details = the offboarding wizard's answers
                                                       per step key ({} for a block);
                                                       terminated_on = their last day (a date)
    member_suspended   membership, by, until, reason   members.services.suspend
                                                       (until: the last day, or None)
    member_reinstated  membership, by                  members.services.reinstate

`by` is the acting Membership, or None when the system or a platform admin did it (a scheduled
reinstatement, Django admin). Receivers take `**kwargs`, so arguments can be added later.
"""

from django.dispatch import Signal

member_approved = Signal()
member_left = Signal()
member_suspended = Signal()
member_reinstated = Signal()
