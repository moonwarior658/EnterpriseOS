import unittest
from decimal import Decimal

from app.supply.parser import parse_supply_line


class SupplyLineParserTests(unittest.TestCase):
    def test_supported_units_and_whitespace(self) -> None:
        cases = (
            ("Картофель 10 кг", "Картофель", "10", "KG"),
            ("Молоко 5 литров", "Молоко", "5", "L"),
            ("Салфетки 3 упаковки", "Салфетки", "3", "PACK"),
            ("Перчатки 2 коробки", "Перчатки", "2", "BOX"),
            ("Яйцо 30 штук", "Яйцо", "30", "PCS"),
            ("  Сливки   33%   2.5 л  ", "Сливки 33%", "2.5", "L"),
            ("Сливки 2,5 л", "Сливки", "2.5", "L"),
            ("Салфетки обычные 3уп", "Салфетки обычные", "3", "PACK"),
            ("Молоко 10л", "Молоко", "10", "L"),
            ("Стаканы 50шт", "Стаканы", "50", "PCS"),
            (
                "Сахар-песок, белый 2 кг",
                "Сахар-песок, белый",
                "2",
                "KG",
            ),
        )
        for raw_text, name, quantity, unit_code in cases:
            with self.subTest(raw_text=raw_text):
                parsed = parse_supply_line(raw_text)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.name, name)
                self.assertEqual(parsed.quantity, Decimal(quantity))
                self.assertEqual(parsed.unit_code, unit_code)

    def test_ambiguous_or_invalid_lines_are_not_guessed(self) -> None:
        for raw_text in (
            "Молоко пять л",
            "Молоко 5",
            "Молоко л 5",
            "10 кг",
            "Молоко -1 кг",
            "Молоко 0 кг",
            "Молоко 1.2345 л",
            "Молоко 5 неизвестных",
        ):
            with self.subTest(raw_text=raw_text):
                self.assertIsNone(parse_supply_line(raw_text))

    def test_integer_only_units_reject_fractional_quantity(self) -> None:
        for suffix in ("1,5 шт", "1,5шт", "1,5 уп", "1,5уп", "1,5 кор"):
            self.assertIsNone(parse_supply_line(f"Товар {suffix}"))
        self.assertIsNotNone(parse_supply_line("Товар 1,5 кг"))
        self.assertIsNotNone(parse_supply_line("Товар 1.5 л"))

    def test_name_still_requires_separator_before_quantity(self) -> None:
        self.assertIsNone(parse_supply_line("Молоко10л"))


if __name__ == "__main__":
    unittest.main()
