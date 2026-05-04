from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "schemas"
PROJECT_STATE_SCHEMA_ID = "https://example.invalid/decide-me/project-state.schema.json"
OBJECT_SCHEMA_ID = "https://example.invalid/decide-me/object.schema.json"
LINK_SCHEMA_ID = "https://example.invalid/decide-me/link.schema.json"


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def load_project_state_schema_bundle() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        load_schema("project-state.schema.json"),
        load_schema("object.schema.json"),
        load_schema("link.schema.json"),
    )


def schema_registry(*schemas: dict[str, Any]) -> Registry:
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas
    )


def project_state_schema_validator(schema: dict[str, Any] | None = None) -> Draft202012Validator:
    project_schema, object_schema, link_schema = load_project_state_schema_bundle()
    if schema is not None:
        project_schema = schema
    return Draft202012Validator(
        project_schema,
        registry=schema_registry(project_schema, object_schema, link_schema),
    )
