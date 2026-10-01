"""Import the supplied Kazakhstan demo package without trusting archive paths."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "kz_demo"
REQUIRED = ("KZ/blocks.csv", "KZ/train_services.csv", "KZ/run_stops.csv", "mock/signals.csv", "mock/switches.csv", "scenarios/scenarios.json", "scenarios/incidents.json", "scenarios/initial_state.json")


def safe_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, Path]]:
    members = []
    for info in archive.infolist():
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        if raw.startswith("/") or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
            raise ValueError(f"unsafe ZIP member: {info.filename}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError(f"symbolic link in ZIP: {info.filename}")
        parts = path.parts
        start = next((i for i, part in enumerate(parts) if part in {"KZ", "mock", "scenarios"}), None)
        if start is not None and len(parts) > start + 1 and not info.is_dir():
            members.append((info, Path(*parts[start:])))
    names = {p.as_posix() for _, p in members}
    if not set(REQUIRED) <= names:
        raise ValueError(f"ZIP missing required files: {sorted(set(REQUIRED) - names)}")
    return members


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, help="Optional source archive; otherwise use existing repository data")
    args = parser.parse_args()
    if args.zip:
        with zipfile.ZipFile(args.zip) as archive:
            members = safe_members(archive)
            for info, rel in members:
                out = TARGET / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, out.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        source = str(args.zip.resolve())
    else:
        for rel in REQUIRED:
            if not (ROOT / "data" / rel).is_file():
                raise FileNotFoundError(ROOT / "data" / rel)
        for folder in ("KZ", "mock", "scenarios"):
            shutil.copytree(ROOT / "data" / folder, TARGET / folder, dirs_exist_ok=True)
        shutil.copy2(ROOT / "README.md", TARGET / "README.md")
        shutil.copy2(ROOT / "validation.json", TARGET / "validation.json")
        source = "repository bundled data"
    for rel in REQUIRED:
        if not (TARGET / rel).is_file():
            raise ValueError(f"import missing {rel}")
    print(json.dumps({"source": source, "target": str(TARGET), "validated": len(REQUIRED)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
