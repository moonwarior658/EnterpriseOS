class AutomationProviderError(Exception):
    """Base error for automation provider communication."""


class ProviderAuthenticationError(AutomationProviderError):
    """The provider rejected the service credentials."""


class ProviderTimeoutError(AutomationProviderError):
    """The provider did not respond within the configured timeout."""


class ProviderUnavailableError(AutomationProviderError):
    """The provider could not be reached."""


class ProviderRejectedError(AutomationProviderError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Automation provider rejected the request with HTTP {status_code}"
        )
