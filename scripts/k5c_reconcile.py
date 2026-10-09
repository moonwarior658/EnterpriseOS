"""Replay all 49 Office rows; separate strict results from conditional diagnostics."""
import copy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend/api'))
from app.product_knowledge.cost_calculation import calculate, POLICY
sys.path.insert(0,str(Path(__file__).resolve().parent))
from k5c_cost_prototype import calculate as original_calculate


def reconcile(source):
    rows=[]
    for root in source['roots']:
        at=date.fromisoformat(source['observed_at'][:10])
        strict=calculate(root,at=at)
        before=original_calculate(root,at=at)
        diagnostic=copy.deepcopy(root)
        for chart in diagnostic['charts']:chart['size_strategy']='COMMON'
        conditional=calculate(diagnostic,at=at,department='OFFICE_CONTEXT_OUTSIDE_EXCEPTION')
        refs={p['key']:p for p in root['references']}
        identity=refs[root['key']]
        if (identity['num'],identity['code']) != (root['office']['article'],root['office']['code']):raise ValueError('OFFICE_IDENTITY_MISMATCH')
        rows.append(dict(article=identity['num'],code=identity['code'],product_key=root['key'],name=identity['name'],
            office_ssn=root['office']['ssn'],office_estimated=root['office']['estimated'],
            strict_candidate=strict['amount'],strict_matches=strict['amount']==root['office']['ssn'],reason=strict['reason'],
            conditional_candidate=conditional['amount'],conditional_matches=conditional['amount']==root['office']['ssn'],
            prior_candidate=before['diagnostic_amount'],risks=strict['risks'],amount=None,publication_allowed=False))
    return dict(policy=POLICY,office_context=source['office_context'],stock_at=source['observed_at'],
        strict_exact=sum(r['strict_matches'] for r in rows),conditional_exact=sum(r['conditional_matches'] for r in rows),
        total=len(rows),currency='RUB',publication_allowed=False,rows=rows)

if __name__=='__main__':
    source=json.loads(Path(sys.argv[1]).read_text());print(json.dumps(reconcile(source),ensure_ascii=False,indent=2))
