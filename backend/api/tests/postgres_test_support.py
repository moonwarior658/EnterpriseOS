from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url


EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


def reset_disposable_postgres_schema(engine: Engine) -> None:
    """Reset only the explicitly guarded local PostgreSQL test database."""
    url = make_url(str(engine.url))
    if (
        not url.drivername.startswith("postgresql")
        or url.host not in ALLOWED_HOSTS
        or url.database != EXPECTED_DATABASE_NAME
    ):
        raise RuntimeError(
            "PostgreSQL test reset accepts only local eos_supply_migration_test"
        )
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
