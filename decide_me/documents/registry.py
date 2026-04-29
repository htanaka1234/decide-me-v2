from __future__ import annotations

from collections.abc import Callable
from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import DOCUMENT_TYPES, normalize_document_type
from decide_me.documents.builders.action_plan import build_action_plan_document
from decide_me.documents.builders.comparison_table import build_comparison_table_document
from decide_me.documents.builders.decision_brief import build_decision_brief_document
from decide_me.documents.builders.research_plan import build_research_plan_document
from decide_me.documents.builders.review_memo import build_review_memo_document
from decide_me.documents.builders.risk_register import build_risk_register_document


DocumentBuilder = Callable[[DocumentContext], dict[str, Any]]


DOCUMENT_BUILDERS: dict[str, DocumentBuilder] = {
    "decision-brief": build_decision_brief_document,
    "action-plan": build_action_plan_document,
    "risk-register": build_risk_register_document,
    "review-memo": build_review_memo_document,
    "research-plan": build_research_plan_document,
    "comparison-table": build_comparison_table_document,
}


def document_builder(document_type: str) -> DocumentBuilder:
    normalized = normalize_document_type(document_type)
    try:
        return DOCUMENT_BUILDERS[normalized]
    except KeyError as exc:  # pragma: no cover - protected by normalize_document_type
        supported = ", ".join(sorted(DOCUMENT_TYPES))
        raise ValueError(f"unsupported document type: {document_type}; supported: {supported}") from exc
