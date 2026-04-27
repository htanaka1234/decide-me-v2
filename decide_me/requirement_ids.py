from __future__ import annotations

import re
from typing import Any


REQUIREMENT_ID_PATTERN = re.compile(r"^R-[0-9]{3,}$")


def is_requirement_id(value: Any) -> bool:
    return isinstance(value, str) and REQUIREMENT_ID_PATTERN.fullmatch(value) is not None


def require_requirement_id(value: Any, label: str = "requirement_id") -> str:
    if not is_requirement_id(value):
        raise ValueError(f"{label} must match R-001 with at least three digits")
    return value


def requirement_id_number(requirement_id: str) -> int:
    require_requirement_id(requirement_id)
    return int(requirement_id[2:])


def format_requirement_id(number: int) -> str:
    if number < 1:
        raise ValueError("requirement ID number must be positive")
    return f"R-{number:03d}"


def next_requirement_id(decisions: list[dict[str, Any]]) -> str:
    numbers = [
        requirement_id_number(decision["requirement_id"])
        for decision in decisions
        if decision.get("requirement_id")
    ]
    return format_requirement_id(max(numbers, default=0) + 1)
