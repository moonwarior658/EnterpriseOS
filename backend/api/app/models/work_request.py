from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User


class WorkRequest(Base):
    __tablename__ = "work_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('warehouse', 'repair')",
            name="ck_work_requests_type",
        ),
        CheckConstraint(
            "department IN ("
            "'Производство', 'Кондитерский цех', 'Кафе', 'М15', 'М6а', "
            "'М35', 'Снабжение', 'Администрация', 'Другое'"
            ")",
            name="ck_work_requests_department",
        ),
        CheckConstraint(
            "status IN ('new', 'in_progress', 'completed', 'cancelled')",
            name="ck_work_requests_status",
        ),
        CheckConstraint(
            "length(trim(description)) > 0 AND length(description) <= 5000",
            name="ck_work_requests_description",
        ),
        CheckConstraint(
            "("
            "request_type = 'warehouse' "
            "AND warehouse_category IN ('products', 'household', 'packaging') "
            "AND repair_category IS NULL AND priority IS NULL"
            ") OR ("
            "request_type = 'repair' "
            "AND warehouse_category IS NULL "
            "AND repair_category IN ("
            "'Сантехника', 'Электрика', 'Кассовое оборудование', "
            "'Компьютерное оборудование', 'Холодильное оборудование', "
            "'Тепловое оборудование', 'Кофемашина', 'Интернет', 'Другое'"
            ") "
            "AND priority IN ('routine', 'important', 'urgent')"
            ")",
            name="ck_work_requests_type_fields",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="new",
        server_default="new",
        nullable=False,
    )
    warehouse_category: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    repair_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_by: Mapped[User] = relationship()

    @property
    def created_by_name(self) -> str:
        return self.created_by.display_name
