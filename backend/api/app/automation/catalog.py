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
        key="products.sync_iiko_prices", display_name="Обновить цены продукции",
        description="Обновляет обычные цены уже включённой продукции на подтверждённых точках.",
        category="products", is_system=True, is_available=True, supports_manual_run=False,
    ),
    AutomationTypeDefinition(
        key="sales.finalize_reports", display_name="Зафиксировать отчёты продаж",
        description="Сохраняет закрытые недели и месяцы после полной загрузки данных.",
        category="sales", is_system=True, is_available=True, supports_manual_run=True,
    ),
    AutomationTypeDefinition(
        key="sales.sync_iiko", display_name="Обновить данные продаж",
        description="Обновляет первичные факты розничных продаж из iiko.",
        category="sales", is_system=True, is_available=True, supports_manual_run=True,
    ),
    AutomationTypeDefinition(
        key="supply.ensure_request_cycle",
        display_name="Открыть цикл заявок снабжения",
        description=(
            "Создаёт цикл выбранного направления в настроенные дни "
            "недели. Повторный запуск не создаёт дубль."
        ),
        category="supply",
        is_system=False,
        is_available=True,
        supports_manual_run=True,
    ),
    AutomationTypeDefinition(
        key="supply.close_expired_request_cycles",
        display_name="Закрыть истёкшие циклы снабжения",
        description=(
            "Закрывает циклы текущей компании после окончательного "
            "времени приёма заявок."
        ),
        category="supply",
        is_system=False,
        is_available=True,
        supports_manual_run=True,
    ),
    AutomationTypeDefinition(
        key="supply.supplier_order_email_send",
        display_name="Отправить заказ поставщику",
        description="Передаёт подготовленное письмо заказа настроенному почтовому transport.",
        category="supply",
        is_system=True,
        is_available=True,
        supports_manual_run=False,
    ),
    AutomationTypeDefinition(
        key="employee.sync_iiko_shifts",
        display_name="Синхронизировать личные смены iiko",
        description=(
            "Получает явки iiko за ограниченный период и идемпотентно "
            "обновляет личные смены связанных сотрудников."
        ),
        category="employees",
        is_system=False,
        is_available=True,
        supports_manual_run=True,
    ),
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
