from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import UUID


logger = logging.getLogger("eos.iiko.finalization")
logger.setLevel(logging.INFO)

_MAX_LOG_VALUE_LENGTH = 500
_SENSITIVE_HEADER_RE = re.compile(
    r"(?im)(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pass|authorization|proxy-authorization|"
    r"cookie|set-cookie|session(?:[_-]?(?:cookie|id))?|token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|secret|"
    r"client[_-]?secret|passwordhash)\b\s*[\"']?\s*[:=]\s*)"
    r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;&}]+)"
)
_AUTH_SCHEME_RE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[a-z0-9._~+/=-]+"
)


@dataclass(frozen=True, slots=True)
class IikoFinalizationLogContext:
    supply_request_id: UUID
    document_number: str | None
    document_id: UUID | str | None


_context: ContextVar[IikoFinalizationLogContext | None] = ContextVar(
    "iiko_finalization_log_context",
    default=None,
)


@contextmanager
def iiko_finalization_log_context(
    *,
    supply_request_id: UUID,
    document_number: str | None = None,
    document_id: UUID | str | None = None,
) -> Iterator[None]:
    token = _context.set(IikoFinalizationLogContext(
        supply_request_id=supply_request_id,
        document_number=document_number,
        document_id=document_id,
    ))
    try:
        yield
    finally:
        _context.reset(token)


def has_iiko_finalization_log_context() -> bool:
    return _context.get() is not None


def sanitize_log_value(value: Any) -> str:
    rendered = "" if value is None else str(value)
    rendered = _SENSITIVE_HEADER_RE.sub(r"\1: <redacted>", rendered)
    rendered = _SENSITIVE_VALUE_RE.sub(r"\1<redacted>", rendered)
    rendered = _AUTH_SCHEME_RE.sub("<redacted>", rendered)
    rendered = " ".join(rendered.split())
    return rendered[:_MAX_LOG_VALUE_LENGTH]


def xml_structure_summary(root: ET.Element | None) -> str:
    if root is None:
        return json.dumps({"parseable": False}, separators=(",", ":"))

    def local_name(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    def node(element: ET.Element) -> dict[str, str]:
        result = {"tag": local_name(element)}
        class_name = element.attrib.get("cls")
        if class_name:
            result["class"] = class_name[:120]
        return result

    direct_children = list(root)[:20]
    return_values = [
        element for element in root.iter()
        if local_name(element) == "returnValue"
    ][:5]
    summary = {
        "parseable": True,
        "root": node(root),
        "children": [node(element) for element in direct_children],
        "returnValues": [
            {
                **node(element),
                "children": [node(child) for child in list(element)[:20]],
                "grandchildren": [
                    node(grandchild)
                    for child in list(element)[:10]
                    for grandchild in list(child)[:10]
                ][:30],
            }
            for element in return_values
        ],
    }
    return json.dumps(summary, separators=(",", ":"))[:4000]


def log_finalization_event(
    event: str,
    *,
    level: int = logging.INFO,
    stage: str,
    rpc_method: str | None = None,
    **fields: Any,
) -> None:
    context = _context.get()
    values: dict[str, Any] = {
        "event": event,
        "stage": stage,
        "supply_request_id": context.supply_request_id if context else None,
        "document_number": context.document_number if context else None,
        "authoritative_uuid": context.document_id if context else None,
        "rpc_method": rpc_method,
        **fields,
    }
    rendered = " ".join(
        f"{key}={sanitize_log_value(value)}"
        for key, value in values.items()
        if value is not None
    )
    logger.log(level, "iiko_finalization %s", rendered)
