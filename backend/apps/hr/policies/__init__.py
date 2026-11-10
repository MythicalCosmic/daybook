"""Company policies people read and sign: the HR Policies page (docs/PLAN-OWNER.md §3.11).

The promise on the page: publish the dispensing and storage rules; everyone they apply to reads
and signs them in the app, and a new version asks again.

    queries     who a policy applies to, where each person stands, what the pages list
    services    every write: policies, drafts, publishing, signing, reminding (audited)
    notify      what people hear (to sign, reminders) and their managers (late), via the inbox
    follow_up   the beat job: newcomers asked, notices out, reminders before the deadline, late
                notes to the manager; outside the company's quiet hours
    owner_api   the dashboard's endpoints (`hr/policies/…`), `api` the mini app's
    hooks       registrations (imported by apps/hr/hooks.py)

The models are in apps/hr/models.py (Policy, PolicyVersion, PolicyAcknowledgement).
"""
