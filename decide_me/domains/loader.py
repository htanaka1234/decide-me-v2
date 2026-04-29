from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Any

import yaml

from decide_me.domains.model import DomainPack, domain_pack_from_dict
from decide_me.domains.registry import DomainRegistry


BUILTIN_PACKS_DIR = Path(__file__).resolve().parent / "packs"
USER_PACKS_DIR_NAME = "domain-packs"
PACK_FILE_SUFFIXES = {".yaml", ".yml", ".json"}


class DomainPackLoadError(ValueError):
    """Raised when domain pack files cannot be loaded into a registry."""


def load_builtin_packs() -> dict[str, DomainPack]:
    return _load_pack_files(_pack_files(BUILTIN_PACKS_DIR))


def load_user_packs(ai_dir: str | Path) -> dict[str, DomainPack]:
    user_pack_dir = Path(ai_dir) / USER_PACKS_DIR_NAME
    if not user_pack_dir.exists():
        return {}
    if not user_pack_dir.is_dir():
        raise DomainPackLoadError(f"user domain pack path is not a directory: {user_pack_dir}")
    return _load_pack_files(_pack_files(user_pack_dir))


def load_domain_registry(ai_dir: str | Path | None = None) -> DomainRegistry:
    builtins = load_builtin_packs()
    user_packs = load_user_packs(ai_dir) if ai_dir is not None else {}
    duplicates = sorted(set(builtins) & set(user_packs))
    if duplicates:
        raise DomainPackLoadError("duplicate domain pack ids: " + ", ".join(duplicates))
    return DomainRegistry({**builtins, **user_packs})


def domain_pack_digest(pack: DomainPack) -> str:
    material = json.dumps(pack.to_dict(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"DP-{digest}"


def _pack_files(directory: Path) -> list[Path]:
    if not directory.exists():
        raise DomainPackLoadError(f"domain pack directory does not exist: {directory}")
    return sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in PACK_FILE_SUFFIXES
    )


def _load_pack_files(paths: Iterable[Path]) -> dict[str, DomainPack]:
    packs: dict[str, DomainPack] = {}
    sources: dict[str, Path] = {}
    for path in paths:
        pack = _load_pack_file(path)
        if pack.pack_id in packs:
            raise DomainPackLoadError(
                f"duplicate domain pack id {pack.pack_id}: {sources[pack.pack_id]} and {path}"
            )
        packs[pack.pack_id] = pack
        sources[pack.pack_id] = path
    return packs


def _load_pack_file(path: Path) -> DomainPack:
    raw = _load_raw_pack(path)
    if not isinstance(raw, dict):
        raise DomainPackLoadError(f"domain pack file must contain an object: {path}")
    try:
        return domain_pack_from_dict(raw)
    except ValueError as exc:
        raise DomainPackLoadError(f"invalid domain pack file {path}: {exc}") from exc


def _load_raw_pack(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DomainPackLoadError(f"cannot read domain pack file {path}: {exc}") from exc

    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DomainPackLoadError(f"cannot parse domain pack file {path}: {exc}") from exc
