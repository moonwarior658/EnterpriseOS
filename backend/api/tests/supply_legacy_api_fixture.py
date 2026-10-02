"""Keep pre-RBAC Supply lifecycle fixtures focused on domain behavior.

Role enforcement is exercised separately in test_supply_rbac.py. These older
fixtures often omit Employee tables and intentionally substitute an admin User.
"""
from fastapi import HTTPException

from app.api.dependencies import (
    get_payment_writer, get_supplier_editor, get_supply_operator,
    get_supply_reader, get_supply_request_viewer,
    get_supply_technical_admin,
)


def install_supply_admin_overrides(app, user_provider):
    def require_fixture_admin():
        try:
            user = user_provider()
        except KeyError:
            raise HTTPException(status_code=401, detail="Not authenticated") from None
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Administrator access required")
        return user

    for dependency in (
        get_payment_writer, get_supplier_editor, get_supply_operator,
        get_supply_reader, get_supply_request_viewer,
        get_supply_technical_admin,
    ):
        app.dependency_overrides[dependency] = require_fixture_admin
