"""Fetch foreign calibration/benchmark data with checksums and safe extraction."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "data" / "external"
MANIFEST = ROOT / "data" / "source_manifest.json"
PKP_URL = "https://zenodo.org/records/21700869/files/pkp_intercity_delays_dataset.zip?download=1"
PKP_MD5 = "7628d3022ec6f257864492ef9d1b3262"
DISPLIB_URL = "https://displib.github.io/displib_problems_2025-09-17.zip"
FALLBACK = {
    "nor1_critical_0.json": "https://displib.github.io/problems/nor1_critical_0.json",
    "smi_close_0.json": "https://displib.github.io/problems/smi_close_0.json",
}


def download(url: str, target: Path, expected_md5: str | None = None) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    last_error = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "TurkiSib-data-import/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response, part.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            digest = hashlib.md5()
            sha = hashlib.sha256()
            with part.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    sha.update(chunk)
            if expected_md5 and digest.hexdigest() != expected_md5:
                raise ValueError(f"MD5 mismatch: {digest.hexdigest()} != {expected_md5}")
            os.replace(part, target)
            return {"url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(), "bytes": target.stat().st_size, "md5": digest.hexdigest(), "sha256": sha.hexdigest(), "download_path": str(target.relative_to(ROOT))}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            part.unlink(missing_ok=True)
            if isinstance(exc, ValueError):
                break
            if attempt < 3:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"{url}: {last_error}")


def extract(archive_path: Path, destination: Path, required: set[str] | None = None) -> list[str]:
    extracted = []
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        normalized = []
        for info in members:
            raw = info.filename.replace("\\", "/")
            path = PurePosixPath(raw)
            if raw.startswith("/") or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
                raise ValueError(f"unsafe ZIP member: {info.filename}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"symbolic link in ZIP: {info.filename}")
            normalized.append((info, path))
        if required:
            found = {"/".join(path.parts[i:]) for _, path in normalized for i, part in enumerate(path.parts) if part == "raw"}
            if not required <= found:
                raise ValueError(f"archive missing: {sorted(required - found)}")
        for info, path in normalized:
            if info.is_dir():
                continue
            output = destination.joinpath(*path.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)
            extracted.append(str(output.relative_to(ROOT)))
    return extracted


def main() -> None:
    result = {"kz_demo": {"source_type": "SIMULATED_DEMO", "path": "data/kz_demo", "note": "Bundled Kazakhstan synthetic data; no real train claims"}, "sources": {}}
    pkp = {"source_type": "FOREIGN_CALIBRATION", "licence_attribution": "Marek Kostrz, PKP Intercity delays, Zenodo record 21700869; see archive LICENSE", "url": PKP_URL}
    try:
        target = EXTERNAL / "pkp" / "_downloads" / "pkp_intercity_delays_dataset.zip"
        pkp.update(download(PKP_URL, target, PKP_MD5))
        pkp["extracted_paths"] = extract(target, EXTERNAL / "pkp", {f"raw/{name}.csv" for name in ("stations", "train_services", "run_stops", "railway_lines", "line_speeds", "track_closures")})
        pkp["status"] = "downloaded"
    except Exception as exc:
        pkp.update(status="failed", error=str(exc))
    result["sources"]["pkp"] = pkp
    displib = {"source_type": "FOREIGN_BENCHMARK", "licence_attribution": "DISPLIB project, displib.github.io; see source specification and archive licence", "url": DISPLIB_URL}
    try:
        target = EXTERNAL / "displib" / "_downloads" / "displib_problems_2025-09-17.zip"
        displib.update(download(DISPLIB_URL, target))
        displib["extracted_paths"] = extract(target, EXTERNAL / "displib")
        displib["status"] = "full_downloaded"
    except Exception as exc:
        displib.update(status="full_failed", error=str(exc), fallback={})
        for name, url in FALLBACK.items():
            try:
                path = EXTERNAL / "displib" / "problems" / name
                meta = download(url, path)
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not {"trains", "objective"} <= data.keys():
                    raise ValueError("missing trains/objective root keys")
                displib["fallback"][name] = {**meta, "status": "downloaded", "extracted_path": str(path.relative_to(ROOT))}
            except Exception as fallback_exc:
                displib["fallback"][name] = {"url": url, "status": "failed", "error": str(fallback_exc)}
        if all(item["status"] == "downloaded" for item in displib["fallback"].values()):
            displib["status"] = "fallback_downloaded"
    result["sources"]["displib"] = displib
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value["status"] for key, value in result["sources"].items()}))


if __name__ == "__main__":
    main()
