# AI Knowledge Compiler

AI Knowledge Compiler turns PDF, Office, image, web, text, and subtitle sources
into provenance-preserving Portable Markdown, Obsidian vaults, RAG JSONL, and
JSON-LD packages.

The product contract is the versioned Canonical Intermediate Representation
(CIR), routing profile, quality gate, provenance graph, and AI Knowledge
Markdown Profile (AKMP)—not any single model. Native parsers are used first;
only pages that need visual understanding are escalated to an interchangeable
provider.

## Repository status

This repository implements the v2 masterplan as a production-oriented
monorepo. It includes a runnable local vertical slice and deployment adapters.
External GPU, payment, email, and enterprise identity integrations remain
fail-closed until their own credentials and environments are configured.

Key directories:

- `apps/web`: Next.js product experience and processing workspace
- `services/api`: FastAPI control plane
- `services/scheduler`: transactional outbox and queue scheduler
- `workers`: CPU document/export workers and isolated GPU endpoint images
- `packages`: CIR, contracts, routing, quality, exporters, security, telemetry
- `migrations`: PostgreSQL schema, RLS, and lifecycle migrations
- `benchmark`: reproducible golden-corpus harness and evaluation reports
- `infra`: local, Runpod, Terraform, Kubernetes, and monitoring definitions
- `docs`: ADRs, AKMP, security guidance, runbooks, and release evidence

## Local quick start

Requirements:

- Node.js 22+
- pnpm 11+
- Python 3.12 or 3.13
- Docker Desktop for the full PostgreSQL/Redis/MinIO/ClamAV stack

Without Docker, the API can run against its SQLite and local-object-store
development adapters.

```powershell
Copy-Item .env.example .env
.\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m uvicorn akc_api.main:app --reload --port 8000
pnpm dev
```

Open `http://localhost:3000`. API documentation is available at
`http://localhost:8000/docs`.

For the complete environment:

```powershell
docker compose -f docker-compose.dev.yml up --build
```

`uv.lock` and `pnpm-lock.yaml` are committed release inputs. CI and production
images reject stale Python resolution and use frozen pnpm installation; update
either lockfile only as part of an intentional dependency change.

## Safety defaults

- External OCR and model APIs are disabled until the tenant explicitly opts in.
- Private mode denies all external provider egress.
- Customer content is never training data by default.
- Object keys never contain user filenames or email addresses.
- Large S3/R2 uploads use resumable browser-direct multipart transfer; the API
  signs bounded part batches but never relays customer file bytes.
- Model output is untrusted data; it cannot invoke tools or network access.
- Missing provenance prevents AI-derived claims from being exported.

See `docs/IMPLEMENTATION_MATRIX.md` for product requirement status,
`docs/UI_IMPLEMENTATION_MATRIX.md` for the enterprise UI/UX epic trace, and
`docs/release/EXTERNAL_GATES.md` for evidence still required before a
production release claim. Deployment and incident details for direct uploads
are in `docs/runbooks/browser-direct-multipart.md`.
