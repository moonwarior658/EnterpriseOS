import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ParsedSupplyLine:
    name: str
    quantity: Decimal
    unit_code: str


_UNIT_FORMS = {
    "кг": ("KG", True),
    "килограмм": ("KG", True),
    "килограмма": ("KG", True),
    "килограммов": ("KG", True),
    "л": ("L", True),
    "литр": ("L", True),
    "литра": ("L", True),
    "литров": ("L", True),
    "шт": ("PCS", False),
    "штука": ("PCS", False),
    "штуки": ("PCS", False),
    "штук": ("PCS", False),
    "уп": ("PACK", False),
    "упаковка": ("PACK", False),
    "упаковки": ("PACK", False),
    "упаковок": ("PACK", False),
    "кор": ("BOX", False),
    "короб": ("BOX", False),
    "коробка": ("BOX", False),
    "коробки": ("BOX", False),
    "коробок": ("BOX", False),
}
_UNIT_PATTERN = "|".join(
    sorted((re.escape(form) for form in _UNIT_FORMS), key=len, reverse=True)
)
_LINE_PATTERN = re.compile(
    rf"^(?P<name>.+?)\s+"
    rf"(?P<quantity>\d+(?:[.,]\d{{1,3}})?)\s*"
    rf"(?P<unit>{_UNIT_PATTERN})$",
    re.IGNORECASE,
)


def parse_supply_line(raw_text: str) -> ParsedSupplyLine | None:
    match = _LINE_PATTERN.fullmatch(raw_text.strip())
    if match is None:
        return None

    name = " ".join(match.group("name").split())
    if not name:
        return None

    try:
        quantity = Decimal(match.group("quantity").replace(",", "."))
    except InvalidOperation:
        return None
    if quantity <= 0:
        return None

    unit_code, allows_fraction = _UNIT_FORMS[match.group("unit").casefold()]
    if not allows_fraction and quantity != quantity.to_integral_value():
        return None

    return ParsedSupplyLine(
        name=name,
        quantity=quantity,
        unit_code=unit_code,
    )


def supply_line_product_name(raw_text: str) -> str:
    parsed = parse_supply_line(raw_text)
    if parsed is not None:
        return parsed.name
    match = _LINE_PATTERN.fullmatch(raw_text.strip())
    if match is not None:
        return " ".join(match.group("name").split())
    return " ".join(raw_text.split())
