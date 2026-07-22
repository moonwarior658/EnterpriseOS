from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AutomationTypeDefinition:
    key: str
    display_name: str
    description: str
    category: str
    is_system: bool
    is_available: bool
    supports_manual_run: bool


AUTOMATION_TYPES = (
    AutomationTypeDefinition(
        key="smoke_test",
        display_name="Проверка Automation Core",
        description=(
            "Безопасная техническая проверка полного пути запуска без "
            "уведомлений и других внешних действий."
        ),
        category="technical",
        is_system=True,
        is_available=True,
        supports_manual_run=True,
    ),
)


def _validate_catalog() -> None:
    keys = [item.key for item in AUTOMATION_TYPES]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Automation type catalog contains duplicate keys")


_validate_catalog()


def get_automation_type(key: str) -> AutomationTypeDefinition | None:
    return next((item for item in AUTOMATION_TYPES if item.key == key), None)


def require_available_automation_type(
    key: str,
) -> AutomationTypeDefinition:
    definition = get_automation_type(key)
    if definition is None or not definition.is_available:
        raise ValueError("Unsupported automation type")

    return definition


def list_available_automation_types() -> tuple[AutomationTypeDefinition, ...]:
    return tuple(
        sorted(
            (item for item in AUTOMATION_TYPES if item.is_available),
            key=lambda item: (item.category, item.display_name, item.key),
        )
    )
