from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_TIMEOUT_SECONDS = 30


class BuiltArtifact:
    def __init__(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.dist_dir = self.root / "dist"
        self.extract_dir = self.root / "extracted"
        self.zip_path = self._build()
        self._skill_dir: Path | None = None

    def __enter__(self) -> BuiltArtifact:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        self._temp_dir.cleanup()

    def open_archive(self) -> ZipFile:
        return ZipFile(self.zip_path)

    def names(self) -> set[str]:
        with self.open_archive() as archive:
            return set(archive.namelist())

    def read_text(self, name: str) -> str:
        with self.open_archive() as archive:
            return archive.read(name).decode("utf-8")

    def modes(self) -> dict[str, int]:
        with self.open_archive() as archive:
            return {name: archive.getinfo(name).external_attr >> 16 for name in archive.namelist()}

    def extract_once(self) -> Path:
        if self._skill_dir is None:
            if self.extract_dir.exists():
                shutil.rmtree(self.extract_dir)
            self.extract_dir.mkdir(parents=True)
            with self.open_archive() as archive:
                archive.extractall(self.extract_dir)
            self._skill_dir = self.extract_dir / "decide-me"
        return self._skill_dir

    def run_packaged_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        skill_dir = self.extract_once()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(skill_dir)
        result = subprocess.run(
            [sys.executable, str(skill_dir / "scripts" / "decide_me.py"), *args],
            cwd=skill_dir,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"Packaged CLI failed with {result.returncode}: {' '.join(args)}\n{result.stdout}"
            )
        return result

    def run_packaged_json(self, *args: str) -> dict[str, Any]:
        result = self.run_packaged_cli(*args, check=True)
        if not result.stdout.strip():
            raise AssertionError(
                f"Packaged CLI produced no JSON stdout: {' '.join(args)}"
            )
        return json.loads(result.stdout)

    def _build(self) -> Path:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        subprocess.run(
            [sys.executable, "scripts/build_artifact.py", "--dist-dir", str(self.dist_dir)],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        return self.dist_dir / "decide-me.zip"
