from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Enroll(StrictModel):
    product_id: UUID
    kind: Literal['RAW_MATERIAL', 'PACKAGING']
    reason: str = Field(min_length=3, max_length=1000)


class Command(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class ApprovedProduct(StrictModel):
    product_id: UUID
    role: Literal['PRIMARY', 'RESERVE']
    manufacturer: str = Field(min_length=1, max_length=240)
    restrictions: str = Field(default='', max_length=2000)
    evidence: str = Field(min_length=3, max_length=1000)


class UnitConversion(StrictModel):
    from_unit_id: UUID
    to_unit_id: UUID
    supplier_iiko_id: UUID
    container_id: UUID | None = None
    factor: Decimal = Field(gt=0, le=100000, max_digits=24, decimal_places=12)
    valid_from: date
    valid_to: date
    evidence: str = Field(min_length=3, max_length=2000)
    packaging: str = Field(min_length=1, max_length=240)

    @model_validator(mode='after')
    def dates_and_direction(self):
        if self.valid_to <= self.valid_from or self.from_unit_id == self.to_unit_id:
            raise ValueError('Проверьте период и направление пересчёта')
        return self


class Knowledge(StrictModel):
    approved_products: list[ApprovedProduct] = Field(default_factory=list, max_length=50)
    conversions: list[UnitConversion] = Field(default_factory=list, max_length=50)
    allowed_manufacturers: list[str] = Field(default_factory=list, max_length=50)
    application_limits: str = Field(default='', max_length=3000)
    package_net_quantity: Decimal | None = Field(default=None, gt=0, le=100000, max_digits=24, decimal_places=12)
    package_unit_id: UUID | None = None
    package_evidence: str = Field(default='', max_length=2000)
    purpose: str = Field(default='', max_length=2000)
    composition: str = Field(default='', max_length=2000)
    allergens: str = Field(default='', max_length=1000)
    characteristics: str = Field(default='', max_length=3000)
    receiving_requirements: str = Field(default='', max_length=3000)
    storage: str = Field(default='', max_length=2000)
    shelf_life: str = Field(default='', max_length=1000)
    manufacturer: str = Field(default='', max_length=240)
    unit_weight_kg: Decimal | None = Field(default=None, gt=0, le=100000, max_digits=18, decimal_places=9)
    weight_evidence: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def weight_requires_evidence(self):
        if self.package_net_quantity is not None and (not self.package_unit_id or len(self.package_evidence)<3):
            raise ValueError('Укажите единицу и основание нетто упаковки')
        if any(not v.strip() or len(v)>240 for v in self.allowed_manufacturers):
            raise ValueError('Проверьте разрешённых производителей')
        if len({p.product_id for p in self.approved_products}) != len(self.approved_products) or sum(p.role=='PRIMARY' for p in self.approved_products)>1:
            raise ValueError('Товары не должны повторяться; основной товар один')
        for i,a in enumerate(self.conversions):
            for b in self.conversions[i+1:]:
                if (a.from_unit_id,a.to_unit_id,a.supplier_iiko_id,a.container_id)==(b.from_unit_id,b.to_unit_id,b.supplier_iiko_id,b.container_id) and a.valid_from<b.valid_to and b.valid_from<a.valid_to:
                    raise ValueError('Периоды коэффициентов пересекаются')
        if self.unit_weight_kg is not None and len(self.weight_evidence) < 3:
            raise ValueError('Укажите основание веса условной единицы')
        return self


class SaveKnowledge(Command):
    knowledge: Knowledge


class Confirm(Command):
    owner_standard_override: bool = False
    specification_id: UUID
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    primary_product_id: UUID


class Archive(Command):
    archived: bool


class SelectReserve(Command):
    specification_id: UUID
    target_product_id: UUID
