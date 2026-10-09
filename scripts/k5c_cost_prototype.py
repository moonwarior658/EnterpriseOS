"""Offline research calculator for K5C evidence; never publishes monetary data.

Experimental policy: expand ASSEMBLE trees using amountIn/assembledAmount and
value terminal ingredients from balance/stores. This is an EOS calculation,
not a response containing an iiko-calculated SSN. No estimated-price fallback.
"""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path


class Unavailable(ValueError):
    pass


def decimal(value):
    if value is None or isinstance(value, (bool, float)):
        raise Unavailable('INVALID_DECIMAL')
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise Unavailable('INVALID_DECIMAL') from None
    if not result.is_finite():
        raise Unavailable('INVALID_DECIMAL')
    return result


def calculate(root, *, at, store_key=None, positive_only=True):
    """Diagnostic values only. Missing required input makes the whole result NULL.

    All-store positive pooling is an empirical hypothesis, never an automatic
    warehouse resolver. Negative-only, missing, zero quantity remain unknown.
    """
    charts = {}
    for chart in root['charts']:
        start = date.fromisoformat(chart['dateFrom'])
        end = date.fromisoformat(chart['dateTo']) if chart.get('dateTo') else None
        if start <= at and (end is None or at < end):
            charts.setdefault(chart['root_key'], []).append(chart)
    references = {p['key']: p for p in root['references']}
    rows = [b for group in root['balances'] for b in group['rows']
        if store_key is None or b['store_key'] == store_key]
    warnings = {'EXPERIMENTAL_NESTED_POLICY', 'UNVERIFIED_OFFICE_METHOD', 'CURRENCY_VAT_UNCONFIRMED'}
    warnings.add('ALL_STORES_POOL' if store_key is None else 'STORE_REQUIRES_CONTEXT_CONFIRMATION')
    components = []

    def visit(product, path):
        if product in path:
            raise Unavailable('RECIPE_CYCLE:'+product)
        if product not in references:
            raise Unavailable('MISSING_REFERENCE:'+product)
        matches = charts.get(product, [])
        if len(matches) > 1:
            raise Unavailable('AMBIGUOUS_RECIPE:'+product)
        if matches and matches[0]['writeoff'] not in ('ASSEMBLE', 'DIRECT'):
            raise Unavailable('UNKNOWN_NESTED_POLICY:'+product)
        if matches and (product == root['key'] or matches[0]['writeoff'] == 'ASSEMBLE'):
            chart = matches[0]
            basis = decimal(chart['assembledAmount'])
            if basis <= 0 or not chart['items']:
                raise Unavailable('INVALID_RECIPE_BASIS:'+product)
            total = Decimal(0)
            for item in chart['items']:
                spec = item.get('storeSpecification')
                if item.get('size_specified') or spec not in (None, {'departments': [], 'inverse': True}):
                    raise Unavailable('UNRESOLVED_LINE_SCOPE:'+item['product_key'])
                norm = decimal(item['amountIn'])
                if norm < 0:
                    raise Unavailable('INVALID_NORM:'+item['product_key'])
                if norm == 0:
                    continue  # Explicit source norm, never a monetary fallback.
                total += norm * visit(item['product_key'], path + (product,))
            return total / basis
        if references[product].get('type') in ('PREPARED', 'DISH') and not matches:
            raise Unavailable('MISSING_NESTED_RECIPE:'+product)
        selected = [b for b in rows if b['product_key'] == product]
        identities = [(b['store_key'], b['product_key']) for b in selected]
        if len(set(identities)) != len(identities):
            raise Unavailable('DUPLICATE_BALANCE:'+product)
        if any(decimal(b['amount']) <= 0 for b in selected):
            warnings.add('NONPOSITIVE_STOCK_PRESENT')
        if positive_only:
            selected = [b for b in selected if decimal(b['amount']) > 0]
        amount = sum((decimal(b['amount']) for b in selected), Decimal(0))
        money = sum((decimal(b['sum']) for b in selected), Decimal(0))
        if not selected or amount == 0:
            raise Unavailable('MISSING_USABLE_BALANCE:'+product)
        if money < 0 and amount > 0:
            raise Unavailable('NEGATIVE_VALUATION:'+product)
        cost = money / amount
        components.append(dict(product_key=product, quantity=str(amount), sum=str(money),
            unit_cost=str(cost), stores=sorted(b['store_key'] for b in selected)))
        return cost

    reason = None
    try:
        with localcontext() as ctx:
            ctx.prec = 36
            value = visit(root['key'], ())
            candidate = str(value)
    except (Unavailable, KeyError, TypeError, ValueError) as error:
        candidate = None
        reason = str(error) if isinstance(error, Unavailable) else 'INVALID_SOURCE_SHAPE'
    return dict(product_key=root['key'], method='EOS_EXPERIMENTAL_RECIPE_BALANCE',
        source='IIKO_RECIPE_AND_STOCK_FACTS', store_key=store_key, effective_on=at.isoformat(),
        stock_policy='POSITIVE_ONLY' if positive_only else 'SIGNED_BALANCE_DIAGNOSTIC',
        diagnostic_amount=candidate, amount=None, publication_allowed=False,
        status='INCOMPLETE' if candidate is None else 'UNVERIFIED', reason=reason,
        warnings=sorted(warnings), components=components)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--store-key')
    parser.add_argument('--signed', action='store_true')
    args = parser.parse_args()
    source = json.loads(args.evidence.read_text())
    at = date.fromisoformat(source['observed_at'][:10])
    result = [calculate(root, at=at, store_key=args.store_key, positive_only=not args.signed)
        for root in source['roots']]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
