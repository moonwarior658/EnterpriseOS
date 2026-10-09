"""Read-only v2/price contract. No product-card price fallback."""
import json
from datetime import date
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, StrictBool, model_validator
from app.integrations.iiko.exceptions import IikoAuthenticationError, IikoAuthorizationError, IikoResponseError, IikoContractError


class CategoryInclusion(BaseModel):
    categoryId: UUID
    include: StrictBool


class CategoryPrice(BaseModel):
    categoryId: UUID
    price: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=20, decimal_places=6)


class PriceInterval(BaseModel):
    model_config = ConfigDict(extra='ignore')
    dateFrom: date
    dateTo: date
    price: Decimal | None = Field(ge=0, allow_inf_nan=False, max_digits=20, decimal_places=6)
    included: StrictBool
    documentId: UUID
    schedule: dict | None
    includeForCategories: list[CategoryInclusion]
    pricesForCategories: list[CategoryPrice]

    @model_validator(mode='after')
    def interval(self):
        if self.dateTo <= self.dateFrom:
            raise ValueError('INVALID_PRICE_INTERVAL')
        return self


class PriceContext(BaseModel):
    departmentId: UUID
    productId: UUID
    productSizeId: UUID | None
    prices: list[PriceInterval]


class PriceResponse(BaseModel):
    revision: int = Field(ge=0)
    contexts: list[PriceContext]


async def read_prices(client, *, date_from, date_to, department_id):
    if date_to <= date_from or (date_to - date_from).days > 93:
        raise IikoContractError('PRICE_QUERY_WINDOW_INVALID')
    await client.authenticate()
    params = dict(dateFrom=date_from.isoformat(), dateTo=date_to.isoformat(),
                  departmentId=str(department_id), includeOutOfSale='true')
    response = await client._raw_request('GET', 'api/v2/price', params=params)
    if response.status_code == 401:
        client._token = None
        await client.authenticate()
        response = await client._raw_request('GET', 'api/v2/price', params=params)
    if response.status_code == 401:
        raise IikoAuthenticationError('IIKO_TOKEN_REJECTED')
    if response.status_code == 403:
        raise IikoAuthorizationError('IIKO_ACCESS_DENIED')
    if not response.is_success:
        raise IikoResponseError(response.status_code)
    if len(response.content) > 16 * 1024 * 1024:
        raise IikoContractError('PRICE_RESPONSE_TOO_LARGE')
    try:
        body = json.loads(response.text, parse_float=Decimal)
        if not isinstance(body, dict) or body.get('result') != 'SUCCESS' or body.get('errors') != []:
            raise ValueError()
        result = PriceResponse(revision=body['revision'], contexts=body['response'])
        if any(c.departmentId != department_id for c in result.contexts):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError):
        raise IikoContractError('PRICE_CONTRACT_INVALID') from None
