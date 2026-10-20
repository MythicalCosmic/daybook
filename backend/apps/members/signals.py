"""What happens to a membership, for other apps to react to. Every signal is sent on commit.

    member_approved    membership, by                  members.services.approve
    member_left        membership, reason, by, details  offboard ("left") and block ("blocked");
                                                        details = the offboarding wizard's answers
                                                        per step key ({} for a block)
    member_suspended   membership, by, until, reason   members.services.suspend
    member_reinstated  membership, by                  members.services.reinstate

`by` is the acting Membership, or None when the system did it (a scheduled reinstatement).
"""

from django.dispatch import Signal

member_approved = Signal()
member_left = Signal()
member_suspended = Signal()
member_reinstated = Signal()
