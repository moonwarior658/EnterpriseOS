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


class Knowledge(StrictModel):
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
        if self.unit_weight_kg is not None and len(self.weight_evidence) < 3:
            raise ValueError('Укажите основание веса условной единицы')
        return self


class SaveKnowledge(Command):
    knowledge: Knowledge


class Confirm(Command):
    specification_id: UUID
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    primary_product_id: UUID


class Archive(Command):
    archived: bool
