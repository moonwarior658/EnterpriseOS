from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.supply import LegalContour


MAX_RAW_INPUT_LENGTH = 20_000
MAX_LINE_LENGTH = 1_000
MAX_PRODUCT_NAME_LENGTH = 240
MAX_REFERENCE_NAME_LENGTH = 160
MAX_REFERENCE_CODE_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 2_000
MAX_IIKO_ID_LENGTH = 160
MAX_PUBLIC_LINE_COUNT = 200
MAX_PUBLIC_AUTHOR_NAME_LENGTH = 160
MAX_PUBLIC_AUTHOR_PHONE_LENGTH = 40


class SupplyRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    PLANNED = "PLANNED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SupplyRequestCycleStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SupplyDuplicateStatus(StrEnum):
    NONE = "NONE"
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"


class SupplyDuplicateResolutionAction(StrEnum):
    KEEP_SEPARATE = "KEEP_SEPARATE"
    MARK_CONFIRMED = "MARK_CONFIRMED"


class SupplyRequestSourceType(StrEnum):
    INTERNAL = "INTERNAL"
    PUBLIC_FORM = "PUBLIC_FORM"
    WORK_REQUEST_MANUAL = "WORK_REQUEST_MANUAL"


class SupplyLineMatchStatus(StrEnum):
    UNPROCESSED = "UNPROCESSED"
    PARSED = "PARSED"
    MATCHED = "MATCHED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


class SupplyLineMatchMethod(StrEnum):
    EXACT_PRODUCT = "EXACT_PRODUCT"
    EXACT_ALIAS = "EXACT_ALIAS"
    MANUAL = "MANUAL"


class SupplyLineMatchAction(StrEnum):
    MATCH = "MATCH"
    REJECT = "REJECT"
    RESET = "RESET"


class DepartmentRead(BaseModel):
    id: UUID
    code: str
    name: str
    legal_contour: LegalContour | None
    is_active: bool
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class SupplyRequestDirectionRead(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    display_order: int

    model_config = ConfigDict(from_attributes=True)


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Дата и время должны содержать часовой пояс")
    return value


class SupplyRequestCycleCreate(BaseModel):
    direction_id: UUID
    cycle_date: date
    opens_at: datetime
    closes_at: datetime
    hard_closes_at: datetime | None = None
    status: SupplyRequestCycleStatus = SupplyRequestCycleStatus.SCHEDULED

    model_config = ConfigDict(extra="forbid")

    @field_validator("opens_at", "closes_at", "hard_closes_at")
    @classmethod
    def validate_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return None if value is None else _require_aware_datetime(value)

    @model_validator(mode="after")
    def validate_window(self):
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at должен быть позже opens_at")
        if (
            self.hard_closes_at is not None
            and self.hard_closes_at < self.closes_at
        ):
            raise ValueError(
                "hard_closes_at должен быть не раньше closes_at"
            )
        return self


class SupplyRequestCycleUpdate(BaseModel):
    direction_id: UUID | None = None
    cycle_date: date | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    hard_closes_at: datetime | None = None
    status: SupplyRequestCycleStatus | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("direction_id", "cycle_date", "opens_at", "closes_at", "status")
    @classmethod
    def reject_null_required_fields(cls, value):
        if value is None:
            raise ValueError("Поле не может быть null")
        return value

    @field_validator("opens_at", "closes_at", "hard_closes_at")
    @classmethod
    def validate_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return None if value is None else _require_aware_datetime(value)


class SupplyRequestCycleRead(BaseModel):
    id: UUID
    direction_id: UUID
    direction: SupplyRequestDirectionRead
    cycle_date: date
    opens_at: datetime
    closes_at: datetime
    hard_closes_at: datetime | None
    status: SupplyRequestCycleStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyRequestCyclePage(BaseModel):
    items: list[SupplyRequestCycleRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SupplyUnitRead(BaseModel):
    id: UUID
    code: str
    name_ru: str
    short_name_ru: str
    allows_fraction: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyProductAliasRead(BaseModel):
    id: UUID
    alias: str
    status: str
    successful_application_count: int
    last_applied_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _strip_required(value: str, *, label: str, max_length: int) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label} не может быть пустым")
    if len(stripped) > max_length:
        raise ValueError(f"{label} не может быть длиннее {max_length} символов")
    return stripped


def _strip_optional(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > max_length:
        raise ValueError(
            f"Значение не может быть длиннее {max_length} символов"
        )
    return stripped


class SupplyReferenceCreate(BaseModel):
    code: str
    name: str
    description: str | None = None
    is_active: bool = True
    sort_order: int = 0

    model_config = ConfigDict(extra="forbid")

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return _strip_required(
            value,
            label="Код",
            max_length=MAX_REFERENCE_CODE_LENGTH,
        )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required(
            value,
            label="Название",
            max_length=MAX_REFERENCE_NAME_LENGTH,
        )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return _strip_optional(value, max_length=MAX_DESCRIPTION_LENGTH)


class SupplyReferenceUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Код не может быть null")
        return SupplyReferenceCreate.validate_code(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Название не может быть null")
        return SupplyReferenceCreate.validate_name(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return _strip_optional(value, max_length=MAX_DESCRIPTION_LENGTH)

    @field_validator("is_active")
    @classmethod
    def validate_is_active(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("Активность не может быть null")
        return value

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("Порядок сортировки не может быть null")
        return value


class SupplyReferenceRead(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyReferencePage(BaseModel):
    items: list[SupplyReferenceRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SupplyProductCreate(BaseModel):
    name: str
    default_unit_id: UUID
    request_direction_id: UUID | None = None
    iiko_id: str | None = None
    category_id: UUID | None = None
    storage_zone_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Название товара не может быть пустым")
        if len(stripped) > MAX_PRODUCT_NAME_LENGTH:
            raise ValueError(
                "Название товара не может быть длиннее "
                f"{MAX_PRODUCT_NAME_LENGTH} символов"
            )
        return stripped

    @field_validator("iiko_id")
    @classmethod
    def validate_iiko_id(cls, value: str | None) -> str | None:
        return _strip_optional(value, max_length=MAX_IIKO_ID_LENGTH)


class SupplyProductUpdate(BaseModel):
    name: str | None = None
    default_unit_id: UUID | None = None
    request_direction_id: UUID | None = None
    iiko_id: str | None = None
    category_id: UUID | None = None
    storage_zone_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Название товара не может быть null")
        return SupplyProductCreate.validate_name(value)

    @field_validator("default_unit_id")
    @classmethod
    def validate_default_unit_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("Базовая единица товара не может быть null")
        return value

    @field_validator("iiko_id")
    @classmethod
    def validate_iiko_id(cls, value: str | None) -> str | None:
        return SupplyProductCreate.validate_iiko_id(value)


class SupplyProductAliasCreate(BaseModel):
    alias: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Алиас товара не может быть пустым")
        if len(stripped) > MAX_PRODUCT_NAME_LENGTH:
            raise ValueError(
                "Алиас товара не может быть длиннее "
                f"{MAX_PRODUCT_NAME_LENGTH} символов"
            )
        return stripped


class SupplyProductRead(BaseModel):
    id: UUID
    name: str
    iiko_id: str | None
    default_unit: SupplyUnitRead
    request_direction: SupplyRequestDirectionRead | None
    category: SupplyReferenceRead | None
    storage_zone: SupplyReferenceRead | None
    is_active: bool
    archived_at: datetime | None
    archived_by_user_id: int | None
    aliases: list[SupplyProductAliasRead]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyProductPage(BaseModel):
    items: list[SupplyProductRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SupplyRequestLineCreate(BaseModel):
    raw_text: str
    product_id: UUID | None = None
    requested_unit_id: UUID | None = None
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=3,
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("raw_text")
    @classmethod
    def validate_raw_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Строка заявки не может быть пустой")
        if len(value) > MAX_LINE_LENGTH:
            raise ValueError(
                f"Строка заявки не может быть длиннее {MAX_LINE_LENGTH} символов"
            )
        return value

    @model_validator(mode="after")
    def validate_structured_quantity(self):
        if (self.requested_unit_id is None) != (self.quantity is None):
            raise ValueError(
                "Количество и единица измерения должны быть указаны вместе"
            )
        return self


class SupplyRequestLineRead(BaseModel):
    id: UUID
    position: int
    raw_text: str
    working_name: str
    parsed_name: str | None
    parsed_quantity: Decimal | None
    parsed_unit: SupplyUnitRead | None
    product: SupplyProductRead | None
    requested_unit: SupplyUnitRead | None
    product_id: UUID | None
    requested_unit_id: UUID | None
    quantity: Decimal | None
    send_quantity: Decimal | None
    match_status: SupplyLineMatchStatus
    match_method: SupplyLineMatchMethod | None
    match_confidence: Decimal | None
    matched_at: datetime | None
    matched_by_user_id: int | None
    match_notes: str | None
    duplicate_group_id: UUID | None
    duplicate_status: SupplyDuplicateStatus
    allocations: list["SupplyLineAllocationRead"]
    planned_transfer: Decimal
    planned_purchase: Decimal
    planned_cancel: Decimal
    planned_total: Decimal
    fulfilled_transfer: Decimal
    fulfilled_purchase: Decimal
    fulfilled_total: Decimal
    unresolved_quantity: Decimal
    active_debt_id: UUID | None
    active_debt_quantity: Decimal
    debt_inclusion_status: "SupplyDebtInclusionStatus"
    debt_quantity_included: Decimal
    requires_debt_confirmation: bool
    unallocated_quantity: Decimal
    planning_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyLineManualMatch(BaseModel):
    expected_version: int = Field(ge=1)
    product_id: UUID | None = None
    unit_id: UUID | None = None
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=3,
    )
    action: SupplyLineMatchAction
    notes: str | None = Field(default=None, max_length=2000)
    save_alias: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_action_fields(self):
        references = (self.product_id, self.unit_id, self.quantity)
        if self.action == SupplyLineMatchAction.MATCH:
            if any(value is None for value in references):
                raise ValueError(
                    "Для MATCH обязательны товар, единица и количество"
                )
        elif any(value is not None for value in references):
            raise ValueError(
                "Для REJECT и RESET товар, единица и количество не передаются"
            )
        if self.save_alias and self.action != SupplyLineMatchAction.MATCH:
            raise ValueError("Алиас можно сохранить только при сопоставлении")
        return self


class SupplyLineWorkingValuesUpdate(BaseModel):
    request_version: int = Field(ge=1)
    working_name: str
    requested_quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=3,
    )
    send_quantity: Decimal = Field(
        ge=0,
        max_digits=18,
        decimal_places=3,
    )
    requested_unit_id: UUID

    model_config = ConfigDict(extra="forbid")

    @field_validator("working_name")
    @classmethod
    def validate_working_name(cls, value: str) -> str:
        return _strip_required(
            value,
            label="Рабочее название",
            max_length=MAX_PRODUCT_NAME_LENGTH,
        )


class SupplyLineWorkingValuesRead(BaseModel):
    request_version: int
    line: SupplyRequestLineRead


class SupplyRecognitionResult(BaseModel):
    line_id: UUID
    position: int
    match_status: SupplyLineMatchStatus
    match_method: SupplyLineMatchMethod | None
    skipped: bool = False


class SupplyRecognitionSummary(BaseModel):
    total: int
    matched: int
    needs_review: int
    rejected: int
    skipped: int
    results: list[SupplyRecognitionResult]


class SupplyExpectedVersion(BaseModel):
    expected_version: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")


class SupplyRequestPlan(SupplyExpectedVersion):
    simple_mode: bool = False


class SupplyAliasStatusUpdate(BaseModel):
    status: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value != "DISABLED":
            raise ValueError("В этом срезе алиас можно только отключить")
        return value


class SupplyAllocationAction(StrEnum):
    TRANSFER = "TRANSFER"
    PURCHASE = "PURCHASE"
    CANCEL = "CANCEL"


class SupplyDebtStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SupplyDebtSeverity(StrEnum):
    YELLOW = "YELLOW"
    PURPLE = "PURPLE"
    RED = "RED"
    CRITICAL = "CRITICAL"


class SupplyDebtInclusionStatus(StrEnum):
    NONE = "NONE"
    COVERED_BY_REQUEST = "COVERED_BY_REQUEST"
    REQUEST_BELOW_DEBT = "REQUEST_BELOW_DEBT"
    CONFIRMED_PARTIAL = "CONFIRMED_PARTIAL"


class SupplyLineAllocationInput(BaseModel):
    action: SupplyAllocationAction
    planned_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    unit_id: UUID
    comment: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class SupplyLineAllocationsUpdate(SupplyExpectedVersion):
    allocations: list[SupplyLineAllocationInput] = Field(max_length=3)

    @field_validator("allocations")
    @classmethod
    def unique_actions(
        cls, value: list[SupplyLineAllocationInput]
    ) -> list[SupplyLineAllocationInput]:
        if len({item.action for item in value}) != len(value):
            raise ValueError("Каждое действие можно указать только один раз")
        return value


class SupplyLineAllocationRead(BaseModel):
    id: UUID
    action: SupplyAllocationAction
    planned_quantity: Decimal
    unit_id: UUID
    comment: str | None
    fulfilled_quantity: Decimal
    fulfilled_at: datetime | None
    fulfilled_by_user_id: int | None
    fulfillment_comment: str | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyFulfillmentItem(BaseModel):
    allocation_id: UUID
    fulfilled_quantity: Decimal = Field(
        ge=0, max_digits=18, decimal_places=3
    )
    comment: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, value: str | None) -> str | None:
        return _strip_optional(value, max_length=2000)


class SupplyLineFulfillmentUpdate(SupplyExpectedVersion):
    items: list[SupplyFulfillmentItem] = Field(min_length=1, max_length=2)

    @field_validator("items")
    @classmethod
    def unique_allocations(
        cls, value: list[SupplyFulfillmentItem]
    ) -> list[SupplyFulfillmentItem]:
        if len({item.allocation_id for item in value}) != len(value):
            raise ValueError("Каждый allocation можно указать только один раз")
        return value


class SupplyDebtInclusionConfirm(SupplyExpectedVersion):
    included_quantity: Decimal = Field(
        ge=0, max_digits=18, decimal_places=3
    )


class SupplyDebtClose(BaseModel):
    expected_version: int = Field(ge=1)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    comment: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, value: str) -> str:
        return _strip_required(value, label="Комментарий", max_length=2000)


class SupplyDebtCancel(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, value: str) -> str:
        return _strip_required(value, label="Причина", max_length=2000)


class SupplyRequestCancel(SupplyExpectedVersion):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class SupplyRecognitionRequest(SupplyExpectedVersion):
    force: bool = False


class SupplyDuplicateGroupResolve(SupplyExpectedVersion):
    action: SupplyDuplicateResolutionAction


class SupplyRequestCreate(BaseModel):
    department_id: UUID
    direction_id: UUID
    cycle_id: UUID
    raw_input: str
    lines: list[SupplyRequestLineCreate]

    model_config = ConfigDict(extra="forbid")

    @field_validator("raw_input")
    @classmethod
    def validate_raw_input(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Исходный текст заявки не может быть пустым")
        if len(stripped) > MAX_RAW_INPUT_LENGTH:
            raise ValueError(
                "Исходный текст заявки не может быть длиннее "
                f"{MAX_RAW_INPUT_LENGTH} символов"
            )
        return stripped

    @field_validator("lines")
    @classmethod
    def validate_lines(
        cls,
        value: list[SupplyRequestLineCreate],
    ) -> list[SupplyRequestLineCreate]:
        if not value:
            raise ValueError("Добавьте хотя бы одну строку заявки")
        if len(value) > 200:
            raise ValueError("В заявке может быть не больше 200 строк")
        return value


class SupplyRequestRead(BaseModel):
    id: UUID
    public_number: str
    department: DepartmentRead
    direction: SupplyRequestDirectionRead
    cycle_id: UUID | None
    cycle: SupplyRequestCycleRead | None
    status: SupplyRequestStatus
    source_type: SupplyRequestSourceType
    source_work_request_id: int | None
    raw_input: str
    version: int
    created_by_user_id: int | None
    submitted_at: datetime | None
    planned_at: datetime | None
    planned_by_user_id: int | None
    cancelled_at: datetime | None
    cancelled_by_user_id: int | None
    cancellation_reason: str | None
    fulfilled_at: datetime | None
    fulfilled_by_user_id: int | None
    lines_total: int
    lines_matched: int
    lines_needs_review: int
    duplicate_groups: int
    planning_complete_lines: int
    planning_incomplete_lines: int
    total_unallocated_lines: int
    can_start_review: bool
    can_plan: bool
    created_at: datetime
    updated_at: datetime
    lines: list[SupplyRequestLineRead]

    model_config = ConfigDict(from_attributes=True)


class SupplyDebtEventRead(BaseModel):
    id: UUID
    event_type: str
    quantity_delta: Decimal
    quantity_before: Decimal
    quantity_after: Decimal
    request_id: UUID | None
    request_line_id: UUID | None
    cycle_id: UUID | None
    actor_user_id: int | None
    comment: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyDebtRead(BaseModel):
    id: UUID
    department: DepartmentRead
    product: SupplyProductRead | None
    working_name: str
    unit: SupplyUnitRead
    outstanding_quantity: Decimal
    original_quantity: Decimal
    status: SupplyDebtStatus
    version: int
    first_request_id: UUID
    latest_request_id: UUID
    first_request_line_id: UUID
    latest_request_line_id: UUID
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    cancelled_at: datetime | None
    close_comment: str | None
    cancel_comment: str | None
    cycle_count: int
    severity: SupplyDebtSeverity
    events: list[SupplyDebtEventRead]

    model_config = ConfigDict(from_attributes=True)


class SupplyDebtPage(BaseModel):
    items: list[SupplyDebtRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SupplyDashboardSummary(BaseModel):
    new_requests: int = Field(ge=0)
    mapping_required: int = Field(ge=0)
    requests_in_progress: int = Field(ge=0)
    active_debts: int = Field(ge=0)
    critical_debts: int = Field(ge=0)


class PublicSupplyDepartmentRead(BaseModel):
    id: UUID
    code: str
    name: str
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class PublicSupplyDirectionRead(BaseModel):
    id: UUID
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class PublicSupplyCycleRead(BaseModel):
    id: UUID
    direction: PublicSupplyDirectionRead
    cycle_date: date
    opens_at: datetime
    closes_at: datetime
    hard_closes_at: datetime | None
    effective_closes_at: datetime
    server_now: datetime
    seconds_until_close: int = Field(ge=0)


class PublicSupplyScheduleRead(BaseModel):
    summary: str


class PublicSupplyRequestCreate(BaseModel):
    department_id: UUID
    cycle_id: UUID | None = None
    author_name: str | None = None
    author_phone: str | None = None
    multiline_text: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("author_name")
    @classmethod
    def validate_author_name(cls, value: str | None) -> str | None:
        return _strip_optional(
            value,
            max_length=MAX_PUBLIC_AUTHOR_NAME_LENGTH,
        )

    @field_validator("author_phone")
    @classmethod
    def validate_author_phone(cls, value: str | None) -> str | None:
        return _strip_optional(
            value,
            max_length=MAX_PUBLIC_AUTHOR_PHONE_LENGTH,
        )

    @field_validator("multiline_text")
    @classmethod
    def validate_multiline_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Добавьте хотя бы одну строку заявки")
        if len(stripped) > MAX_RAW_INPUT_LENGTH:
            raise ValueError(
                "Текст заявки не может быть длиннее "
                f"{MAX_RAW_INPUT_LENGTH} символов"
            )
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if len(lines) > MAX_PUBLIC_LINE_COUNT:
            raise ValueError(
                f"В заявке может быть не больше {MAX_PUBLIC_LINE_COUNT} строк"
            )
        if any(len(line) > MAX_LINE_LENGTH for line in lines):
            raise ValueError(
                f"Строка заявки не может быть длиннее {MAX_LINE_LENGTH} символов"
            )
        return "\n".join(lines)


class PublicSupplyExpectedVersion(BaseModel):
    expected_version: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")


class PublicSupplySubmit(PublicSupplyExpectedVersion):
    confirm_unrecognized: bool = False


class PublicSupplyLinesUpdate(PublicSupplyExpectedVersion):
    multiline_text: str

    @field_validator("multiline_text")
    @classmethod
    def validate_multiline_text(cls, value: str) -> str:
        return PublicSupplyRequestCreate.validate_multiline_text(value)


class PublicSupplyLineRead(BaseModel):
    id: UUID
    raw_text: str
    parsed_name: str | None
    parsed_quantity: Decimal | None
    parsed_unit: str | None
    matched_product_name: str | None
    requested_quantity: Decimal | None
    requested_unit: str | None
    confirmed_quantity: Decimal
    fulfilled_quantity: Decimal
    unresolved_quantity: Decimal
    debt_quantity: Decimal
    match_status: SupplyLineMatchStatus
    duplicate_status: SupplyDuplicateStatus
    public_message: str


class PublicSupplyRequestRead(BaseModel):
    request_number: str
    department: PublicSupplyDepartmentRead
    direction: PublicSupplyDirectionRead
    cycle: PublicSupplyCycleRead
    status: SupplyRequestStatus
    version: int
    author_name: str | None
    lines: list[PublicSupplyLineRead]
    submitted_at: datetime | None
    expires_at: datetime


class PublicSupplyRequestCreated(PublicSupplyRequestRead):
    public_token: str


class SupplyRequestListItem(BaseModel):
    id: UUID
    public_number: str
    department: DepartmentRead
    direction: SupplyRequestDirectionRead
    cycle_id: UUID | None
    cycle: SupplyRequestCycleRead | None
    status: SupplyRequestStatus
    source_type: SupplyRequestSourceType
    version: int
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    line_count: int
    public_author_name: str | None
    lines_total: int
    lines_matched: int
    lines_needs_review: int
    duplicate_groups: int
    planning_complete_lines: int
    planning_incomplete_lines: int
    total_unallocated_lines: int
    can_start_review: bool
    can_plan: bool

    model_config = ConfigDict(from_attributes=True)
