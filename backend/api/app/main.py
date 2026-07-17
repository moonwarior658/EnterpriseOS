from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine


app = FastAPI(
    title="EnterpriseOS API",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "eos-api",
        "version": "0.1.0",
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
