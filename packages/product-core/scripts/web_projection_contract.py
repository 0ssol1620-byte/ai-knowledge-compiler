"""Cross-language contract: the site's own request builder and projection around this Core.

    uv run python packages/product-core/scripts/web_projection_contract.py \
        --web-checkout D:/CodexProjects/tavonel-self-service-launch-20260928

The site's `nextjs/lib/core-runtime-v2.ts` is bundled unmodified with the site's own esbuild,
then: site builds the request -> signed POST to this Core's FastAPI app -> site projects the
response. A projection that returns null is the production CORE_V2_PROJECTION_INVALID refusal.
`web_retry` runs the site's real `dispatchProductCoreV2` twice (a fresh requestId and time each,
the site's own receipt checks) against this Core served on 127.0.0.1: a retry of the same work
must return the same World, receipted to the retry.
Synthetic English and Korean documents only; loopback only, a local test secret, no credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from akc_product_core.api import create_product_core_app
from akc_product_core.auth import sign_product_core_request
from fastapi.testclient import TestClient

_NODE = shutil.which("node") or "node"
SECRET = b"web-projection-contract-local-secret-32b"
RELEASE = "sha256:" + hashlib.sha256(b"web-projection-contract").hexdigest()
WORKSPACE = "pilot-contract01"
CORPORA = {
    "english": ["Revenue for fiscal 2025 was 120 million dollars according to the annual report."],
    "korean": ["2025년 매출액은 1200억원이며 영업이익은 150억원으로 증가하였다."],
    "mixed": [
        "Revenue for fiscal 2025 was 120 million dollars according to the annual report.",
        "2025년 매출액은 1200억원이며 영업이익은 150억원으로 증가하였다.",
    ],
    # Entities, `mentions` relations and a contradiction: must project as review_required.
    "entities_and_contradiction": [
        "2025 revenue was 100 million won. TAVONEL Research Institute reported the result.",
        "2025 revenue was 120 million won. 한국은행은 공시했다.",
    ],
    # Negative: the source key does not name the digest that was read.
    "non_content_addressed_key": ["2025년 매출액은 1200억원이다. Revenue was 120 billion won."],
}
EXPECTED_LIFECYCLE = {
    "english": "candidate",
    "korean": "candidate",
    "mixed": "candidate",
    "entities_and_contradiction": "review_required",
    "non_content_addressed_key": "review_required",
}
ENTRY = """
import {{ readFileSync }} from "node:fs";
import {{
  buildProductCoreV2Request, dispatchProductCoreV2, projectProductCoreV2Candidate,
}} from {module};
const {{ CONTRACT_MODE: mode, CONTRACT_INPUT: path, CONTRACT_EXTRA: extra }} = process.env;
const input = JSON.parse(readFileSync(path, "utf8"));
if (mode === "request") {{
  const now = new Date("2026-09-30T00:00:00Z");
  const request = buildProductCoreV2Request({workspace}, input, now, "core-contract-" + extra);
  process.stdout.write(JSON.stringify(request));
}} else if (mode === "retry") {{
  const env = {{ url: process.env.CONTRACT_CORE_URL, hmac: process.env.CONTRACT_CORE_HMAC }};
  const attempts = [];
  for (const offsetMs of [120000, 0]) {{
    const now = new Date(Date.now() - offsetMs);
    const dispatched = await dispatchProductCoreV2(env, {workspace}, input, now);
    attempts.push(dispatched.ok ? {{
      ok: true,
      requestId: dispatched.result.receipt.requestId,
      worldStateId: dispatched.result.candidate.worldStateId,
      outputSha256: dispatched.result.receipt.outputSha256,
      projected: projectProductCoreV2Candidate(dispatched.result, input) !== null,
    }} : {{ ok: false, code: dispatched.code }});
  }}
  process.stdout.write(JSON.stringify(attempts));
}} else {{
  const response = JSON.parse(readFileSync(extra, "utf8"));
  const artifact = projectProductCoreV2Candidate(response, input);
  process.stdout.write(JSON.stringify(artifact === null ? null : {{
    lifecycle: artifact.lifecycle, candidatePromotion: artifact.candidatePromotion,
    validation: artifact.validation, nodes: artifact.ontology.nodes.length,
    edges: artifact.ontology.edges.map((edge) => edge.type),
    evidenceNodes: artifact.ontology.nodes.filter((node) => node.kind === "Evidence").length,
    documents: artifact.sourceDocuments.map((document) => document.documentId),
  }}));
}}
"""


def _documents(
    texts: list[str], *, content_addressed: bool, confidence: float = 0.98
) -> list[dict[str, object]]:
    rows = []
    for index, text in enumerate(texts):
        version = hashlib.sha256(text.encode("utf-8")).hexdigest()
        document_id = f"doc{index}-{version[:8]}"
        prefix = f"immutable/{WORKSPACE}/{WORKSPACE}/{document_id}/{version}"
        rows.append(
            {
                "documentId": document_id,
                "versionKey": version,
                "sanitizedKey": f"{prefix}/sanitized.pdf",
                "ocrJsonKey": f"{prefix}/ocr.json",
                "pageCount": 1,
                "text": text,
                "inputSha256": f"sha256:{version}",
                "sourceImmutableKey": (
                    f"{prefix}/sanitized.pdf"
                    if content_addressed
                    else f"immutable/{WORKSPACE}/{WORKSPACE}/{document_id}/latest/sanitized.pdf"
                ),
                "regions": [
                    {
                        "regionId": f"r-{document_id}-0",
                        "pageIndex0": 0,
                        "pageNumber1": 1,
                        "order": 0,
                        "blockType": "paragraph",
                        "text": text,
                        "bbox1000": [80, 100, 920, 220],
                        "confidence": confidence,
                        "authority": "official",
                    }
                ],
            }
        )
    return rows


def _bundle(web: Path, work: Path) -> Path:
    module = (web / "nextjs/lib/core-runtime-v2.ts").resolve()
    entry = work / "entry.ts"
    entry.write_text(
        ENTRY.format(module=json.dumps(module.as_posix()), workspace=json.dumps(WORKSPACE)),
        encoding="utf-8",
    )
    esbuild = next(
        (web / "nextjs/node_modules/.pnpm").glob("esbuild@*/node_modules/esbuild/bin/esbuild")
    )
    out = work / "bundle.mjs"
    subprocess.run(  # noqa: S603 -- fixed argv, local files only
        [
            _NODE,
            str(esbuild),
            str(entry),
            "--bundle",
            "--platform=node",
            "--format=esm",
            f"--outfile={out}",
            "--log-level=warning",
        ],
        check=True,
    )
    return out


def _node(
    bundle: Path, mode: str, documents: Path, extra: str, env: dict[str, str] | None = None
) -> bytes:
    # Imported rather than executed: the bundle inlines validate.mjs, whose CLI entry point
    # would otherwise take this process for its own main module.
    return subprocess.run(  # noqa: S603 -- fixed argv, local files only
        [_NODE, "--input-type=module", "-e", f"await import({json.dumps(bundle.as_uri())})"],
        check=True,
        stdout=subprocess.PIPE,
        env={
            **os.environ,
            "CONTRACT_MODE": mode,
            "CONTRACT_INPUT": str(documents),
            "CONTRACT_EXTRA": extra,
            **(env or {}),
        },
    ).stdout


def _web_retry(bundle: Path, work: Path) -> list[dict[str, object]]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.05)
        documents = work / "retry-documents.json"
        documents.write_text(
            # confidence 1 and an official source: integral numbers in the receipted World.
            json.dumps(
                _documents(CORPORA["korean"], content_addressed=True, confidence=1),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        attempts = json.loads(
            _node(
                bundle,
                "retry",
                documents,
                "",
                {
                    "CONTRACT_CORE_URL": f"http://127.0.0.1:{port}",
                    "CONTRACT_CORE_HMAC": SECRET.decode(),
                },
            )
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert isinstance(attempts, list)
    return attempts


def run(web: Path) -> dict[str, object]:
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        bundle = _bundle(web, work)
        for name, texts in CORPORA.items():
            documents = work / f"{name}-documents.json"
            documents.write_text(
                json.dumps(
                    _documents(texts, content_addressed=name != "non_content_addressed_key"),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            body = _node(bundle, "request", documents, name)
            request_id = json.loads(body)["requestId"]
            headers = sign_product_core_request(
                body=body,
                request_id=request_id,
                timestamp=int(datetime.now(tz=UTC).timestamp()),
                secret=SECRET,
            )
            response = client.post(
                "/v2/compile", content=body, headers={"content-type": "application/json", **headers}
            )
            if response.status_code != 200:
                results[name] = {"coreStatus": response.status_code, "body": response.json()}
                continue
            response_file = work / f"{name}-response.json"
            response_file.write_text(response.text, encoding="utf-8")
            projected = json.loads(_node(bundle, "project", documents, str(response_file)))
            payload = response.json()
            results[name] = {
                "coreStatus": payload["status"],
                "coreValidation": payload["candidate"]["validation"],
                "reviewReasons": payload["candidate"]["reviewReasons"],
                "projection": projected if projected is not None else "CORE_V2_PROJECTION_INVALID",
            }
        results["web_retry"] = _web_retry(bundle, work)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-checkout", type=Path, required=True)
    args = parser.parse_args()
    results = run(args.web_checkout)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(
        isinstance(row, dict)
        and isinstance(row.get("projection"), dict)
        and row["projection"]["candidatePromotion"] is False
        and row["projection"]["lifecycle"] == EXPECTED_LIFECYCLE[name]
        for name, row in results.items()
        if name != "web_retry"
    )
    retry = results["web_retry"]
    ok = (
        ok
        and isinstance(retry, list)
        and len(retry) == 2
        and all(attempt["ok"] and attempt["projected"] for attempt in retry)
        and retry[0]["requestId"] != retry[1]["requestId"]
        and retry[0]["worldStateId"] == retry[1]["worldStateId"]
        and retry[0]["outputSha256"] == retry[1]["outputSha256"]
    )
    negative = results["non_content_addressed_key"]
    ok = (
        ok
        and isinstance(negative, dict)
        and negative["projection"]["validation"]["immutableInputsOnly"] is False
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
