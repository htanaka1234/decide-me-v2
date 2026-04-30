#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "decide-me"
DIST_DIR = REPO_ROOT / "dist"

INCLUDE_FILES = (
    "requirements.txt",
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/decide_me.py",
)

INCLUDE_DIRS = (
    "decide_me",
    "references",
    "schemas",
    "templates",
)

EXCLUDE_NAMES = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_RELATIVE_PATHS = {
    "references/migration-from-legacy-model.md",
}
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build the decide-me distribution artifact")
    parser.add_argument("--dist-dir", default=str(DIST_DIR), help="output directory for the staged package and zip")
    args = parser.parse_args(argv)

    dist_dir = Path(args.dist_dir)
    staging_dir = dist_dir / SKILL_NAME
    zip_path = dist_dir / f"{SKILL_NAME}.zip"

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    if zip_path.exists():
        zip_path.unlink()

    dist_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    for relative_path in INCLUDE_FILES:
        copy_file(relative_path, staging_dir)

    for relative_dir in INCLUDE_DIRS:
        copy_tree(relative_dir, staging_dir)

    write_zip(dist_dir, staging_dir, zip_path)
    print(f"Built {_display_path(zip_path)}")
    return 0


def copy_tree(relative_dir: str, staging_dir: Path) -> None:
    source_dir = REPO_ROOT / relative_dir
    for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
        if should_exclude(source):
            continue
        copy_file(source.relative_to(REPO_ROOT).as_posix(), staging_dir)


def copy_file(relative_path: str, staging_dir: Path) -> None:
    source = REPO_ROOT / relative_path
    target = staging_dir / relative_path
    if not source.is_file():
        raise FileNotFoundError(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def should_exclude(path: Path) -> bool:
    relative_path = path.relative_to(REPO_ROOT).as_posix()
    return (
        relative_path in EXCLUDE_RELATIVE_PATHS
        or any(part in EXCLUDE_NAMES for part in path.parts)
        or path.suffix in EXCLUDE_SUFFIXES
    )


def write_zip(dist_dir: Path, staging_dir: Path, zip_path: Path) -> None:
    files = sorted(path for path in staging_dir.rglob("*") if path.is_file())
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in files:
            archive_name = file_path.relative_to(dist_dir).as_posix()
            info = ZipInfo(archive_name, FIXED_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = unix_mode(file_path) << 16
            archive.writestr(info, file_path.read_bytes())


def unix_mode(path: Path) -> int:
    mode = 0o644
    if path.name == "decide_me.py" or path.name == "build_artifact.py":
        mode = 0o755
    return stat.S_IFREG | mode


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
