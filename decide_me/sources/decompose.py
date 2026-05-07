from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from decide_me.sources.model import (
    SUPPORTED_DECOMPOSE_FORMATS,
    normalize_text,
    path_slug,
    sha256_text,
    source_path_from_metadata,
    source_unit_id,
)


DECOMPOSE_STRATEGIES = {"auto", "egov-law-xml", "japanese-regulation-text"}
XML_UNIT_TAGS = {
    "Article",
    "Paragraph",
    "Item",
    "Subitem1",
    "Subitem2",
    "Subitem3",
    "Subitem4",
    "Subitem5",
    "Subitem6",
    "Subitem7",
    "Subitem8",
    "Subitem9",
    "Subitem10",
    "AppdxTable",
}

CHAPTER_PATTERN = re.compile(r"^(第[0-9０-９一二三四五六七八九十百千]+章)\s*(.*)$")
ARTICLE_PATTERN = re.compile(r"^(第[0-9０-９一二三四五六七八九十百千]+条(?:の[0-9０-９一二三四五六七八九十百千]+)?)\s*(.*)$")
PARAGRAPH_PATTERN = re.compile(r"^([0-9０-９]+)\s+(.+)$")
ITEM_PATTERN = re.compile(r"^([一二三四五六七八九十百千]+)\s+(.+)$")
SUBITEM_PATTERN = re.compile(r"^([イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセス])\s+(.+)$")
APPENDIX_PATTERN = re.compile(r"^(別表第[0-9０-９一二三四五六七八九十百千]+)\s*(.*)$")


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._pieces.append(stripped)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._pieces.append("\n")

    def text(self) -> str:
        return "\n".join(piece for piece in self._pieces if piece)


def decompose_document(
    ai_dir: str | Path,
    metadata: dict[str, Any],
    *,
    strategy: str,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    if strategy not in DECOMPOSE_STRATEGIES:
        allowed = ", ".join(sorted(DECOMPOSE_STRATEGIES))
        raise ValueError(f"strategy must be one of: {allowed}")
    source_format = metadata["format"]
    if source_format == "pdf":
        raise ValueError("PDF decomposition is unsupported in Phase 12 MVP; import stores the snapshot only.")
    if source_format not in SUPPORTED_DECOMPOSE_FORMATS:
        raise ValueError(f"decomposition is unsupported for source format: {source_format}")

    selected = _resolve_strategy(metadata, strategy)
    original = source_path_from_metadata(ai_dir, metadata, "original_path")
    if selected == "egov-law-xml":
        units = _decompose_egov_xml(original, metadata)
        flags = ["xml_structure_used", "parent_units_include_descendant_text"]
    else:
        text = source_text(original, source_format)
        units = _decompose_japanese_regulation_text(text, metadata)
        flags = ["text_heading_rules_used"]

    if not units:
        flags.append("no_units_detected")
    return units, _parser_version(selected), flags


def source_text(path: Path, source_format: str) -> str:
    data = path.read_bytes()
    if source_format == "html":
        parser = _TextHTMLParser()
        parser.feed(data.decode("utf-8", errors="replace"))
        return parser.text()
    if source_format == "xml":
        return data.decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def html_to_text(data: bytes) -> str:
    parser = _TextHTMLParser()
    parser.feed(data.decode("utf-8", errors="replace"))
    return parser.text()


def _resolve_strategy(metadata: dict[str, Any], strategy: str) -> str:
    if strategy != "auto":
        return strategy
    if metadata["format"] == "xml":
        return "egov-law-xml"
    return "japanese-regulation-text"


def _parser_version(strategy: str) -> str:
    if strategy == "egov-law-xml":
        return "egov_law_xml_v1"
    return "japanese_regulation_text_v1"


def _decompose_egov_xml(path: Path, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    tree = ET.parse(path)
    root = tree.getroot()
    records: list[dict[str, Any]] = []

    def visit(element: ET.Element, context: dict[str, str]) -> None:
        tag = _local_name(element.tag)
        next_context = deepcopy(context)
        if tag in XML_UNIT_TAGS:
            next_context.update(_xml_path_update(element, tag))
            text = normalize_text(" ".join(element.itertext()))
            if text:
                records.append(
                    {
                        "unit_type": _xml_unit_type(tag),
                        "path": deepcopy(next_context),
                        "text_exact": text,
                    }
                )
        for child in list(element):
            visit(child, next_context)

    visit(root, {})
    return _finalize_units(records, metadata)


def _xml_path_update(element: ET.Element, tag: str) -> dict[str, str]:
    if tag == "Article":
        return {"article": _first_text(element, "ArticleTitle") or _attribute_value(element, "Num") or "Article"}
    if tag == "Paragraph":
        return {"paragraph": _first_text(element, "ParagraphNum") or _attribute_value(element, "Num") or "Paragraph"}
    if tag == "Item":
        return {"item": _first_text(element, "ItemTitle") or _attribute_value(element, "Num") or "Item"}
    if tag.startswith("Subitem"):
        title = _first_text(element, f"{tag}Title") or _attribute_value(element, "Num") or tag
        return {tag.lower(): title}
    if tag == "AppdxTable":
        return {"appendix": _first_text(element, "AppdxTableTitle") or _attribute_value(element, "Num") or "AppdxTable"}
    return {}


def _xml_unit_type(tag: str) -> str:
    if tag.startswith("Subitem"):
        return "subitem"
    if tag == "AppdxTable":
        return "appendix_table"
    return tag.lower()


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _first_text(element: ET.Element, local_name: str) -> str | None:
    for child in list(element):
        if _local_name(child.tag) == local_name:
            text = normalize_text(" ".join(child.itertext()))
            return text or None
    return None


def _attribute_value(element: ET.Element, name: str) -> str | None:
    value = element.attrib.get(name)
    return value if value else None


def _decompose_japanese_regulation_text(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    context: dict[str, str] = {}
    current: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        match = CHAPTER_PATTERN.match(line)
        if match:
            context = {"chapter": _join_label_text(match)}
            current = None
            continue
        match = APPENDIX_PATTERN.match(line)
        if match:
            current = _new_text_record("appendix_table", {**context, "appendix": match.group(1)}, _join_label_text(match))
            records.append(current)
            continue
        match = ARTICLE_PATTERN.match(line)
        if match:
            context = {**{key: value for key, value in context.items() if key == "chapter"}, "article": match.group(1)}
            current = _new_text_record("article", context, _join_label_text(match))
            records.append(current)
            continue
        match = PARAGRAPH_PATTERN.match(line)
        if match and "article" in context:
            path = {**context, "paragraph": match.group(1)}
            current = _new_text_record("paragraph", path, _join_label_text(match))
            records.append(current)
            continue
        match = ITEM_PATTERN.match(line)
        if match and "article" in context:
            path = {**context, "item": match.group(1)}
            current = _new_text_record("item", path, _join_label_text(match))
            records.append(current)
            continue
        match = SUBITEM_PATTERN.match(line)
        if match and "article" in context:
            path = {**context, "subitem": match.group(1)}
            current = _new_text_record("subitem", path, _join_label_text(match))
            records.append(current)
            continue
        if current is not None:
            current["text_exact"] = normalize_text(f"{current['text_exact']} {line}")

    return _finalize_units(records, metadata)


def _new_text_record(unit_type: str, path: dict[str, str], text: str) -> dict[str, Any]:
    return {"unit_type": unit_type, "path": deepcopy(path), "text_exact": normalize_text(text)}


def _join_label_text(match: re.Match[str]) -> str:
    label = match.group(1)
    rest = match.group(2).strip() if len(match.groups()) >= 2 else ""
    return normalize_text(f"{label} {rest}") if rest else label


def _finalize_units(records: list[dict[str, Any]], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, record in enumerate(records, start=1):
        text_exact = normalize_text(record["text_exact"])
        if not text_exact:
            continue
        text_normalized = normalize_text(text_exact)
        content_hash = sha256_text(text_exact)
        path_values = [str(value) for value in record["path"].values() if value]
        unit_id = source_unit_id(
            metadata["id"],
            path_slug([str(order), record["unit_type"], *path_values]),
            content_hash,
        )
        if unit_id in seen:
            unit_id = source_unit_id(metadata["id"], path_slug([str(order), record["unit_type"]]), content_hash)
        seen.add(unit_id)
        units.append(
            {
                "id": unit_id,
                "source_document_id": metadata["id"],
                "order": len(units) + 1,
                "unit_type": record["unit_type"],
                "path": deepcopy(record["path"]),
                "citation": _citation(metadata, record["path"]),
                "canonical_locator": _canonical_locator(metadata, record["path"]),
                "text_exact": text_exact,
                "text_normalized": text_normalized,
                "content_hash": content_hash,
                "anchors": {"page": None, "xpath": None},
                "effective_from": metadata["effective_from"],
                "effective_to": metadata["effective_to"],
            }
        )
    return units


def _citation(metadata: dict[str, Any], path: dict[str, str]) -> str:
    pieces = [metadata["title"], *[value for value in path.values() if value]]
    return " ".join(pieces)


def _canonical_locator(metadata: dict[str, Any], path: dict[str, str]) -> str:
    pieces = [
        metadata["document_type"],
        metadata["title"],
        *[value for value in path.values() if value],
    ]
    return ":".join(pieces)
