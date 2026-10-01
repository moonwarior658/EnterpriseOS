"""Retired anonymous repair creation endpoint.

Historical public repairs remain readable through the authorized repair API.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix='/public/requests', tags=['public-requests'])


@router.post('')
def create_public_request():
    raise HTTPException(status_code=403, detail='Для создания ремонта войдите в EnterpriseOS')
