# Local development stack

`docker-compose.dev.yml` is a loopback-only development stack. Its default path
starts PostgreSQL, ClamAV, a one-shot Alembic migration, API, scheduler, and
web. The migration provisions the scheduler's constrained PostgreSQL role
before the API and scheduler start. The API uses the implemented local
object-store adapter on the `api-data` named volume, so browser upload URLs
remain reachable at `localhost`; security scanning is enabled and cannot use
the development antivirus bypass.

Start and validate:

```text
docker compose -f docker-compose.dev.yml config --quiet
docker compose -f docker-compose.dev.yml up --build --wait
```

The optional profiles are intentionally not presented as integrated features:

- `--profile durable-queue` starts Redis for future queue-adapter work;
- `--profile s3-emulation` starts MinIO and creates private buckets for adapter
  development.

Do not switch the API to the MinIO container by setting only
`AKC_S3_ENDPOINT_URL`: a URL reachable inside Docker is not necessarily a
presigned upload URL reachable by the host browser. A separate reviewed
internal/public endpoint design is required before that profile can replace the
default local adapter.

Default developer credentials and the deterministic Fernet key are disposable
local values. Override them for any shared machine, never reuse them, and never
copy them into staging or production.

Stop without deleting data:

```text
docker compose -f docker-compose.dev.yml down
```

Deleting named volumes is destructive and intentionally omitted. Use only
synthetic files; local Compose output is not production security, performance,
restore, or release evidence.
