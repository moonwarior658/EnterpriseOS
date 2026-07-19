from functools import lru_cache

from pydantic import AnyHttpUrl, PositiveFloat, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class N8nSettings(BaseSettings):
    dispatch_webhook_url: AnyHttpUrl
    healthcheck_url: AnyHttpUrl
    service_token: SecretStr
    timeout_seconds: PositiveFloat = 10.0

    model_config = SettingsConfigDict(
        env_prefix="N8N_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_n8n_settings() -> N8nSettings:
    return N8nSettings()
