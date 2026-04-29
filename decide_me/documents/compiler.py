from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.documents.context import build_document_context
from decide_me.documents.model import normalize_document_type
from decide_me.documents.registry import document_builder


def compile_document(
    ai_dir: str | Path,
    *,
    document_type: str,
    session_ids: list[str] | None = None,
    object_ids: list[str] | None = None,
    include_invalidated: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_document_type(document_type)
    context = build_document_context(
        ai_dir,
        document_type=normalized,
        session_ids=session_ids,
        object_ids=object_ids,
        include_invalidated=include_invalidated,
        now=now,
    )
    return document_builder(normalized)(context)
