"""Ordinary pricelist, without a price category or product size.

v2/price already resolves BASE orders into effective half-open intervals.
Date-only queries cannot select a changing intraday price. Until independently
verified, SCHEDULED overlaps never inherit an invented precedence.
"""
from datetime import date, time
from app.integrations.iiko.prices import PriceContext


def schedule_on_day(schedule, day):
    # Unknown schedules fail closed, including overnight/zero-width semantics.
    try:
        periods = schedule['periods']
        if not isinstance(periods, list):
            return True
        for p in periods:
            begin, end = time.fromisoformat(p['begin']), time.fromisoformat(p['end'])
            days = p['daysOfWeek']
            if not days or any(type(d) is not int or d not in range(1, 8) for d in days):
                return True
            if begin >= end:
                return True
            if day.isoweekday() in days:
                return True
        return False
    except (KeyError, ValueError, TypeError):
        return True


def resolve(contexts: list[PriceContext], day: date):
    active = [p for c in contexts if c.productSizeId is None for p in c.prices
              if p.dateFrom <= day < p.dateTo]
    if any(p.schedule is not None and schedule_on_day(p.schedule, day) for p in active):
        return dict(state='TIME_DEPENDENT', price=None)
    base = [p for p in active if p.schedule is None]
    if len(base) > 1:
        return dict(state='CONFLICT', price=None)
    if not base:
        return dict(state='MISSING', price=None)
    p = base[0]
    if not p.included:
        return dict(state='EXCLUDED', price=None)
    if p.price is None:
        return dict(state='MISSING', price=None)
    return dict(state='CONFIRMED', price=p)
