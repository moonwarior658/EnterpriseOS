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
            "'М15', 'М35', 'М6А', 'Цех ГХ', 'Бар ГХ', 'Кухня', 'Авто', "
            "'Производство', 'Кондитерский цех', 'Кафе', 'М6а', "
            "'Снабжение', 'Администрация', 'Другое'"
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
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
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

    created_by: Mapped[User | None] = relationship()
    attachments: Mapped[list["WorkRequestAttachment"]] = relationship(
        back_populates="work_request",
        cascade="all, delete-orphan",
        order_by="WorkRequestAttachment.created_at",
    )
    comments: Mapped[list["WorkRequestComment"]] = relationship(
        back_populates="work_request",
        cascade="all, delete-orphan",
        order_by="WorkRequestComment.created_at",
    )

    @property
    def created_by_name(self) -> str:
        if self.created_by is not None:
            return self.created_by.display_name
        return self.author_name or f"Подразделение: {self.department}"

    @property
    def attachment_count(self) -> int:
        return len(self.attachments)


class WorkRequestAttachment(Base):
    __tablename__ = "work_request_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_request_id: Mapped[int] = mapped_column(
        ForeignKey("work_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    work_request: Mapped[WorkRequest] = relationship(
        back_populates="attachments",
    )


class WorkRequestComment(Base):
    __tablename__ = "work_request_comments"
    __table_args__ = (
        CheckConstraint(
            "length(trim(body)) > 0 AND length(body) <= 2000",
            name="ck_work_request_comments_body",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_request_id: Mapped[int] = mapped_column(
        ForeignKey("work_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    work_request: Mapped[WorkRequest] = relationship(
        back_populates="comments",
    )
    author: Mapped[User] = relationship()

    @property
    def author_name(self) -> str:
        return self.author.display_name
