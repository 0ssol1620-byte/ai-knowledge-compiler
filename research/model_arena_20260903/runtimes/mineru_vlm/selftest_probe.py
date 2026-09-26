"""Bootstrap-time probes for the mineru_vlm layout defect (ARENA_CONTRACT D73).

On pod o6eq3bm2ei7r9c (2026-09-04) the vendor CLI parsed the synthetic warm-up
page correctly in its own process, and the arena adapter -- same pod, same
weights, same engine, same image -- got the layout answer ``]]<|><|><|><|>``
in the worker process. The call sites differ in only a few ways, and this
script runs the adapter's exact ``do_parse`` call under each of them, in a
fresh process, so the READY-time log (D71) says which one flips the answer:

    adapter-args         the adapter's kwargs (batch_size=1, f_* flags), main thread
    adapter-args-env     + the adapter's env (OMP_NUM_THREADS=1,
                           MINERU_API_MAX_CONCURRENT_REQUESTS=1)
    adapter-args-thread  + run from a non-main thread, the way the worker's HTTP handler does
    cli-args             the CLI's defaults through the same in-process do_parse

Each probe prints one ``[arena] probe <mode>: ...`` line with the markdown byte
count and the first characters of the layout stage's raw answer (mineru_vl_utils
logs it at DEBUG, so the loguru sink is set to DEBUG here exactly as D64 does in
the adapter). Evidence only: nothing here changes what the canary measures.
"""

from __future__ import annotations

import io
import os
import re
import sys
import threading
from pathlib import Path

RAW_RE = re.compile(r"Layout raw output:\s*\n?(.*)")


def _debug_sink(buffer: io.StringIO) -> None:
    try:
        from loguru import logger  # type: ignore[import-not-found]

        logger.remove()
        logger.add(sys.stderr, level="DEBUG", enqueue=False)
        logger.add(buffer, level="DEBUG", enqueue=False)
    except Exception as exc:
        print(f"[arena] probe: loguru sink not installed ({type(exc).__name__}: {exc})")


def _engine_ids() -> str:
    """Which backend string each path resolves 'auto' to."""

    from mineru.utils.engine_utils import get_vlm_engine  # type: ignore[import-not-found]

    sync = get_vlm_engine(inference_engine="auto", is_async=False)
    aio = get_vlm_engine(inference_engine="auto", is_async=True)
    return f"sync={sync} async={aio}"


def _aio_parse(mode: str, image: Path, out: Path) -> None:
    """The server's path: aio_do_parse, which picks the async engine."""

    import asyncio

    from mineru.cli.common import aio_do_parse, read_fn  # type: ignore[import-not-found]

    pdf_bytes = read_fn(image, "png")
    kwargs = dict(
        output_dir=str(out),
        pdf_file_names=[mode],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=["ch"],
        backend="vlm-engine",
    )
    if mode == "aio-adapter-args":
        kwargs.update(
            formula_enable=True,
            table_enable=True,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=True,
            f_dump_model_output=True,
            f_dump_orig_pdf=False,
            f_dump_content_list=True,
            batch_size=1,
        )
    asyncio.run(aio_do_parse(**kwargs))


def _do_parse(mode: str, image: Path, out: Path) -> None:
    if mode.startswith("aio-"):
        _aio_parse(mode, image, out)
        return
    from mineru.cli.common import do_parse, read_fn  # type: ignore[import-not-found]

    pdf_bytes = read_fn(image, "png")  # the adapter's two-argument call
    if mode.startswith("adapter-args"):
        do_parse(
            output_dir=str(out),
            pdf_file_names=[mode],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=["ch"],
            backend="vlm-engine",
            formula_enable=True,
            table_enable=True,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=True,
            f_dump_model_output=True,
            f_dump_orig_pdf=False,
            f_dump_content_list=True,
            batch_size=1,
        )
    else:
        do_parse(
            output_dir=str(out),
            pdf_file_names=[mode],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=["ch"],
            backend="vlm-engine",
        )


def main() -> int:
    mode = sys.argv[1]
    image = Path(sys.argv[2])
    out = Path(sys.argv[3])
    if mode == "engine-ids":
        try:
            answer = _engine_ids()
        except Exception as exc:
            answer = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"[arena] probe engine-ids: status=ok markdown_bytes=-1 "
              f"format_warnings=0 raw={answer}", flush=True)
        return 0
    if mode == "adapter-args-env" or mode == "adapter-args-thread":
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["MINERU_API_MAX_CONCURRENT_REQUESTS"] = "1"
    buffer = io.StringIO()
    _debug_sink(buffer)
    failure: list[BaseException] = []

    def work() -> None:
        try:
            _do_parse(mode, image, out)
        except BaseException as exc:
            failure.append(exc)

    if mode == "adapter-args-thread":
        thread = threading.Thread(target=work, name="arena-probe", daemon=False)
        thread.start()
        thread.join()
    else:
        work()

    raw = ""
    match = RAW_RE.search(buffer.getvalue())
    if match:
        raw = match.group(1).strip().splitlines()[0][:160] if match.group(1).strip() else ""
    md_files = sorted(out.rglob("*.md"))
    md_bytes = md_files[0].stat().st_size if md_files else -1
    warnings = buffer.getvalue().count("does not match expected format")
    status = "ok" if not failure else f"{type(failure[0]).__name__}: {str(failure[0])[:200]}"
    print(
        f"[arena] probe {mode}: status={status} markdown_bytes={md_bytes} "
        f"format_warnings={warnings} raw={raw or '<none logged>'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
