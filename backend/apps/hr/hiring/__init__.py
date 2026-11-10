"""Hiring (docs/PLAN-OWNER.md §3.11, package G, v11): vacancies with a link and a QR code to the
employee bot, the questions applicants answer there, and each applicant's way from the first
answer to the hire.

    questions.py     what a vacancy may ask and how an answer is checked
    services.py      vacancies, applying in the bot, the pipeline (move, reject, hire, notes)
    queries.py       what a member sees (branch scope), counts per stage, the pulse, search
    bot.py           what the employee bot says to applicants (and the buttons)
    callbacks.py     the bot's inline-button data
    serializers.py, owner_api.py, owner_urls.py   the dashboard's `hr/vacancies/` and
                     `hr/applicants/` endpoints
    hooks.py         registrations (audit, pulse, search, inbox kind, file check)
    demo.py          Demo Dorixona's vacancies and applicants

The models live with the other HR records in `apps/hr/models.py`. "Hire" asks to join the
company for the applicant (`members.services.request_access`) and approves that request at
once with the vacancy's position, branch and the position's role (`approve`), so the person
gets the usual welcome and creates their account like anyone else.
"""
