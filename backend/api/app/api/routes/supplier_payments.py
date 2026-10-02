from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_supply_reader, get_payment_writer
from app.core.authorization import Capability, authorize
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_payment import (
    SupplySupplierPaymentCreate,
    SupplySupplierPaymentPage,
    SupplySupplierPaymentRead,
    SupplySupplierPaymentStatus,
    SupplySupplierPaymentType,
    SupplySupplierPaymentUpdate,
    SupplySupplierPaymentReason,
)
from app.supply.supplier_payments import (
    SupplierPaymentConflictError,
    SupplierPaymentLinkError,
    SupplierPaymentNotFoundError,
    SupplierPaymentStateError,
    SupplierPaymentValidationError,
    available_orders,
    attach_payment_photo,
    payment_photo,
    cancel_payment,
    create_payment,
    list_payments,
    read_payment,
    record_payment,
    update_payment,
)


router = APIRouter(prefix="/supply/supplier-payments", tags=["supply"])


def _error(error: Exception) -> HTTPException:
    if isinstance(error, SupplierPaymentNotFoundError):
        return HTTPException(status_code=404, detail="Оплата поставщику не найдена")
    if isinstance(error, SupplierPaymentConflictError):
        return HTTPException(status_code=409, detail="Платёжное поручение уже зарегистрировано")
    if isinstance(error, SupplierPaymentLinkError):
        return HTTPException(
            status_code=409,
            detail="Документ или заказ не соответствует поставщику",
        )
    if isinstance(error, SupplierPaymentValidationError):
        detail = "Сумма превышает остаток по заказу" if str(error) == "Сумма превышает остаток по заказу" else "Проверьте реквизиты и связи оплаты"
        return HTTPException(status_code=409, detail=detail)
    if isinstance(error, SupplierPaymentStateError) and str(error) in {"Заказ недоступен для оплаты", "Заказ уже оплачен"}:
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=409, detail="Зафиксированную оплату изменить нельзя")


@router.get("", response_model=SupplySupplierPaymentPage)
def read_payments(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
    supplier_id: UUID | None = None,
    payment_status: Annotated[SupplySupplierPaymentStatus | None, Query(alias="status")] = None,
    payment_type: SupplySupplierPaymentType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_order_number: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplySupplierPaymentPage:
    items, total = list_payments(
        db,
        tenant_id=admin.tenant_id,
        supplier_id=supplier_id,
        status=payment_status.value if payment_status else None,
        payment_type=payment_type.value if payment_type else None,
        date_from=date_from,
        date_to=date_to,
        payment_order_number=payment_order_number,
        limit=limit,
        offset=offset,
    )
    return SupplySupplierPaymentPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/available-orders")
def list_available_payment_orders(supplier_id: UUID, db: Annotated[Session, Depends(get_db)],
                                  admin: Annotated[User, Depends(get_payment_writer)]):
    return available_orders(db, tenant_id=admin.tenant_id, supplier_id=supplier_id)


@router.get("/{payment_id}", response_model=SupplySupplierPaymentRead)
def read_supplier_payment(
    payment_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
) -> SupplySupplierPaymentRead:
    try:
        return read_payment(db, payment_id, tenant_id=admin.tenant_id)
    except SupplierPaymentNotFoundError as error:
        raise _error(error) from error


@router.post("", response_model=SupplySupplierPaymentRead, status_code=status.HTTP_201_CREATED)
def create_supplier_payment(
    payload: SupplySupplierPaymentCreate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_payment_writer)],
) -> SupplySupplierPaymentRead:
    try:
        context = authorize(db, admin, Capability.PAYMENT_WRITE, write=True)
        return create_payment(db, payload, tenant_id=admin.tenant_id, user_id=admin.id,
                              audit_context=context, actor_user=admin)
    except (SupplierPaymentConflictError, SupplierPaymentLinkError, SupplierPaymentValidationError, SupplierPaymentStateError) as error:
        raise _error(error) from error


@router.patch("/{payment_id}", response_model=SupplySupplierPaymentRead)
def patch_supplier_payment(
    payment_id: UUID, payload: SupplySupplierPaymentUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_payment_writer)],
) -> SupplySupplierPaymentRead:
    try:
        context = authorize(db, admin, Capability.PAYMENT_WRITE, write=True)
        return update_payment(db, payment_id, payload, tenant_id=admin.tenant_id,
                              audit_context=context, actor_user=admin)
    except (
        SupplierPaymentNotFoundError, SupplierPaymentStateError,
        SupplierPaymentConflictError, SupplierPaymentLinkError,
        SupplierPaymentValidationError,
    ) as error:
        raise _error(error) from error


@router.post("/{payment_id}/record", response_model=SupplySupplierPaymentRead)
def record_supplier_payment(
    payment_id: UUID, payload: SupplySupplierPaymentReason,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_payment_writer)],
) -> SupplySupplierPaymentRead:
    try:
        context = authorize(db, admin, Capability.PAYMENT_WRITE, write=True)
        return record_payment(
            db, payment_id, tenant_id=admin.tenant_id, user_id=admin.id,
            audit_context=context, actor_user=admin, reason=payload.reason,
        )
    except (
        SupplierPaymentNotFoundError, SupplierPaymentStateError,
        SupplierPaymentConflictError, SupplierPaymentLinkError,
        SupplierPaymentValidationError,
    ) as error:
        raise _error(error) from error


@router.post("/{payment_id}/cancel", response_model=SupplySupplierPaymentRead)
def cancel_supplier_payment(
    payment_id: UUID, payload: SupplySupplierPaymentReason,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_payment_writer)],
) -> SupplySupplierPaymentRead:
    try:
        context = authorize(db, admin, Capability.PAYMENT_WRITE, write=True)
        return cancel_payment(db, payment_id, tenant_id=admin.tenant_id,
                              audit_context=context, actor_user=admin, reason=payload.reason)
    except (SupplierPaymentNotFoundError, SupplierPaymentStateError) as error:
        raise _error(error) from error


@router.post("/{payment_id}/photo", response_model=SupplySupplierPaymentRead)
async def upload_supplier_payment_photo(
    payment_id: UUID, file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_payment_writer)],
) -> SupplySupplierPaymentRead:
    allowed = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}
    content = await file.read(10 * 1024 * 1024 + 1)
    await file.close()
    if file.content_type not in allowed or not content.startswith(allowed[file.content_type]) or not content:
        raise HTTPException(status_code=422, detail="Допустимы фотографии JPEG, PNG и WebP")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Фото не должно превышать 10 МБ")
    if file.content_type == "image/webp" and content[8:12] != b"WEBP":
        raise HTTPException(status_code=422, detail="Некорректный файл WebP")
    try:
        context = authorize(db, admin, Capability.PAYMENT_WRITE, write=True)
        return attach_payment_photo(
            db, payment_id, tenant_id=admin.tenant_id,
            filename=file.filename or "photo", content_type=file.content_type,
            content=content, upload_dir=Path(settings.supplier_document_upload_dir) / "payments",
            audit_context=context, actor_user=admin,
        )
    except (SupplierPaymentNotFoundError, SupplierPaymentStateError) as error:
        raise _error(error) from error


@router.get("/{payment_id}/photo")
def read_supplier_payment_photo(
    payment_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
) -> FileResponse:
    try:
        filename, content_type = payment_photo(db, payment_id, tenant_id=admin.tenant_id)
    except SupplierPaymentNotFoundError as error:
        raise _error(error) from error
    root = (Path(settings.supplier_document_upload_dir) / "payments").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Фото оплаты не найдено")
    return FileResponse(path, media_type=content_type)
