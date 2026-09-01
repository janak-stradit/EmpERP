"""Emails each ticket assignee a digest of their tickets due today or overdue.

Not scheduled by the app itself (no in-process scheduler) — intended to be run once a
day via an external cron job, e.g. on the host running docker compose:

    0 8 * * * cd /opt/emperp && docker compose -f docker-compose.prod.yml exec -T app python scripts/send_due_reminders.py >> /var/log/emperp_due_reminders.log 2>&1

Safe to run manually any time to test: it only reads tickets and sends email, no writes.
"""

import html
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.email import send_email
from app.db.session import SessionLocal
from app.models.employee import Employee
from app.models.project import StatusCategory, TicketStatus
from app.models.ticket import Ticket
from app.models.user import User


def main() -> None:
    db = SessionLocal()
    try:
        today = date.today()
        done_status_ids = list(db.scalars(select(TicketStatus.id).where(TicketStatus.category == StatusCategory.DONE)))

        query = select(Ticket).where(
            Ticket.due_date.is_not(None),
            Ticket.due_date <= today,
            Ticket.assignee_id.is_not(None),
            Ticket.deleted_at.is_(None),
        )
        if done_status_ids:
            query = query.where(~Ticket.status_id.in_(done_status_ids))
        due_tickets = list(db.scalars(query))

        if not due_tickets:
            print("No due or overdue tickets. Nothing to send.")
            return

        by_assignee: dict[int, list[Ticket]] = defaultdict(list)
        for t in due_tickets:
            by_assignee[t.assignee_id].append(t)

        sent = 0
        for employee_id, tickets in by_assignee.items():
            employee = db.get(Employee, employee_id)
            if employee is None:
                continue
            user = db.get(User, employee.user_id)
            if user is None or not user.is_active:
                continue

            tickets.sort(key=lambda t: t.due_date)

            text_lines = [f"You have {len(tickets)} ticket(s) due today or overdue:", ""]
            row_html = []
            for t in tickets:
                overdue = t.due_date < today
                label = "OVERDUE" if overdue else "DUE TODAY"
                text_lines.append(f"[{label}] {t.ticket_key} - {t.summary} (due {t.due_date})")
                color = "#dc2626" if overdue else "#b45309"
                row_html.append(
                    "<tr>"
                    f'<td style="padding:6px 10px;color:{color};font-weight:700;white-space:nowrap;">{label}</td>'
                    f'<td style="padding:6px 10px;font-weight:600;">{html.escape(t.ticket_key)}</td>'
                    f'<td style="padding:6px 10px;">{html.escape(t.summary)}</td>'
                    f'<td style="padding:6px 10px;white-space:nowrap;">{t.due_date}</td>'
                    "</tr>"
                )

            html_body = (
                '<div style="font-family:Arial,sans-serif;font-size:14px;color:#1f2937;">'
                f"<p>You have {len(tickets)} ticket(s) due today or overdue:</p>"
                '<table style="border-collapse:collapse;width:100%;">'
                '<thead><tr style="background:#f3f4f6;text-align:left;">'
                '<th style="padding:6px 10px;">Status</th><th style="padding:6px 10px;">Ticket</th>'
                '<th style="padding:6px 10px;">Summary</th><th style="padding:6px 10px;">Due</th>'
                "</tr></thead>"
                f"<tbody>{''.join(row_html)}</tbody></table></div>"
            )

            send_email(
                to=user.email,
                subject=f"{len(tickets)} ticket(s) due or overdue",
                body="\n".join(text_lines),
                html_body=html_body,
            )
            sent += 1
            print(f"Sent due-ticket reminder to {user.email} ({len(tickets)} ticket(s)).")

        print(f"Done. Sent {sent} reminder email(s) for {len(due_tickets)} due/overdue ticket(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
