from __future__ import annotations

import asyncio
from argparse import ArgumentParser, Namespace
from datetime import date

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.integrations.iiko.exceptions import IikoError


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Safe iiko read-only diagnostics")
    subparsers = parser.add_subparsers(dest="mode")
    subparsers.add_parser("all")
    subparsers.add_parser("warehouses")
    stock = subparsers.add_parser("stock-balances")
    stock.add_argument("--warehouse-id", required=True)
    stock.add_argument("--date", required=True, type=date.fromisoformat)
    stock.add_argument("--product-id")
    stock.add_argument("--include-zero", action="store_true")
    stock.add_argument("--include-deleted", action="store_true")
    return parser.parse_args()


async def run(args: Namespace) -> int:
    config = get_iiko_settings()
    try:
        config.validate_enabled()
    except IikoError as error:
        print(f"Configuration: ERROR ({error.args[0]})")
        return 1

    async with IikoServerClient(config) as provider:
        print(f"API type: {config.api_type}")
        try:
            await provider.authenticate()
            print("Connection: OK")
            if args.mode == "warehouses":
                records = await provider.get_warehouses()
                names = [record.dto.name for record in records[:5]]
                print(f"Warehouses received: {len(records)}")
                print(f"First warehouse names: {names}")
                return 0
            if args.mode == "stock-balances":
                records = await provider.get_stock_balances(
                    balance_date=args.date,
                    warehouse_external_ids=[args.warehouse_id],
                    product_external_ids=(
                        [args.product_id] if args.product_id else None
                    ),
                    include_zero=args.include_zero,
                    include_deleted=args.include_deleted,
                )
                positive = sum(
                    1 for record in records if record.dto.quantity > 0
                )
                zero = sum(
                    1 for record in records if record.dto.quantity == 0
                )
                negative = sum(
                    1 for record in records if record.dto.quantity < 0
                )
                print(f"Stock balances received: {len(records)}")
                print(
                    "Quantities: "
                    f"positive={positive}, zero={zero}, negative={negative}"
                )
                return 0
            readers = (
                ("Organizations", provider.get_organizations),
                ("Enterprises", provider.get_enterprises),
                ("Departments", provider.get_departments),
                ("Warehouses", provider.get_warehouses),
                ("Product groups", provider.get_product_groups),
                ("Product categories", provider.get_product_categories),
                ("Products", provider.get_products),
                ("Units", provider.get_units),
                ("Packages", provider.get_packages),
            )
            for label, reader in readers:
                try:
                    records = await reader()
                except IikoError as error:
                    print(f"{label}: unavailable ({error.code})")
                else:
                    print(f"{label} received: {len(records)}")
        except IikoError as error:
            print(f"Connection: ERROR ({error.code})")
            return 1
    return 0


def main() -> None:
    args = parse_args()
    if args.mode is None:
        args.mode = "all"
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
