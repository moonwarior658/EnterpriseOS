"""Presentation ordering of safe EOS projections, before pagination."""
from decimal import Decimal

NUMERIC = {'unit_weight_kg', 'last_purchase_price', 'six_month_average', 'monthly_consumption'}
MONEY = {'last_purchase_price', 'six_month_average'}
FIELDS = {'name', 'primary_supplier', 'backup_supplier'} | NUMERIC


def ordered(items, field, descending=False):
    """Keep unknown/blocked rows after actual values in both directions."""
    def value(row):
        item = row.get(field)
        if field in ('primary_supplier', 'backup_supplier'):
            if field == 'backup_supplier' and row.get('backup_ambiguous'):
                return None
            return item['name'].casefold() if item else None
        if field in ('last_purchase_price', 'six_month_average', 'monthly_consumption'):
            if not item or item['status'] != 'READY':
                return None
            item = item.get('quantity' if field == 'monthly_consumption' else 'amount')
        if item is None:
            return None
        return Decimal(item) if field in NUMERIC else item.casefold()
    # Deterministic tie-breaker, regardless of current page or DB iteration order.
    stable = sorted(items, key=lambda row: (row['name'].casefold(), str(row['id'])))
    known = [row for row in stable if value(row) is not None]
    missing = [row for row in stable if value(row) is None]
    known.sort(key=value, reverse=descending)
    # BLOCKED and NO_DATA remain distinct, never interpreted as zero.
    missing.sort(key=lambda row: 0 if isinstance(row.get(field), dict) and row[field].get('status') == 'BLOCKED' else 1)
    return known + missing
