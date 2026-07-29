from functools import lru_cache

from pydantic import AnyHttpUrl, PositiveFloat, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.integrations.iiko.exceptions import IikoConfigurationError


class IikoSettings(BaseSettings):
    enabled: bool = False
    base_url: AnyHttpUrl | None = None
    api_type: str = "iiko_server"
    login: SecretStr | None = None
    password: SecretStr | None = None
    request_timeout_seconds: PositiveFloat = 45.0
    connect_timeout_seconds: PositiveFloat = 10.0
    verify_tls: bool = True
    max_safe_retries: int = 1
    sync_page_size: PositiveInt = 500

    model_config = SettingsConfigDict(
        env_prefix="IIKO_",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def configured(self) -> bool:
        return bool(
            self.base_url
            and self.login
            and self.login.get_secret_value().strip()
            and self.password
            and self.password.get_secret_value()
        )

    def validate_enabled(self) -> None:
        if not self.enabled:
            raise IikoConfigurationError("IIKO_DISABLED")
        if not self.configured:
            raise IikoConfigurationError("IIKO_NOT_CONFIGURED")
        if self.api_type != "iiko_server":
            raise IikoConfigurationError("IIKO_API_TYPE_UNSUPPORTED")
        if self.max_safe_retries < 0 or self.max_safe_retries > 3:
            raise IikoConfigurationError("IIKO_RETRY_LIMIT_INVALID")


@lru_cache
def get_iiko_settings() -> IikoSettings:
    return IikoSettings()
