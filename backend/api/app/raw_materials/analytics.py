"""Reproducible calendar purchase/usage projections. No stock ledger or inferred units."""
from datetime import date, datetime
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET
from app.raw_materials.purchases import evaluate, decimal, windows, WAREHOUSE
from app.product_knowledge.bootstrap import digest

POLICY = 'materials-calendar-v1'
CATEGORIES = ('PRODUCTION', 'DIRECT_ISSUE', 'TRANSFER', 'RETURN', 'INVENTORY', 'WRITEOFF', 'COST_CORRECTION', 'RECEIPT', 'OTHER')


def periods(today):
    bounds = list(windows(today))
    return bounds[0][0], today.replace(day=1), bounds[-2][0]


def average(documents, suppliers, mapping, *, start, end, units):
    result = evaluate(documents, suppliers, mapping, date_from=start.isoformat(), date_to=end.isoformat(), units=units)
    rows = result['documents']
    reasons = sorted({r for row in rows for r in row['reasons']})
    if 'DATE_UNCONFIRMED' in result['reasons']: reasons.append('DATE_UNCONFIRMED')
    with localcontext() as ctx:
        ctx.prec = 80
        numerator = sum((Decimal(r['numerator']) for r in rows), Decimal(0))
        denominator = sum((Decimal(r['denominator']) for r in rows), Decimal(0))
        status = 'BLOCKED' if reasons else 'NO_DATA' if not rows or denominator <= 0 else 'READY'
        amount = str(numerator / denominator) if status == 'READY' else None
    return dict(status=status, amount=amount, numerator=str(numerator), denominator=str(denominator),
        reasons=reasons, documents=rows, exclusions=result['exclusions'], date_from=start.isoformat(), date_to=end.isoformat(),
        unit=mapping['unit'], currency='RUB', tax_basis='WITH_VAT', formula='Σ сумма с НДС / Σ подтверждённое количество')


def parse_xml(xml, root_name, row_name):
    root = ET.fromstring(xml)
    name = lambda n: n.tag.rsplit('}', 1)[-1]
    if name(root) != root_name: raise ValueError('MATERIAL_ANALYTICS_CONTRACT')
    rows = []
    for node in root:
        if name(node) != row_name: raise ValueError('MATERIAL_ANALYTICS_INCOMPLETE')
        row = {name(n): (n.text or '').strip() for n in node if name(n) != 'items'}
        row['items'] = [{name(n): (n.text or '').strip() for n in i} for c in node if name(c) == 'items' for i in c]
        rows.append(row)
    if len(rows) > 100000: raise ValueError('MATERIAL_ANALYTICS_LIMIT')
    return rows


def usage(operations, outgoing, product_types, mapping, *, start, end, opening, closing):
    """Signed movements; inverse/reversal rows retained, unknown classification blocks production total."""
    pid = mapping['iiko_product_id']; docs = {}; reasons = []; evidence = []
    for doc in outgoing:
        if doc.get('id') in docs and docs[doc['id']] != doc: reasons.append('OUTGOING_REVISION_CONFLICT')
        docs[doc.get('id')] = doc
    totals = {k: Decimal(0) for k in CATEGORIES}; signed = Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 80
        for row in operations:
            if row.get('primaryStore') != WAREHOUSE or row.get('product') != pid: continue
            try: day = datetime.strptime(row.get('date', ''), '%d.%m.%Y').date()
            except ValueError: reasons.append('MOVEMENT_DATE_UNKNOWN'); day = None
            if day is not None and not start <= day < end: reasons.append('MOVEMENT_OUTSIDE_PERIOD')
            quantity = decimal(row.get('amount')); kind = row.get('type'); category = 'OTHER'
            if quantity is None: reasons.append('MOVEMENT_QUANTITY_UNKNOWN'); continue
            if kind == 'STORE_COST_CORRECTION':
                category = 'COST_CORRECTION'
                if quantity != 0: reasons.append('NONZERO_COST_CORRECTION')
            elif kind in {'INTERNAL_TRANSFER','TRANSFER'}: category = 'TRANSFER'
            elif kind == 'RETURNED_INVOICE': category = 'RETURN'
            elif kind in {'INCOMING_INVENTORY','OUTGOING_INVENTORY','INVENTORY'}: category = 'INVENTORY'
            elif kind in {'SESSION_WRITEOFF','WRITEOFF','WRITEOFF_DOCUMENT'}: category = 'WRITEOFF'
            elif kind == 'INCOMING_INVOICE': category = 'RECEIPT'
            elif kind == 'OUTGOING_INVOICE':
                doc = docs.get(row.get('documentId'))
                if not doc or doc.get('status') != 'PROCESSED' or doc.get('defaultStoreId') != WAREHOUSE:
                    reasons.append('OUTGOING_DOCUMENT_UNCONFIRMED')
                elif any(i.get('productId') == pid for i in doc['items']): category = 'DIRECT_ISSUE'
                elif doc['items'] and all(product_types.get(i.get('productId')) in {'DISH','PREPARED'} for i in doc['items']): category = 'PRODUCTION'
                else: reasons.append('OUTGOING_ROOT_CLASSIFICATION_UNKNOWN')
            else: reasons.append('MOVEMENT_CLASSIFICATION_UNKNOWN')
            totals[category] += quantity; signed += quantity
            # Quantity-only evidence; never return movement sums to knowledge-only roles.
            evidence.append(dict(root_products=[dict(product_id=i.get('productId'), product_type=product_types.get(i.get('productId'))) for i in docs.get(row.get('documentId'), {}).get('items', [])], category=category, quantity=str(quantity), date=row.get('date'), document_id=row.get('documentId'), number=row.get('documentNum'), source_hash=digest(row)))
        a, b = decimal(opening), decimal(closing)
        residual = b - a - signed if a is not None and b is not None else None
        if residual is None: reasons.append('BALANCE_BOUNDARY_UNKNOWN')
        elif abs(residual) > Decimal('0.000000001'): reasons.append('BALANCE_MISMATCH')
        reasons = sorted(set(reasons)); status = 'BLOCKED' if reasons else 'READY'
        quantity = str(-totals['PRODUCTION']) if status == 'READY' else None
    return dict(status=status, quantity=quantity, unit=mapping['unit'], date_from=start.isoformat(), date_to=end.isoformat(),
        reasons=reasons, categories={k:str(v) for k,v in totals.items()}, documents=evidence,
        balance=dict(opening=str(a) if a is not None else None, closing=str(b) if b is not None else None, signed_movements=str(signed), residual=str(residual) if residual is not None else None),
        label='Учётное списание ингредиента при передаче готовой продукции', independent_verification='NOT_AVAILABLE')
