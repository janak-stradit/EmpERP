from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES
from app.models.notification import Notification, NotificationCategory
from app.models.user import User, UserRole


def hr_user_ids(db: Session, company_id: int | None, exclude_user_id: int | None = None) -> list[int]:
    ids = db.scalars(
        select(User.id).where(
            User.company_id == company_id,
            User.role.in_([UserRole(role) for role in HR_WRITE_ROLES]),
            User.is_active.is_(True),
        )
    ).all()
    return [i for i in ids if i != exclude_user_id]


def notify(
    db: Session,
    *,
    user_id: int,
    category: NotificationCategory,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    db.add(Notification(user_id=user_id, category=category, title=title, body=body, link=link))
    db.commit()


def notify_many(
    db: Session,
    *,
    user_ids: Iterable[int],
    category: NotificationCategory,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    unique_ids = set(user_ids)
    if not unique_ids:
        return
    for user_id in unique_ids:
        db.add(Notification(user_id=user_id, category=category, title=title, body=body, link=link))
    db.commit()
