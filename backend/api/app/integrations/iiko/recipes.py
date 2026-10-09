"""Confirmed K5A read-only endpoints. Decimal values are never parsed as floats."""
import json
from decimal import Decimal
from app.integrations.iiko.exceptions import IikoAuthenticationError, IikoAuthorizationError, IikoContractError, IikoResponseError

METHODS = {'getTree', 'getAssembled', 'getPrepared', 'getHistory', 'byId'}


def reject_nonfinite(_):
    raise ValueError('RECIPE_NONFINITE_NUMBER')

async def read_json(client, path, params):
    await client.authenticate()
    response = await client._raw_request('GET', path, params=params)
    if response.status_code == 401:
        client._token = None
        await client.authenticate()
        response = await client._raw_request('GET', path, params=params)
    if response.status_code == 401:
        raise IikoAuthenticationError('IIKO_TOKEN_REJECTED')
    if response.status_code == 403:
        raise IikoAuthorizationError('IIKO_ACCESS_DENIED')
    if not response.is_success:
        raise IikoResponseError(response.status_code)
    if len(response.content) > 16 * 1024 * 1024:
        raise IikoContractError('RECIPE_RESPONSE_TOO_LARGE')
    try:
        return json.loads(response.text, parse_float=Decimal,
            parse_constant=reject_nonfinite)
    except (ValueError, TypeError):
        raise IikoContractError('RECIPE_JSON_INVALID') from None

async def read_charts(client, method, *, product_id=None, at=None, department_id=None, chart_id=None):
    if method not in METHODS:
        raise IikoContractError('RECIPE_METHOD_INVALID')
    if method == 'byId':
        params = {'id': str(chart_id)}
    else:
        params = {'productId': str(product_id), 'departmentId': str(department_id)}
        if method != 'getHistory':
            params['date'] = at.isoformat()
    result = await read_json(client, 'api/v2/assemblyCharts/' + method, params)
    if method == 'getHistory' and not isinstance(result, list) or method != 'getHistory' and not isinstance(result, dict):
        raise IikoContractError('RECIPE_ENVELOPE_INVALID')
    return result


def frozen_json(value):
    """JSON portable exact decimal strings, including extra source fields."""
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, list):
        return [frozen_json(v) for v in value]
    if isinstance(value, dict):
        return {k: frozen_json(v) for k, v in value.items()}
    return value
