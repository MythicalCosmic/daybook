"""Signals of sales and cash (docs/PLAN-OWNER.md §2.5), sent after the change commits.

- `shift_closed(shift)`: a cashier (or a manager) closed a shift; K reads its photos with AI.
- `shift_verified(shift)`: a manager verified a shift.
"""

from django.dispatch import Signal

shift_closed = Signal()
shift_verified = Signal()
