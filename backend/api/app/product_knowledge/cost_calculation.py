"""K5C SSN reconstruction. Exact Decimal arithmetic; source SSN is never claimed.

Policy v1 reproduces the 2026-10-09 Office list. This module cannot approve or
publish values. Negative-stock and estimated valuations require Office review.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

POLICY = 'EOS_OFFICE_SSN_V1'
CENT = Decimal('.01')


class CostUnavailable(ValueError):
    pass


def number(value):
    if value is None or isinstance(value, (bool, float)):
        raise CostUnavailable('INVALID_DECIMAL')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CostUnavailable('INVALID_DECIMAL') from None
    if not result.is_finite():
        raise CostUnavailable('INVALID_DECIMAL')
    return result


def applies(spec, department):
    if spec is None:
        return True
    if not isinstance(spec, dict) or type(spec.get('inverse')) is not bool or not isinstance(spec.get('departments'), list):
        raise CostUnavailable('INVALID_DEPARTMENT_SCOPE')
    ids = spec['departments']
    if ids and department is None:
        raise CostUnavailable('DEPARTMENT_REQUIRED')
    return (department not in ids) if spec['inverse'] else (department in ids)


def calculate(root, *, at: date, department=None):
    """Normalized UUID-keyed tree, references, units and monetary stock snapshot.

    Root always uses its raw set (SSN), irrespective of finished-dish writeoff.
    Nested direct-writeoff products use stock valuation, other compounds expand.
    Unit costs round to cents; nested SSN remains unrounded until the root total.
    """
    components, risks, methods, used_charts = [], set(), {}, []
    by_product = {}
    refs = {p['key']: p for p in root['references']}
    if len(refs) != len(root['references']):
        return dict(amount=None, reason='DUPLICATE_REFERENCE', components=[], risks=[], signature=None)
    units = {u['key']: u['name'] for u in root.get('units', [])}
    for c in root['charts']:
        try:
            start = date.fromisoformat(c['dateFrom'])
            end = date.fromisoformat(c['dateTo']) if c.get('dateTo') else None
            if end is not None and end <= start:
                raise CostUnavailable('INVALID_RECIPE_INTERVAL')
            if start <= at and (end is None or at < end):
                by_product.setdefault(c['root_key'], []).append(c)
        except (KeyError, TypeError, ValueError):
            return dict(amount=None, reason='INVALID_RECIPE_INTERVAL', components=[], risks=[], signature=None)
    rows = root['balances']
    if any(len({(b['product_key'], b['store_key']) for b in group['rows']}) != len(group['rows']) for group in rows):
        return dict(amount=None, reason='DUPLICATE_BALANCE', components=[], risks=[], signature=None)
    balances = [b for group in rows for b in group['rows']]
    if len({(b['product_key'], b['store_key']) for b in balances}) != len(balances):
        return dict(amount=None, reason='DUPLICATE_BALANCE', components=[], risks=[], signature=None)

    def valuation(pid):
        selected = [b for b in balances if b['product_key'] == pid and number(b['amount']) > 0]
        method = 'POSITIVE_STOCK_POOL'
        if not selected:
            selected = [b for b in balances if b['product_key'] == pid and number(b['amount']) < 0]
            method = 'NEGATIVE_STOCK_RATIO'
            risks.add('NEGATIVE_STOCK_RATIO')
        quantity = sum((number(b['amount']) for b in selected), Decimal(0))
        money = sum((number(b['sum']) for b in selected), Decimal(0))
        if not selected or quantity == 0:
            # EstimatedPurchasePrice=0 alone cannot prove a deliberate estimate.
            raise CostUnavailable('MISSING_STOCK_VALUATION:'+pid)
        value = money / quantity
        if value < 0:
            raise CostUnavailable('NEGATIVE_UNIT_COST:'+pid)
        if value == 0:
            risks.add('ZERO_VALUATION_REQUIRES_REVIEW')
        methods[pid] = dict(method=method, zero=value == 0, stores=sorted(b['store_key'] for b in selected))
        return value.quantize(CENT, rounding=ROUND_HALF_UP), method, selected

    def visit(pid, multiplier, path, is_root=False):
        if len(path) >= 32 or pid in path:
            raise CostUnavailable('RECIPE_CYCLE_OR_DEPTH:'+pid)
        p = refs.get(pid)
        if p is None or p.get('deleted') is True or p.get('type') not in ('GOODS','DISH','PREPARED','MODIFIER'):
            raise CostUnavailable('UNRESOLVED_PRODUCT:'+pid)
        if p.get('mainUnit_key') not in units or not units.get(p.get('mainUnit_key')):
            raise CostUnavailable('UNRESOLVED_UNIT:'+pid)
        charts = by_product.get(pid, [])
        if len(charts) > 1:
            raise CostUnavailable('AMBIGUOUS_RECIPE:'+pid)
        chart = charts[0] if charts else None
        expand = is_root
        if chart and not is_root:
            if 'direct_spec' not in chart or chart['direct_spec'] is None:
                raise CostUnavailable('UNKNOWN_NESTED_WRITEOFF:'+pid)
            expand = not applies(chart['direct_spec'], department)
        if is_root and chart is None:
            raise CostUnavailable('MISSING_ROOT_RECIPE')
        if not is_root and chart is None and p['type'] in ('DISH','PREPARED','MODIFIER'):
            raise CostUnavailable('MISSING_NESTED_RECIPE:'+pid)
        if expand:
            if chart.get('size_strategy') != 'COMMON' and not (chart.get('size_strategy') == 'SPECIFIC' and chart.get('scale_absent') is True):
                raise CostUnavailable('SIZE_REQUIRES_REVIEW:'+pid)
            basis = number(chart['assembledAmount'])
            if basis <= 0 or not chart['items']:
                raise CostUnavailable('INVALID_RECIPE_BASIS:'+pid)
            used_charts.append(chart)
            total = Decimal(0)
            for item in chart['items']:
                norm = number(item['amountIn'])
                if norm < 0:
                    raise CostUnavailable('NEGATIVE_NORM')
                if item.get('size_specified'):
                    raise CostUnavailable('SIZE_REQUIRES_REVIEW')
                if norm == 0 or not applies(item.get('storeSpecification'), department):
                    continue
                total += visit(item['product_key'], multiplier * norm / basis, path + (pid,))
            return total
        unit_cost, method, stock = valuation(pid)
        contribution = multiplier * unit_cost
        components.append(dict(product_key=pid, name=p.get('name'), unit=units[p['mainUnit_key']],
            quantity=str(multiplier), unit_cost=str(unit_cost), contribution=str(contribution),
            method=method, path=list(path), stock_rows=stock,
            estimated_price=p.get('estimatedPurchasePrice')))
        return contribution

    try:
        with localcontext() as ctx:
            ctx.prec = 50
            value = visit(root['key'], Decimal(1), (), True)
            amount = str(value.quantize(CENT, rounding=ROUND_HALF_UP))
        # Excludes changing prices, includes norms/units/valuation method/zero state.
        signature = dict(policy=POLICY, charts=used_charts,
            references=[{k:p.get(k) for k in ('key','type','mainUnit_key','unitWeight','deleted')} for p in root['references']],
            units=root.get('units', []), methods=methods)
        return dict(amount=amount, unrounded_amount=str(value), reason=None,
            components=components, risks=sorted(risks), signature=signature)
    except (CostUnavailable, KeyError, TypeError, ValueError) as error:
        return dict(amount=None, reason=str(error) if isinstance(error, CostUnavailable) else 'INVALID_SOURCE_SHAPE',
            components=[], risks=sorted(risks), signature=None)
