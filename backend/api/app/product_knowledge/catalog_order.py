"""Ordering of existing safe catalog projections, with no new cost calculation."""
from decimal import Decimal

FIELDS = {'name', 'unit_weight_kg', 'sale_mode', 'sale_status', 'price', 'cost'}


def ordered(items, field, descending=False):
    def value(row):
        if field == 'price':
            price = row.get('price')
            if not price or str(price['department_id']) in {str(p) for p in row.get('price_conflict_points', [])}:
                return None
            return Decimal(price['amount'])
        if field == 'cost':
            cost = row.get('cost')
            return Decimal(cost['amount']) if cost and cost['status'] == 'VERIFIED' and cost['amount'] is not None else None
        if field == 'unit_weight_kg':
            return Decimal(row[field]) if row.get(field) is not None else None
        if field == 'sale_mode':
            return {'PORTION': 'порционный', 'WEIGHT': 'весовой'}.get(row[field])
        if field == 'sale_status':
            return 'удалено из eos' if row.get('deleted_at') else {'ON_SALE': 'в продаже', 'OFF_SALE': 'выведено из продажи'}[row[field]]
        return row[field].casefold()
    stable = sorted(items, key=lambda r: (r['name'].casefold(), str(r['id'])))
    known = [r for r in stable if value(r) is not None]
    missing = [r for r in stable if value(r) is None]
    known.sort(key=value, reverse=descending)
    return known + missing
