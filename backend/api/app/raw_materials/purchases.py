"""R-M2 purchase policy. Pure, replayable Decimal calculation over bounded inputs."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET
from app.product_knowledge.bootstrap import digest

WAREHOUSE = '1c22edc0-7ded-41c9-b781-0389462c7247'
SOURCE = '244d6eaf9c7c106993d10feb0ff9883dbdb73101cd3a2ab6852c9ba5b9907401'
TECHNICAL = '5bf2b1c7-8c91-b774-01a0-ae4cafa53ba1'
POLICY = 'rm2-v1-rub-vat-document-sum-exact-unit'


def windows(as_of: date):
    year, month = divmod(as_of.year * 12 + as_of.month - 7, 12)
    start = date(year, month + 1, 1)
    while start <= as_of:
        year, month = divmod(start.year * 12 + start.month, 12)
        end = min(date(year, month + 1, 1), as_of.fromordinal(as_of.toordinal() + 1))
        yield start, end
        start = end


def parse_export(xml: str):
    root = ET.fromstring(xml)
    name = lambda node: node.tag.rsplit('}', 1)[-1]
    if name(root) not in {'incomingInvoiceDtoes', 'documentDtoes', 'documents'}:
        raise ValueError('PURCHASE_EXPORT_INCOMPLETE')
    if any(name(n).lower() in {'nextpage', 'hasmore', 'totalpages'} and (n.text or '').strip().lower() not in {'', '0', '1', 'false'} for n in root):
        raise ValueError('PURCHASE_EXPORT_PAGINATION_UNSUPPORTED')
    documents = []
    for doc in root:
        if name(doc) != 'document':
            raise ValueError('PURCHASE_EXPORT_CONTRACT')
        fields = {name(n): (n.text or '').strip() for n in doc if name(n) != 'items'}
        # Never silently drop an unusable header: it could hide the newest receipt.
        if not all(fields.get(k) for k in ('id', 'status', 'documentNumber')):
            raise ValueError('PURCHASE_EXPORT_HEADER_MISSING')
        fields['id'] = str(UUID(fields['id']))
        fields['items'] = [{name(n): (n.text or '').strip() for n in item} for container in doc if name(container) == 'items' for item in container]
        if any(not i.get('product') for i in fields['items']):
            raise ValueError('PURCHASE_EXPORT_LINE_MISSING_PRODUCT')
        fields['source_hash'] = digest(fields)
        for key in ('supplier', 'defaultStore'):
            if fields.get(key):
                try: fields[key] = str(UUID(fields[key]))
                except ValueError: pass
        for item in fields['items']:
            item['product'] = str(UUID(item['product']))
            for key in ('store', 'amountUnit', 'containerId'):
                if item.get(key):
                    try: item[key] = str(UUID(item[key]))
                    except ValueError: pass
        documents.append(fields)
    if len(documents) > 20000:
        raise ValueError('PURCHASE_EXPORT_LIMIT')
    return documents


def warehouse(item, document):
    raw = item.get('store') or document.get('defaultStore')
    try:
        return str(UUID(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def evaluate(documents, suppliers, mapping, *, date_from, date_to, units=None):
    with localcontext() as context:
        context.prec = 80
        return _evaluate(documents, suppliers, mapping, date_from=date_from, date_to=date_to, units=units or {})


def _evaluate(documents, suppliers, mapping, *, date_from, date_to, units):
    """No implicit historical conversions; unknown newer candidates block fallback."""
    grouped, exclusions, undated = {}, [], False
    for document in documents:
        relevant = [i for i in document['items'] if i.get('product') == mapping['iiko_product_id']]
        if not relevant:
            continue
        lines = [i for i in relevant if warehouse(i, document) in {WAREHOUSE, None}]
        if not lines:
            continue
        did, status = document['id'], document.get('status', '').upper()
        if did == TECHNICAL or status in {'NEW', 'DELETED', 'CANCELLED', 'CANCELED'} or any(document.get(k, 'false').lower() == 'true' for k in ('deleted','isDeleted','cancelled','isCancelled')):
            exclusions.append(dict(document_id=did, reason='TECHNICAL_SMOKE' if did == TECHNICAL else 'NOT_PROCESSED'))
            continue
        supplier = suppliers.get(document.get('supplier'), {})
        if supplier.get('represents_store'):
            exclusions.append(dict(document_id=did, reason='INTERNAL_STORE'))
            continue
        try:
            instant = datetime.fromisoformat(document.get('dateIncoming', ''))
            # iiko document local date/time, preserving explicit offsets if supplied.
            instant = (instant.replace(tzinfo=ZoneInfo('Asia/Yekaterinburg')) if instant.tzinfo is None else instant.astimezone(ZoneInfo('Asia/Yekaterinburg')))
            stamp = instant.isoformat()
        except (ValueError, TypeError):
            undated = True
            stamp = ''
        if stamp and not (date_from <= instant.date().isoformat() < date_to):
            continue
        reason = []
        if status != 'PROCESSED' or document.get('deleted', 'false').lower() != 'false': reason.append('UNCONFIRMED_DOCUMENT')
        if not supplier or not supplier.get('is_supplier') or supplier.get('is_employee') or supplier.get('is_deleted'):
            reason.append('SUPPLIER_UNCONFIRMED')
        if document.get('currency') not in (None, '', 'RUB'): reason.append('CURRENCY_MISMATCH')
        if any(i.get('isAdditionalExpense', 'false').lower() != 'false' for i in document['items']): reason.append('ADDITIONAL_EXPENSE')
        numerator, denominator, identities = Decimal(0), Decimal(0), set()
        evidence = []
        for item in lines:
            identity = item.get('num')
            if not identity or not str(identity).isdigit() or identity in identities: reason.append('LINE_IDENTITY_CONFLICT')
            identities.add(identity)
            if warehouse(item, document) != WAREHOUSE: reason.append('WAREHOUSE_UNCONFIRMED')
            if item.get('amountUnit') != mapping['unit_id']: reason.append('UNIT_MISMATCH')
            if item.get('containerId') and item.get('containerId') != '00000000-0000-0000-0000-000000000000': reason.append('CONTAINER_UNCONFIRMED')
            if item.get('isAdditionalExpense', 'false').lower() != 'false': reason.append('ADDITIONAL_EXPENSE')
            amount, actual, total = decimal(item.get('amount')), decimal(item.get('actualAmount')), decimal(item.get('sum'))
            if actual is None or amount is None or actual != amount or actual <= 0 or total is None or total <= 0:
                reason.append('AMOUNT_UNCONFIRMED')
            else:
                numerator += total
                denominator += actual
            vat, vat_sum = decimal(item.get('vatPercent')), decimal(item.get('vatSum'))
            if vat is None or not 0 <= vat <= 100 or vat_sum is None or vat_sum < 0 or total is None or vat_sum > total or (vat == 0 and vat_sum != 0):
                reason.append('TAX_UNCONFIRMED')
            evidence.append(dict(unit_name=units.get(item.get('amountUnit'), mapping['unit'] if item.get('amountUnit') == mapping['unit_id'] else None), **{k: item.get(k) for k in ('num','product','store','amount','actualAmount','amountUnit','containerId','sum','price','priceWithoutVat','vatPercent','vatSum','isAdditionalExpense')}))
        candidate = dict(document_id=did, number=document.get('documentNumber'), receipt_at=stamp or None,
            supplier_id=document.get('supplier'), supplier_name=supplier.get('name') if not supplier.get('is_employee') else None,
            supplier_flags={k: supplier.get(k) for k in ('is_supplier','is_employee','represents_store','is_deleted')},
            status=status, revision=document.get('revision'), source_hash=document['source_hash'], lines=evidence,
            numerator=str(numerator), denominator=str(denominator), reasons=sorted(set(reason)))
        grouped.setdefault(did, {})[document['source_hash']] = candidate
    candidates = []
    for versions in grouped.values():
        for candidate in versions.values():
            if len(versions) > 1: candidate['reasons'].append('DOCUMENT_REVISION_CONFLICT')
            candidates.append(candidate)
    latest_time = max((c['receipt_at'] or '' for c in candidates), default='')
    latest = [c for c in candidates if not c['receipt_at'] or c['receipt_at'] == latest_time]
    reasons = sorted({r for c in latest for r in c['reasons']})
    if undated: reasons.append('DATE_UNCONFIRMED')
    if any('UNIT_MISMATCH' in c['reasons'] for c in candidates): reasons.append('MIXED_UNITS_BLOCKED')
    if len({c['document_id'] for c in latest}) > 1: reasons.append('LATEST_DOCUMENT_CONFLICT')
    status = 'NO_DATA' if not latest else 'BLOCKED' if reasons else 'READY'
    amount = None
    if status == 'READY':
        with localcontext() as context:
            context.prec = 38
            amount = str(Decimal(latest[0]['numerator']) / Decimal(latest[0]['denominator']))
    return dict(status=status, amount=amount, currency='RUB', tax_basis='WITH_VAT', unit_id=mapping['unit_id'], unit=mapping['unit'],
        receipt_at=latest_time or None, reasons=reasons or ([] if latest else ['NO_PURCHASE_IN_WINDOW']),
        candidates=latest, documents=candidates, exclusions=exclusions, date_from=date_from, date_to=date_to,
        warehouse_id=WAREHOUSE, policy=POLICY)
