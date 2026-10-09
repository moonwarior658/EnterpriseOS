"""Curated snapshot input and safe public projection (no recipes/cost/raw data)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceProduct(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=500)
    sku: str | None = Field(default=None, max_length=160)
    main_unit: UUID
    unit_weight_kg: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    deleted: bool
    source_type: str
    use_balance_for_sell: bool | None = None
    description: str | None = None


class SourceUnit(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=160)


class ConfirmedMode(StrictModel):
    iiko_product_id: UUID
    sale_mode: Literal['PORTION', 'WEIGHT']
    evidence: str = Field(min_length=1, max_length=500)


class ConfirmedPrice(StrictModel):
    iiko_product_id: UUID
    department_id: UUID
    valid_from: date
    valid_to: date
    amount: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=20, decimal_places=6)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    price_unit: str = Field(min_length=1, max_length=160)
    evidence: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def interval(self):
        if self.valid_to <= self.valid_from:
            raise ValueError('INVALID_PRICE_INTERVAL')
        return self


class SourceSnapshot(StrictModel):
    source_id: str = Field(min_length=1, max_length=64)
    observed_at: datetime
    evidence: str = Field(min_length=1, max_length=500)
    complete: bool
    products: list[SourceProduct]
    units: list[SourceUnit]
    sale_modes: list[ConfirmedMode] = Field(default_factory=list)
    prices: list[ConfirmedPrice] = Field(default_factory=list)

    @field_validator('observed_at')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError('OBSERVATION_TIMEZONE_REQUIRED')
        return value

    @model_validator(mode='after')
    def unique_modes(self):
        if len({x.iiko_product_id for x in self.sale_modes}) != len(self.sale_modes):
            raise ValueError('SALE_MODE_CONFLICT')
        ids = {x.id for x in self.products}
        if any(x.iiko_product_id not in ids for x in [*self.sale_modes, *self.prices]):
            raise ValueError('CONFIRMATION_PRODUCT_MISSING')
        return self


class PriceRead(BaseModel):
    department_id: UUID
    department_name: str
    amount: Decimal
    currency: str
    price_unit: str
    valid_from: date
    valid_to: date
    observed_at: datetime


class PriceHealthRead(BaseModel):
    department_id: UUID
    last_success_at: datetime | None
    stale: bool
    update_failed: bool


class ProductRead(BaseModel):
    recipe_access: bool = False
    id: UUID
    name: str
    sku: str | None
    unit_name: str
    unit_weight_kg: Decimal | None
    sale_mode: str
    sale_status: str
    category_id: UUID | None
    category_name: str | None
    description: str | None
    observed_at: datetime
    source_deleted: bool
    price: PriceRead | None
    prices: list[PriceRead]
    price_health: list[PriceHealthRead] = Field(default_factory=list)
    price_conflict_points: list[UUID] = Field(default_factory=list)
    description_source: Literal['EOS', 'iiko']
    photo: str | None = None
    characteristics: str | None = None
    composition: str | None = None
    allergens: str | None = None
    storage: str | None = None
    training: str | None = None
    version: int
    deleted_at: datetime | None = None
    verified_at: datetime | None = None
    verified_by_employee_id: UUID | None = None
    verified_by_name: str | None = None
    eligible_for_production: bool
    allowed_actions: list[str] = Field(default_factory=list)


class OptionRead(BaseModel):
    id: UUID
    name: str


class CatalogRead(BaseModel):
    items: list[ProductRead]
    total: int
    offset: int
    limit: int
    points: list[OptionRead]
    categories: list[OptionRead]
    observed_at: datetime | None
    verified_count: int
    active_count: int
    allowed_actions: list[str] = Field(default_factory=list)


class ProductCommand(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip():
            raise ValueError('Укажите причину')
        return value.strip()


class KnowledgeUpdate(ProductCommand):
    name: str = Field(min_length=1, max_length=500)
    category_id: UUID | None = None
    description: str | None = Field(default=None, max_length=10000)
    characteristics: str | None = Field(default=None, max_length=10000)
    composition: str | None = Field(default=None, max_length=10000)
    allergens: str | None = Field(default=None, max_length=10000)
    storage: str | None = Field(default=None, max_length=10000)
    training: str | None = Field(default=None, max_length=10000)

    @field_validator('name')
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError('Укажите название')
        return value.strip()


class StatusUpdate(ProductCommand):
    sale_status: Literal['ON_SALE', 'OFF_SALE']


class VerificationUpdate(ProductCommand):
    verified: bool


class ManualAdd(StrictModel):
    source_id: str = Field(min_length=1, max_length=64)
    iiko_product_id: UUID
    confirmation_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    sale_status: Literal['ON_SALE', 'OFF_SALE']
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip():
            raise ValueError('Укажите причину')
        return value.strip()
