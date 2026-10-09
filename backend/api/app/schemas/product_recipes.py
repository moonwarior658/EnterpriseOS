"""Human portal commands, never raw iiko/automation payloads."""
from datetime import date
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecipeConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    observation_id: UUID
    manifest_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    office_evidence: str = Field(min_length=10, max_length=1000)

    @field_validator('office_evidence')
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 10:
            raise ValueError('Укажите результат независимой сверки с iikoOffice')
        return value.strip()


class RecipePortalRefresh(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    effective_on: date
    request_id: UUID
