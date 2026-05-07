from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from decide_me.sources.model import load_registry, load_source_metadata, load_units, source_paths
from decide_me.store import load_runtime, runtime_paths


SOURCE_INDEX_SCHEMA_VERSION = 1


def rebuild_evidence_index(ai_dir: str | Path) -> dict[str, Any]:
    paths = source_paths(ai_dir)
    paths["index_dir"].mkdir(parents=True, exist_ok=True)
    registry = load_registry(ai_dir)
    row_count = 0
    with sqlite3.connect(paths["source_units_index"]) as conn:
        _reset_schema(conn)
        fts_enabled = _create_fts(conn)
        for entry in registry.get("documents", []):
            metadata = load_source_metadata(ai_dir, entry["id"])
            for unit in load_units(ai_dir, entry["id"]):
                row_count += 1
                conn.execute(
                    """
                    INSERT INTO source_units(
                        source_unit_id,
                        source_document_id,
                        title,
                        citation,
                        unit_type,
                        text_exact,
                        text_normalized,
                        content_hash,
                        effective_from,
                        effective_to
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unit["id"],
                        unit["source_document_id"],
                        metadata["title"],
                        unit["citation"],
                        unit["unit_type"],
                        unit["text_exact"],
                        unit["text_normalized"],
                        unit["content_hash"],
                        unit["effective_from"],
                        unit["effective_to"],
                    ),
                )
                if fts_enabled:
                    conn.execute(
                        """
                        INSERT INTO source_units_fts(source_unit_id, title, citation, text_normalized)
                        VALUES (?, ?, ?, ?)
                        """,
                        (unit["id"], metadata["title"], unit["citation"], unit["text_normalized"]),
                    )
        conn.execute(
            "INSERT INTO source_index_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SOURCE_INDEX_SCHEMA_VERSION)),
        )
        conn.execute("INSERT INTO source_index_meta(key, value) VALUES (?, ?)", ("fts_enabled", str(int(fts_enabled))))
        conn.commit()
    return {"status": "ok", "path": str(paths["source_units_index"]), "unit_count": row_count, "fts_enabled": fts_enabled}


def search_evidence(
    ai_dir: str | Path,
    *,
    query: str,
    source_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query must be a non-empty string")
    if limit < 1:
        raise ValueError("limit must be positive")
    paths = source_paths(ai_dir)
    if not paths["source_units_index"].exists():
        rebuild_evidence_index(ai_dir)
    linked = _linked_targets(ai_dir)
    with sqlite3.connect(paths["source_units_index"]) as conn:
        conn.row_factory = sqlite3.Row
        rows = _search_fts(conn, query, source_id=source_id, limit=limit)
        if not rows:
            rows = _search_like(conn, query, source_id=source_id, limit=limit)
    results = []
    for row in rows:
        item = dict(row)
        unit_links = linked.get(item["source_unit_id"], {})
        item["linked_object_ids"] = sorted(
            {target for targets in unit_links.values() for target in targets}
        )
        item["linked_by_relevance"] = {
            relation: sorted(targets) for relation, targets in sorted(unit_links.items())
        }
        results.append(item)
    return {"status": "ok", "query": query, "count": len(results), "results": results}


def _reset_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS source_index_meta")
    conn.execute("DROP TABLE IF EXISTS source_units")
    conn.execute("DROP TABLE IF EXISTS source_units_fts")
    conn.execute("CREATE TABLE source_index_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE source_units(
            source_unit_id TEXT PRIMARY KEY,
            source_document_id TEXT NOT NULL,
            title TEXT NOT NULL,
            citation TEXT NOT NULL,
            unit_type TEXT NOT NULL,
            text_exact TEXT NOT NULL,
            text_normalized TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            effective_to TEXT
        )
        """
    )
    conn.execute("CREATE INDEX source_units_document_idx ON source_units(source_document_id)")


def _create_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE source_units_fts
            USING fts5(source_unit_id, title, citation, text_normalized)
            """
        )
    except sqlite3.OperationalError:
        return False
    return True


def _search_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    source_id: str | None,
    limit: int,
) -> list[sqlite3.Row]:
    try:
        where = "source_units_fts MATCH ?"
        params: list[Any] = [query]
        if source_id is not None:
            where += " AND u.source_document_id = ?"
            params.append(source_id)
        params.append(limit)
        return list(
            conn.execute(
                f"""
                SELECT u.source_unit_id,
                       u.source_document_id,
                       u.title,
                       u.citation,
                       u.unit_type,
                       u.text_exact,
                       u.content_hash,
                       u.effective_from,
                       u.effective_to
                FROM source_units_fts f
                JOIN source_units u ON u.source_unit_id = f.source_unit_id
                WHERE {where}
                ORDER BY rank, u.source_unit_id
                LIMIT ?
                """,
                params,
            )
        )
    except sqlite3.OperationalError:
        return []


def _search_like(
    conn: sqlite3.Connection,
    query: str,
    *,
    source_id: str | None,
    limit: int,
) -> list[sqlite3.Row]:
    needle = f"%{query}%"
    where = "(title LIKE ? OR citation LIKE ? OR text_normalized LIKE ?)"
    params: list[Any] = [needle, needle, needle]
    if source_id is not None:
        where += " AND source_document_id = ?"
        params.append(source_id)
    params.append(limit)
    return list(
        conn.execute(
            f"""
            SELECT source_unit_id,
                   source_document_id,
                   title,
                   citation,
                   unit_type,
                   text_exact,
                   content_hash,
                   effective_from,
                   effective_to
            FROM source_units
            WHERE {where}
            ORDER BY source_unit_id
            LIMIT ?
            """,
            params,
        )
    )


def _linked_targets(ai_dir: str | Path) -> dict[str, dict[str, set[str]]]:
    try:
        bundle = load_runtime(runtime_paths(ai_dir))
    except Exception:
        return {}
    evidence_by_id = {
        obj["id"]: obj
        for obj in bundle["project_state"].get("objects", [])
        if obj.get("type") == "evidence" and obj.get("metadata", {}).get("source_unit_id")
    }
    result: dict[str, dict[str, set[str]]] = {}
    for link in bundle["project_state"].get("links", []):
        evidence = evidence_by_id.get(link.get("source_object_id"))
        if evidence is None:
            continue
        source_unit_id = evidence["metadata"]["source_unit_id"]
        by_relation = result.setdefault(source_unit_id, {})
        targets = by_relation.setdefault(link["relation"], set())
        targets.add(link["target_object_id"])
    return result
