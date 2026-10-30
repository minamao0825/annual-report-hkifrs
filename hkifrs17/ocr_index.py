"""Optional on-device OCR for scanned PDFs; no report text leaves this machine.

Windows OCR is already provided by the OS. Unsupported platforms or missing
recognizer languages return a warning and leave visual discovery available.
Only navigation consumes these noisy words; amounts are always read from images.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable

import fitz


OCR_INDEX_VERSION = 1


@dataclass(frozen=True)
class OCRIndex:
    pages: tuple[tuple[int, str], ...] = ()
    seconds: float = 0
    cached: bool = False
    warning: str = ""


def _windows_batch(manifest: Path) -> list[dict]:
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(Path(__file__).with_name("windows_ocr.ps1")), "-ManifestPath", str(manifest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-400:] or "The local Windows OCR engine failed.")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]


def scanned_text_index(path: Path, pages: list[int], *, rotations: dict[int, int] | None = None,
                       cache_dir: Path | None = None,
                       progress: Callable[[int, int], None] | None = None) -> OCRIndex:
    """Build a reusable current-file index with three independent local OCR engines."""
    if not pages:
        return OCRIndex()
    if os.name != "nt":
        return OCRIndex(warning="Local Windows OCR is unavailable; visual discovery is retained.")
    started = time.perf_counter()
    from .storage import DATA
    cache_dir = cache_dir or DATA / "page_text_cache"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rotation_key = sorted((int(p), int(angle)) for p, angle in (rotations or {}).items())
    key = hashlib.sha256(json.dumps([digest, OCR_INDEX_VERSION, rotation_key]).encode()).hexdigest()
    cache = cache_dir / (key + ".json")
    saved: dict[int, str] = {}
    try:
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if payload.get("pdf_sha256") == digest and payload.get("version") == OCR_INDEX_VERSION:
                saved = {int(n): text for n, text in payload.get("pages", {}).items() if isinstance(text, str) and text.strip()}
        missing = [n for n in sorted(set(pages)) if n not in saved]
        if not missing:
            return OCRIndex(tuple((n, saved[n]) for n in sorted(set(pages))), time.perf_counter() - started, True)
        errors, done = [], 0
        with tempfile.TemporaryDirectory(prefix="hkfrs17_ocr_") as temporary:
            folder = Path(temporary)
            shards: list[list[dict]] = [[], [], []]
            with fitz.open(path) as pdf:
                for i, n in enumerate(missing):
                    angle = int((rotations or {}).get(n, 0))
                    image = folder / f"page_{n:04d}.png"
                    pdf[n - 1].get_pixmap(matrix=fitz.Matrix(2, 2).prerotate(angle), alpha=False).save(image)
                    shards[i % len(shards)].append({"page": n, "path": str(image)})
            manifests = []
            for i, items in enumerate(shards):
                if items:
                    manifest = folder / f"batch_{i}.json"
                    manifest.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
                    manifests.append(manifest)
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(_windows_batch, manifest): manifest for manifest in manifests}
                for future in as_completed(futures):
                    try:
                        rows = future.result()
                        for row in rows:
                            n, text = int(row["page"]), str(row.get("text", ""))
                            if text.strip():
                                saved[n] = text
                            elif row.get("error"):
                                errors.append(f"p{n}: {row['error']}")
                        done += len(rows)
                    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                        errors.append(str(exc))
                    if progress:
                        progress(min(done, len(missing)), len(missing))
        if saved:
            cache_dir.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".ocr_", suffix=".json", dir=cache_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": OCR_INDEX_VERSION, "pdf_sha256": digest, "pages": saved}, handle, ensure_ascii=False)
                os.replace(name, cache)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        return OCRIndex(tuple((n, saved[n]) for n in sorted(set(pages)) if n in saved),
                        time.perf_counter() - started, False, "; ".join(errors[:3]))
    except (OSError, RuntimeError, ValueError) as exc:
        return OCRIndex(warning=f"Local OCR unavailable: {exc}", seconds=time.perf_counter() - started)
