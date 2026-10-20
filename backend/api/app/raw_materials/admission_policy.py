"""Exact original source binding; no global employee exception and no numeric conversion."""
from decimal import Decimal, InvalidOperation
from app.product_knowledge.bootstrap import digest

LINE_FIELDS=('num','product','store','amount','actualAmount','amountUnit','containerId','sum','price','priceWithoutVat','vatPercent','vatSum','isAdditionalExpense')


def original(line):
    return line.get('original_line') or line


def line_hash(line):
    return digest({k:original(line).get(k) for k in LINE_FIELDS})


def number(value):
    try:
        n=Decimal(str(value));return n if n.is_finite() else None
    except (InvalidOperation,ValueError):return None


def matching(mapping, document, line, kind):
    result=[]
    for decision in mapping.get('document_admissions',[]):
        if decision['kind']!=kind or decision['document_id']!=document['id'] or decision['document_hash']!=document['source_hash']:continue
        if decision['line_num'] and (decision['line_num']!=line.get('num') or decision['line_hash']!=line_hash(line)):continue
        if kind=='BASE_UNIT_CONTAINER':
            raw=original(line);proof=decision['verification']
            actual,amount=number(raw.get('actualAmount')),number(raw.get('amount'))
            if raw.get('amountUnit')!=mapping['unit_id'] or actual is None or actual<=0 or actual!=amount:continue
            if proof.get('unit_id')!=mapping['unit_id'] or number(proof.get('quantity'))!=actual or proof.get('container_id')!=raw.get('containerId'):continue
        result.append(decision)
    return result
