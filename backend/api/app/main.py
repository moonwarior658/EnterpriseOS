from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.automation import router as automation_router
from app.api.routes.auth import router as auth_router
from app.api.routes.iiko import router as iiko_router
from app.api.routes.public_requests import router as public_requests_router
from app.api.routes.public_supply import router as public_supply_router
from app.api.routes.requests import router as requests_router
from app.api.routes.supply import router as supply_router
from app.api.routes.users import router as users_router
from app.db.session import engine


app = FastAPI(
    title="EnterpriseOS API",
    version="0.3.0",
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(public_requests_router)
app.include_router(public_supply_router)
app.include_router(requests_router)
app.include_router(supply_router)
app.include_router(automation_router)
app.include_router(iiko_router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "eos-api",
        "version": "0.3.0",
    }


@app.get("/health/database")
def database_health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable",
        ) from error

    return {
        "status": "ok",
        "database": "connected",
    }
