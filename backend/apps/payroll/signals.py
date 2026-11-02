"""What happens to payroll runs, for other apps to react to (docs/PLAN-OWNER.md §2.5). Every
signal is sent on commit, with `sender=PayrollRun`.

    payslips_published  run   some or all of a finalized run's payslips were published
    run_paid            run   every payslip of the run is paid
"""

from django.dispatch import Signal

payslips_published = Signal()
run_paid = Signal()
