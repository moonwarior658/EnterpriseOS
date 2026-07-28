"""EnterpriseOS Automation Core package with lazy public exports."""

from typing import Any


__all__ = [
    "AutomationProvider",
    "CommandAcceptance",
    "DeliveryResult",
    "DeliveryStatus",
    "OutboxWorker",
    "SqlAlchemyOutboxStore",
]


def __getattr__(name: str) -> Any:
    if name in {"AutomationProvider", "CommandAcceptance"}:
        from app.automation import providers

        return getattr(providers, name)
    if name in {
        "DeliveryResult",
        "DeliveryStatus",
        "OutboxWorker",
        "SqlAlchemyOutboxStore",
    }:
        from app.automation import outbox

        return getattr(outbox, name)
    raise AttributeError(name)
