from __future__ import annotations

import json
from inspect import signature
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver

try:
    from referencing import Registry, Resource
except ModuleNotFoundError:  # pragma: no cover - exercised by older system test environments.
    Registry = Any  # type: ignore[misc, assignment]
    Resource = None  # type: ignore[assignment]


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
    if Resource is None:
        raise RuntimeError("schema_registry requires jsonschema with the referencing package installed")
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas
    )


def schema_validator(root_schema: dict[str, Any], *referenced_schemas: dict[str, Any]) -> Draft202012Validator:
    if Resource is not None and "registry" in signature(Draft202012Validator).parameters:
        return Draft202012Validator(
            root_schema,
            registry=schema_registry(root_schema, *referenced_schemas),
        )

    store = {schema["$id"]: schema for schema in (root_schema, *referenced_schemas) if "$id" in schema}
    return Draft202012Validator(
        root_schema,
        resolver=RefResolver.from_schema(root_schema, store=store),
    )


def project_state_schema_validator(schema: dict[str, Any] | None = None) -> Draft202012Validator:
    project_schema, object_schema, link_schema = load_project_state_schema_bundle()
    if schema is not None:
        project_schema = schema
    return schema_validator(project_schema, object_schema, link_schema)
