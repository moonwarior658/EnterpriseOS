"""Public analytics contracts. Decimal values serialize as exact decimal strings."""
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PeriodKind(StrEnum):
    WEEK = "week"
    MONTH = "month"
    CUSTOM = "custom"


class StaffFilter(StrEnum):
    ACTIVE = "active"
    DISMISSED = "dismissed"
    ALL = "all"


class TargetMetric(StrEnum):
    AVERAGE_CHECK = "average_check"
    FULLNESS = "fullness"
    REVENUE = "revenue"


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: TargetMetric
    month: date
    value: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    expected_revision: int = Field(default=0, ge=0)

    @field_validator("month")
    @classmethod
    def month_start(cls, value):
        if value.day != 1:
            raise ValueError("Укажите первый день месяца")
        return value


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    metric: TargetMetric
    month: date
    value: Decimal
    revision: int
    created_by_user_id: int
    created_at: datetime


class PeriodRead(BaseModel):
    kind: PeriodKind
    start: date
    end: date  # inclusive
    previous_start: date
    previous_end: date


class MetricRead(BaseModel):
    fact: Decimal | None
    target: Decimal | None = None
    completion_percent: Decimal | None = None
    status: Literal["green", "warning", "red", "no_target", "no_data", "mixed_targets"]
    previous: Decimal | None = None
    change: Decimal | None = None
    change_percent: Decimal | None = None


class MetricsRead(BaseModel):
    revenue: MetricRead
    check_count: MetricRead
    average_check: MetricRead
    fullness: MetricRead


class TargetSegment(BaseModel):
    start: date
    end: date
    metrics: MetricsRead


class CoverageRead(BaseModel):
    complete: bool
    expected_days: int
    loaded_days: int
    missing_dates: list[date]
    checked_through: date | None


class CompletenessRead(BaseModel):
    current: CoverageRead
    previous: CoverageRead
    as_of: date
    warning: bool


class DailyMetricsRead(BaseModel):
    date: date
    metrics: MetricsRead


class FreshnessRead(BaseModel):
    last_success_at: datetime | None
    stale: bool
    update_failed: bool
    today: date
    history_from: date
    source_timezone: str


class AnalyticsRead(BaseModel):
    period: PeriodRead
    metrics: MetricsRead
    target_segments: list[TargetSegment]
    completeness: CompletenessRead | None = None
    dynamics: list[DailyMetricsRead] = Field(default_factory=list)


class EmployeeAnalyticsRead(AnalyticsRead):
    employee_id: UUID
    employee_name: str
    employee_status: str


class PointAnalyticsRead(AnalyticsRead):
    department_id: UUID
    department_name: str


class ProductDayRead(BaseModel):
    date: date
    quantity: Decimal | None
    revenue: Decimal | None


class ProductRead(BaseModel):
    iiko_product_id: UUID
    department_id: UUID
    product_name: str | None = None
    category: str | None = None
    department_name: str | None = None
    check_count: int = 0
    dynamics: list[ProductDayRead] = Field(default_factory=list)
    quantity: Decimal
    revenue: Decimal
    previous_quantity: Decimal
    previous_revenue: Decimal


class ProductSummaryRead(ProductRead):
    department_id: UUID | None = None


class ProductsRead(BaseModel):
    completeness: CompletenessRead | None = None
    period: PeriodRead
    products: list[ProductRead]
    categories: list[str] = Field(default_factory=list)
    summaries: list[ProductSummaryRead] = Field(default_factory=list)
    dynamics: list[ProductDayRead] = Field(default_factory=list)


class WorkspaceRead(BaseModel):
    status: FreshnessRead
    completeness: CompletenessRead
    analytics: AnalyticsRead | None = None
    points: list[PointAnalyticsRead] = Field(default_factory=list)
    sellers: list[EmployeeAnalyticsRead] = Field(default_factory=list)
    products: ProductsRead | None = None
