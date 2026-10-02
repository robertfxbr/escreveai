"""Install app dependencies only when their requirements change."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


REQUIREMENTS = ("requirements.txt", "requirements-vision.txt")


def ensure_dependencies(project_dir: Path, python_executable: Path) -> bool:
    project_dir = Path(project_dir)
    digest = hashlib.sha256()
    for name in REQUIREMENTS:
        digest.update(name.encode("utf-8"))
        digest.update((project_dir / name).read_bytes())
    fingerprint = digest.hexdigest()
    marker = project_dir / ".venv" / "requirements.sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == fingerprint:
        return False

    subprocess.run(
        [str(python_executable), "-m", "pip", "install", "-r", "requirements-vision.txt"],
        cwd=project_dir, check=True,
    )
    marker.write_text(fingerprint, encoding="ascii")
    return True


if __name__ == "__main__":
    try:
        if ensure_dependencies(Path(__file__).resolve().parent, Path(sys.executable)):
            print("Dependências instaladas ou atualizadas.")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Não foi possível preparar as dependências: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
