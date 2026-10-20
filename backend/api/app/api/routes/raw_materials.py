"""Authenticated local knowledge and saved purchase facts; manual Core commands."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.raw_materials import service, purchase_refresh
from app.schemas.raw_materials import Enroll, SaveKnowledge, Confirm, Archive, Command, SelectReserve

router = APIRouter(prefix='/raw-materials', tags=['raw materials'])
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]


def execute(db, response, operation, *, write=False):
    response.headers['Cache-Control'] = 'no-store'
    try:
        result = operation()
        if write:
            db.commit()
        return result
    except ActionContextError as error:
        db.rollback()
        raise action_context_http_error(error) from error
    except HTTPException:
        db.rollback()
        raise


@router.get('')
def catalog(db: Db, actor: Actor, response: Response,
    q: str = Query('', max_length=200), kind: Literal['RAW_MATERIAL','PACKAGING'] | None = None,
    archived: bool = False, category_id: UUID | None = None, supplier_id: UUID | None = None,
    without_supplier: bool = False, state: Literal['CONFIRMED','UNCONFIRMED'] | None = None,
    sort: Literal['name'] = 'name', offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return execute(db, response, lambda: service.catalog(db, actor, q=q, kind=kind, archived=archived,
        category_id=category_id, supplier_id=supplier_id, without_supplier=without_supplier, state=state, offset=offset, limit=limit))


@router.get('/candidates')
def candidates(db: Db, actor: Actor, response: Response, q: str = Query('', max_length=200), offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return execute(db, response, lambda: service.candidates(db, actor, q=q, offset=offset, limit=limit))


@router.post('', status_code=201)
def enroll(command: Enroll, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.enroll(db, actor, command), write=True)


@router.get('/{product_id}')
def detail(product_id: UUID, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.detail(db, actor, product_id))


@router.patch('/{product_id}/knowledge')
def save(product_id: UUID, command: SaveKnowledge, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.save(db, actor, product_id, command), write=True)


@router.post('/{product_id}/knowledge/confirm')
def confirm(product_id: UUID, command: Confirm, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.confirm(db, actor, product_id, command), write=True)


@router.patch('/{product_id}/archive')
def archive(product_id: UUID, command: Archive, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.archive(db, actor, product_id, command), write=True)


@router.get('/{product_id}/history')
def history(product_id: UUID, db: Db, actor: Actor, response: Response, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return execute(db, response, lambda: service.history(db, actor, product_id, offset=offset, limit=limit))


@router.put('/{product_id}/photo')
async def upload_photo(product_id: UUID, db: Db, actor: Actor, response: Response,
    expected_version: Annotated[int, Form(ge=1)], reason: Annotated[str, Form(min_length=3, max_length=1000)], file: Annotated[UploadFile, File()]):
    # Authorize and bind before processing an untrusted upload.
    try:
        service.editable(db, actor, product_id, Command(expected_version=expected_version, reason=reason))
    except ActionContextError as error:
        raise action_context_http_error(error) from error
    content = await file.read(service.media.MAX_BYTES + 1)
    return execute(db, response, lambda: service.photo(db, actor, product_id,
        Command(expected_version=expected_version, reason=reason), settings.raw_material_photo_upload_dir,
        content=content, content_type=file.content_type), write=True)


@router.delete('/{product_id}/photo')
def delete_photo(product_id: UUID, command: Command, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.photo(db, actor, product_id, command, settings.raw_material_photo_upload_dir), write=True)


@router.get('/{product_id}/photo')
def read_photo(product_id: UUID, db: Db, actor: Actor, photo_hash: str | None = Query(None, pattern=r'^[a-f0-9]{64}$')):
    try:
        path = service.read_photo(db, actor, product_id, settings.raw_material_photo_upload_dir, photo_hash)
        return FileResponse(path, media_type='image/webp', headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'})
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.post('/{product_id}/metrics/refresh', status_code=202)
def refresh_purchase(product_id: UUID, command: purchase_refresh.RefreshCommand, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: purchase_refresh.refresh(db, actor, product_id, command), write=True)


@router.get('/{product_id}/metrics')
def purchase_history(product_id: UUID, db: Db, actor: Actor, response: Response, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return execute(db, response, lambda: purchase_refresh.history(db, actor, product_id, offset=offset, limit=limit))


@router.get('/{product_id}/metrics/{snapshot_id}/sources')
def purchase_sources(product_id: UUID, snapshot_id: UUID, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: purchase_refresh.sources(db, actor, product_id, snapshot_id))


@router.get('/{product_id}/usage')
def usage_history(product_id: UUID, db: Db, actor: Actor, response: Response, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return execute(db, response, lambda: purchase_refresh.usage_history(db, actor, product_id, offset=offset, limit=limit))


@router.post('/{product_id}/reserve-selection')
def select_reserve(product_id: UUID, command: SelectReserve, db: Db, actor: Actor, response: Response):
    return execute(db, response, lambda: service.select_reserve(db, actor, product_id, command), write=True)


@router.get('/{product_id}/standards/options')
def standard_options(product_id: UUID, db: Db, actor: Actor, response: Response, q: str = Query('', max_length=200)):
    return execute(db, response, lambda: service.standards.options(db, actor, product_id, q=q))
