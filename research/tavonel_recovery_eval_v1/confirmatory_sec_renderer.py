#!/usr/bin/env python3
"""Qualified deterministic SEC HTML -> page-image renderer for TAVONEL-R.

The renderer is deliberately separate from source acquisition.  A filing may
enter the SEC page candidate pool only after this instrument has emitted and
re-verified an immutable qualification receipt.

Pipeline:
  SEC primary HTML + local submission assets
    -> pinned local Chrome headless print-to-PDF (network disabled)
    -> isolated pypdfium2 + Pillow rasterization
    -> deterministic PNG page bytes + per-page SHA-256

Chrome/PDFium versions alone are not treated as proof of reproducibility: the
qualification also renders the same synthetic document twice and requires the
complete ordered page-hash sequence to match exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRIVATE_ROOT = HERE / ".private" / "sec-renderer-v1"
DEFAULT_VENV = PRIVATE_ROOT / "venv"
DEFAULT_RECEIPT = HERE / "receipts" / "sec-renderer-qualification.json"

PYPDFIUM2_VERSION = "5.13.0"
PILLOW_VERSION = "12.3.0"
RENDER_SCALE = 2.0
PAGE_CSS = (
    "@page { size: letter; margin: 0.5in; } "
    "html, body { background: white !important; print-color-adjust: exact; "
    "-webkit-print-color-adjust: exact; }"
)
RECEIPT_SCHEMA = "tavonel.recovery.sec_renderer_qualification.v1"
PAGE_MANIFEST_SCHEMA = "tavonel.recovery.sec_rendered_pages.v1"

_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SecRendererRefused(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_once(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise SecRendererRefused(f"immutable renderer artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def chrome_path() -> Path:
    explicit = str(os.environ.get("TAVONEL_SEC_CHROME", "")).strip()
    candidates = [
        Path(explicit) if explicit else None,
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise SecRendererRefused("pinned SEC renderer requires a local Chrome executable")


def renderer_python(venv: Path = DEFAULT_VENV) -> Path:
    candidate = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not candidate.is_file():
        raise SecRendererRefused(f"isolated SEC renderer Python is absent: {candidate}")
    return candidate.resolve()


def _chrome_version(path: Path) -> str:
    if os.name == "nt":
        quoted = str(path).replace("'", "''")
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-Item -LiteralPath '{quoted}').VersionInfo.FileVersion",
        ]
    else:
        command = [str(path), "--version"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        raise SecRendererRefused("Chrome version could not be observed")
    return version


def _python_runtime_versions(python_exe: Path) -> dict[str, str]:
    code = (
        "import importlib.metadata,json,sys;"
        "print(json.dumps({'python':sys.version.split()[0],"
        "'pypdfium2':importlib.metadata.version('pypdfium2'),"
        "'pillow':importlib.metadata.version('Pillow')},sort_keys=True))"
    )
    result = subprocess.run(  # noqa: S603
        [str(python_exe), "-c", code], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SecRendererRefused("isolated SEC renderer dependencies are not importable")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SecRendererRefused("isolated renderer version evidence is malformed") from exc
    if value.get("pypdfium2") != PYPDFIUM2_VERSION or value.get("pillow") != PILLOW_VERSION:
        raise SecRendererRefused("isolated SEC renderer dependency versions drifted")
    return {str(key): str(item) for key, item in value.items()}


def _prepare_html(source: Path, target: Path) -> None:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source.read_text(encoding="latin-1")
    style = f'<style id="tavonel-sec-renderer">{PAGE_CSS}</style>'
    head = re.search(r"<head(?:\s[^>]*)?>", text, re.IGNORECASE)
    if head is not None:
        text = text[: head.end()] + style + text[head.end() :]
    else:
        text = f"<html><head>{style}</head><body>{text}</body></html>"
    target.write_text(text, encoding="utf-8", newline="\n")


def _rasterize_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Called under the isolated renderer Python; imports stay out of repo venv."""

    import pypdfium2 as pdfium  # type: ignore[import-not-found]

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    paths: list[Path] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                bitmap = page.render(scale=RENDER_SCALE, rev_byteorder=True)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    path = output_dir / f"page_{index + 1:04d}.png"
                    image.save(path, format="PNG", optimize=False, compress_level=6)
                    paths.append(path)
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        pdf.close()
    if not paths:
        raise SecRendererRefused("PDFium produced no SEC page images")
    return paths


def _rasterize_subprocess(pdf_path: Path, output_dir: Path, python_exe: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [
            str(python_exe),
            str(Path(__file__).resolve()),
            "rasterize-pdf",
            "--pdf",
            str(pdf_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        raise SecRendererRefused(
            "PDFium rasterization failed: " + (result.stderr.strip() or result.stdout.strip())[-1000:]
        )


def _render_once(source_html: Path, output_dir: Path, *, receipt: Mapping[str, Any]) -> dict[str, Any]:
    chrome = Path(str(receipt["chrome"]["path"]))
    python_exe = Path(str(receipt["rasterizer"]["python_path"]))
    output_dir.mkdir(parents=True, exist_ok=False)
    # Keep the prepared HTML beside the source so relative SEC submission
    # assets (images/styles) resolve exactly as they do for the primary filing.
    # The sibling is temporary and is always removed after Chrome exits.
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".tavonel-render.html", dir=source_html.parent, delete=False
    )
    handle.close()
    prepared = Path(handle.name)
    _prepare_html(source_html, prepared)
    pdf_path = output_dir / "render.pdf"
    profile = output_dir / "chrome-profile"
    command = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        "--no-pdf-header-footer",
        "--allow-file-access-from-files",
        "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE localhost",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={pdf_path}",
        prepared.resolve().as_uri(),
    ]
    try:
        result = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, check=False, timeout=300
        )
    finally:
        prepared_sha256 = _sha_file(prepared) if prepared.is_file() else None
        prepared.unlink(missing_ok=True)
    if result.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise SecRendererRefused(
            "Chrome print-to-PDF failed: " + (result.stderr.strip() or result.stdout.strip())[-1000:]
        )
    page_root = output_dir / "pages"
    _rasterize_subprocess(pdf_path, page_root, python_exe)
    pages = sorted(page_root.glob("page_*.png"))
    return {
        "page_count": len(pages),
        "page_sha256": [_sha_file(path) for path in pages],
        "prepared_html_sha256": prepared_sha256,
    }


def _runtime_identity(venv: Path = DEFAULT_VENV) -> dict[str, Any]:
    chrome = chrome_path()
    python_exe = renderer_python(venv)
    versions = _python_runtime_versions(python_exe)
    return {
        "chrome": {
            "path": str(chrome),
            "version": _chrome_version(chrome),
            "sha256": _sha_file(chrome),
        },
        "rasterizer": {
            "python_path": str(python_exe),
            "python_sha256": _sha_file(python_exe),
            **versions,
        },
        "renderer_module_sha256": _sha_file(Path(__file__).resolve()),
        "settings": {
            "page_css": PAGE_CSS,
            "render_scale": RENDER_SCALE,
            "output_format": "PNG-RGB-compress_level_6",
            "network_during_render": False,
        },
    }


def qualify(*, venv: Path = DEFAULT_VENV, output: Path = DEFAULT_RECEIPT) -> dict[str, Any]:
    if output.exists():
        raise SecRendererRefused("SEC renderer qualification receipt already exists")
    identity = _runtime_identity(venv)
    synthetic = """<!doctype html><html><head><meta charset='utf-8'></head><body>
<h1>TAVONEL SEC renderer qualification</h1>
<p>Revenue 1,234.56 — 2026-08-30</p>
<table border='1'><tr><th>A</th><th>B</th></tr><tr><td>10-Q</td><td>$42</td></tr></table>
<div style='break-before:page'><h2>Second page</h2><p>Critical token: 0001193125-26-000001</p></div>
</body></html>"""
    with tempfile.TemporaryDirectory(prefix="tavonel-sec-renderer-") as raw:
        root = Path(raw)
        source = root / "smoke.html"
        source.write_text(synthetic, encoding="utf-8", newline="\n")
        first = _render_once(source, root / "first", receipt=identity)
        second = _render_once(source, root / "second", receipt=identity)
    if first["page_count"] != second["page_count"] or first["page_sha256"] != second["page_sha256"]:
        raise SecRendererRefused("SEC renderer repeatability smoke produced different page bytes")
    if first["page_count"] < 2:
        raise SecRendererRefused("SEC renderer smoke did not exercise a multi-page document")
    body = {
        "schema": RECEIPT_SCHEMA,
        "state": "RENDERER_QUALIFIED",
        **identity,
        "repeatability_smoke": {
            "page_count": first["page_count"],
            "page_sha256": first["page_sha256"],
            "repeat_runs": 2,
            "exact_page_bytes_equal": True,
            "fresh_confirmatory_observation": False,
        },
        "scientific_outcomes_observed": False,
    }
    report = {**body, "renderer_qualification_digest": _digest(body)}
    _write_once(output, report)
    return report


def verify_receipt(path: Path = DEFAULT_RECEIPT) -> dict[str, Any]:
    if not path.is_file():
        raise SecRendererRefused("SEC renderer qualification receipt is missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    body = {key: item for key, item in value.items() if key != "renderer_qualification_digest"}
    if value.get("schema") != RECEIPT_SCHEMA or value.get("state") != "RENDERER_QUALIFIED":
        raise SecRendererRefused("SEC renderer qualification receipt state is invalid")
    if _digest(body) != value.get("renderer_qualification_digest"):
        raise SecRendererRefused("SEC renderer qualification digest does not recompute")
    current = _runtime_identity(Path(str(value["rasterizer"]["python_path"])).parents[1])
    for section in ("chrome", "rasterizer", "renderer_module_sha256", "settings"):
        if current[section] != value[section]:
            raise SecRendererRefused(f"SEC renderer live identity drifted: {section}")
    return value


def render_document(
    *, source_html: Path, output_dir: Path, receipt_path: Path = DEFAULT_RECEIPT
) -> dict[str, Any]:
    receipt = verify_receipt(receipt_path)
    result = _render_once(source_html, output_dir, receipt=receipt)
    body = {
        "schema": PAGE_MANIFEST_SCHEMA,
        "renderer_qualification_digest": receipt["renderer_qualification_digest"],
        "source_html_sha256": _sha_file(source_html),
        "page_count": result["page_count"],
        "page_sha256": result["page_sha256"],
    }
    return {**body, "rendered_pages_digest": _digest(body)}


def plan() -> dict[str, Any]:
    chrome = chrome_path()
    return {
        "schema": "tavonel.recovery.sec_renderer_plan.v1",
        "chrome_path": str(chrome),
        "chrome_sha256": _sha_file(chrome),
        "chrome_version": _chrome_version(chrome),
        "pypdfium2_version": PYPDFIUM2_VERSION,
        "pillow_version": PILLOW_VERSION,
        "render_scale": RENDER_SCALE,
        "network_during_render": False,
        "qualification_required_before_fresh_sec_pages": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    qualify_parser = sub.add_parser("qualify")
    qualify_parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    sub.add_parser("verify")
    raster = sub.add_parser("rasterize-pdf")
    raster.add_argument("--pdf", type=Path, required=True)
    raster.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = plan()
        elif args.command == "qualify":
            value = qualify(venv=args.venv)
        elif args.command == "verify":
            value = verify_receipt()
        else:
            paths = _rasterize_pdf(args.pdf, args.output_dir)
            value = {"page_count": len(paths), "page_sha256": [_sha_file(path) for path in paths]}
    except SecRendererRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())