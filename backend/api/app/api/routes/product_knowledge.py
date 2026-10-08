"""Authenticated product portal; requests never contact iiko."""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError
from app.db.session import get_db
from app.models.user import User
from app.product_knowledge import service
from app.schemas.product_knowledge import CatalogRead, ProductRead

router = APIRouter(prefix='/products', tags=['product knowledge'])
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]


def today():
    return datetime.now(ZoneInfo('Asia/Yekaterinburg')).date()


@router.get('', response_model=CatalogRead)
def list_products(db: Db, actor: Actor, response: Response,
    q: str = Query('', max_length=200), status: Literal['ON_SALE','OFF_SALE'] | None = None,
    mode: Literal['UNKNOWN','PORTION','WEIGHT'] | None = None, category_id: UUID | None = None,
    department_id: UUID | None = None, price_at: date | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return service.catalog(db, actor, q=q, status=status, mode=mode, category_id=category_id,
            department_id=department_id, price_at=price_at or today(), offset=offset, limit=limit)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.get('/{product_id}', response_model=ProductRead)
def product_detail(product_id: UUID, db: Db, actor: Actor, response: Response,
                   department_id: UUID | None = None, price_at: date | None = None):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return service.detail(db, actor, product_id, department_id=department_id, price_at=price_at or today())
    except ActionContextError as error:
        raise action_context_http_error(error) from error
