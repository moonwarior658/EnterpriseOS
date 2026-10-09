"""Authenticated product portal; requests never contact iiko."""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Query, Response, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError
from app.db.session import get_db
from app.models.user import User
from app.product_knowledge import service, management
from app.product_knowledge.snapshot import collect
from app.product_knowledge.bootstrap import PublicationError
from app.product_knowledge.recipes import RecipeRefreshPayload, enqueue
from app.integrations.iiko.exceptions import IikoError
from app.schemas.product_knowledge import CatalogRead, ProductRead, ProductCommand, KnowledgeUpdate, StatusUpdate, VerificationUpdate, ManualAdd
from app.schemas.product_recipes import RecipeConfirmation, RecipePortalRefresh
from app.product_knowledge import recipe_portal

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
    deleted: bool = False, unverified: bool = False,
    offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return service.catalog(db, actor, q=q, status=status, mode=mode, category_id=category_id,
            department_id=department_id, price_at=price_at or today(), offset=offset, limit=limit, deleted=deleted, unverified=unverified)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


async def source_snapshot(db, actor):
    source_id = management.active_source(db, actor)
    try:
        return await collect(source_id)
    except (IikoError, PublicationError, ValueError) as error:
        raise HTTPException(503, 'Не удалось проверить справочник iiko. Повторите позже') from error


@router.post('/recipes/refresh', status_code=202)
def refresh_recipes(command: RecipeRefreshPayload, db: Db, actor: Actor):
    try:
        enqueue(db, actor, command)
        db.commit()
        return dict(message='Загрузка рецептур поставлена в очередь', accepted=True)
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except PublicationError as error:
        db.rollback()
        raise HTTPException(409, 'Проверьте источник, UUID изделий и подтверждённый контекст пилота') from error


@router.get('/iiko-candidates')
async def iiko_candidates(db: Db, actor: Actor, response: Response,
                          q: str = Query('', max_length=200), limit: int = Query(25, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        snapshot = await source_snapshot(db, actor)
        return management.candidates(db, actor, snapshot, q=q, limit=limit)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.post('', response_model=ProductRead)
async def manual_add(command: ManualAdd, db: Db, actor: Actor, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        management.manage_context(db, actor)
        snapshot = await source_snapshot(db, actor)
        product = management.add_product(db, actor, command, snapshot)
        result = service.detail(db, actor, product.id, department_id=None, price_at=today())
        db.commit()
        return result
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except Exception:
        db.rollback()
        raise


@router.get('/{product_id}', response_model=ProductRead)
def product_detail(product_id: UUID, db: Db, actor: Actor, response: Response,
                   department_id: UUID | None = None, price_at: date | None = None):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return service.detail(db, actor, product_id, department_id=department_id, price_at=price_at or today())
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.get('/{product_id}/history')
def product_history(product_id: UUID, db: Db, actor: Actor, response: Response,
                    offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return management.history(db, actor, product_id, offset=offset, limit=limit)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.get('/{product_id}/recipes')
def recipe_detail(product_id: UUID, db: Db, actor: Actor, response: Response,
                  context_key: str | None = Query(None, pattern=r'^[a-f0-9]{64}$'),
                  observation_id: UUID | None = None,
                  offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return recipe_portal.detail(db, actor, product_id, selected_context=context_key,
                                    observation_id=observation_id, offset=offset, limit=limit)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.post('/{product_id}/recipes/confirm')
def recipe_confirm(product_id: UUID, command: RecipeConfirmation, db: Db, actor: Actor, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        row = recipe_portal.confirm(db, actor, product_id, command)
        result = recipe_portal.detail(db, actor, product_id, observation_id=row.id)
        db.commit()
        return result
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except Exception:
        db.rollback()
        raise


@router.post('/{product_id}/recipes/refresh', status_code=202)
def recipe_refresh(product_id: UUID, command: RecipePortalRefresh, db: Db, actor: Actor, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        result = recipe_portal.refresh(db, actor, product_id, command)
        db.commit()
        return dict(refresh=result)
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except PublicationError as error:
        db.rollback()
        raise HTTPException(409, 'Источник или контекст рецептуры изменён. Обновите карточку') from error
    except Exception:
        db.rollback()
        raise


def execute(db, actor, product_id, operation, command):
    try:
        management.mutate(db, actor, product_id, operation, command)
        result = service.detail(db, actor, product_id, department_id=None, price_at=today())
        db.commit()
        return result
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except Exception:
        db.rollback()
        raise


@router.patch('/{product_id}/knowledge', response_model=ProductRead)
def edit_product(product_id: UUID, command: KnowledgeUpdate, db: Db, actor: Actor):
    return execute(db, actor, product_id, 'EDIT', command)


@router.patch('/{product_id}/sale-status', response_model=ProductRead)
def change_status(product_id: UUID, command: StatusUpdate, db: Db, actor: Actor):
    return execute(db, actor, product_id, 'STATUS', command)


@router.delete('/{product_id}', response_model=ProductRead)
def delete_product(product_id: UUID, command: ProductCommand, db: Db, actor: Actor):
    return execute(db, actor, product_id, 'DELETE', command)


@router.post('/{product_id}/restore', response_model=ProductRead)
def restore_product(product_id: UUID, command: ProductCommand, db: Db, actor: Actor):
    return execute(db, actor, product_id, 'RESTORE', command)


@router.patch('/{product_id}/verification', response_model=ProductRead)
def verify_product(product_id: UUID, command: VerificationUpdate, db: Db, actor: Actor):
    return execute(db, actor, product_id, 'VERIFY', command)


@router.get('/{product_id}/photo')
def read_product_photo(product_id: UUID, db: Db, actor: Actor):
    from fastapi.responses import FileResponse
    from app.core.config import settings
    from app.product_knowledge import media
    try:
        path = media.read(db, actor, product_id, settings.product_photo_upload_dir)
        return FileResponse(path, media_type='image/webp', headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'"})
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.put('/{product_id}/photo', response_model=ProductRead)
async def upload_product_photo(product_id: UUID, db: Db, actor: Actor,
    file: Annotated[UploadFile, File()], expected_version: Annotated[int, Form(ge=1)],
    reason: Annotated[str, Form(min_length=1, max_length=500)]):
    from app.core.config import settings
    from app.product_knowledge import media
    try:
        management.manage_context(db, actor)
        if not reason.strip():
            raise HTTPException(422, 'Укажите причину')
        content = await file.read(media.MAX_BYTES + 1)
        command = ProductCommand(expected_version=expected_version, reason=reason)
        media.mutate(db, actor, product_id, command, settings.product_photo_upload_dir,
                     content=content, content_type=file.content_type)
        result = service.detail(db, actor, product_id, department_id=None, price_at=today())
        db.commit()
        return result
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except Exception:
        db.rollback()
        raise
    finally:
        await file.close()


@router.delete('/{product_id}/photo', response_model=ProductRead)
def delete_product_photo(product_id: UUID, command: ProductCommand, db: Db, actor: Actor):
    from app.core.config import settings
    from app.product_knowledge import media
    try:
        media.mutate(db, actor, product_id, command, settings.product_photo_upload_dir)
        result = service.detail(db, actor, product_id, department_id=None, price_at=today())
        db.commit()
        return result
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except Exception:
        db.rollback()
        raise
