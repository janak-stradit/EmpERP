from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationCategory


class NotificationResponse(BaseModel):
    id: int
    category: NotificationCategory
    title: str
    body: str | None
    link: str | None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCountResponse(BaseModel):
    count: int
