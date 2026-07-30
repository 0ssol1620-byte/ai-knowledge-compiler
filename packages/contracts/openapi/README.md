# OpenAPI compatibility baseline

`openapi-v1.json` is the reviewed public API baseline. CI runs
`scripts/check_openapi_compat.py` and rejects removed paths or operations,
new required request inputs, narrowed request types/enums/ranges, removed
response fields/statuses/media types, and widened response contracts.

An intentional breaking change requires a new API version and migration plan.
Do not update this baseline merely to make CI pass. For a reviewed compatible
addition, regenerate it explicitly:

```bash
python scripts/check_openapi_compat.py --update-baseline
python scripts/check_openapi_compat.py
```

The generator uses fixed test settings. It does not connect to a database,
start the application lifespan, or include development verification-token
routes.
