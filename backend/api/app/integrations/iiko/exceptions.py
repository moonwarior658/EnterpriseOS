class IikoError(Exception):
    code = "IIKO_ERROR"


class IikoConfigurationError(IikoError):
    code = "IIKO_CONFIGURATION_ERROR"


class IikoAuthenticationError(IikoError):
    code = "IIKO_AUTHENTICATION_ERROR"


class IikoAuthorizationError(IikoError):
    code = "IIKO_AUTHORIZATION_ERROR"


class IikoConnectionError(IikoError):
    code = "IIKO_CONNECTION_ERROR"


class IikoRateLimitError(IikoError):
    code = "IIKO_RATE_LIMIT_ERROR"


class IikoResponseError(IikoError):
    code = "IIKO_RESPONSE_ERROR"

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"iiko returned HTTP {status_code}")


class IikoContractError(IikoError):
    code = "IIKO_CONTRACT_ERROR"


class IikoUnsupportedOperationError(IikoError):
    code = "IIKO_UNSUPPORTED_OPERATION"
