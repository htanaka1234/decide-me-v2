#!/usr/bin/env python3
from __future__ import annotations

import shutil
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "decide-me"
DIST_DIR = REPO_ROOT / "dist"
STAGING_DIR = DIST_DIR / SKILL_NAME
ZIP_PATH = DIST_DIR / f"{SKILL_NAME}.zip"

INCLUDE_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/decide_me.py",
    "templates/adr-template.md",
    "templates/plan-template.md",
    "templates/structured-adr-template.md",
)

INCLUDE_DIRS = (
    "decide_me",
    "references",
    "schemas",
)

EXCLUDE_NAMES = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def main() -> int:
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    DIST_DIR.mkdir(exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    for relative_path in INCLUDE_FILES:
        copy_file(relative_path)

    for relative_dir in INCLUDE_DIRS:
        copy_tree(relative_dir)

    write_zip()
    print(f"Built {ZIP_PATH.relative_to(REPO_ROOT)}")
    return 0


def copy_tree(relative_dir: str) -> None:
    source_dir = REPO_ROOT / relative_dir
    for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
        if should_exclude(source):
            continue
        copy_file(source.relative_to(REPO_ROOT).as_posix())


def copy_file(relative_path: str) -> None:
    source = REPO_ROOT / relative_path
    target = STAGING_DIR / relative_path
    if not source.is_file():
        raise FileNotFoundError(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDE_NAMES for part in path.parts) or path.suffix in EXCLUDE_SUFFIXES


def write_zip() -> None:
    files = sorted(path for path in STAGING_DIR.rglob("*") if path.is_file())
    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in files:
            archive_name = file_path.relative_to(DIST_DIR).as_posix()
            info = ZipInfo(archive_name, FIXED_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = unix_mode(file_path) << 16
            archive.writestr(info, file_path.read_bytes())


def unix_mode(path: Path) -> int:
    mode = stat.S_IMODE(path.stat().st_mode)
    if path.name == "decide_me.py" or path.name == "build_artifact.py":
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    return stat.S_IFREG | mode


if __name__ == "__main__":
    raise SystemExit(main())
