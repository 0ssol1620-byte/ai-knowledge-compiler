# Third-Party Notices

This file is generated for each production release from the dependency SBOM,
model registry, license snapshots, and manual-review decisions. Placeholder
text MUST NOT ship.

For every distributed or hosted component include:

- component and exact version/revision;
- copyright holder when required;
- license identifier and unmodified license text/link;
- modifications and attribution/UI obligations;
- source-offer or network-use obligations where applicable;
- model weight, code, dataset, and runtime licenses as separate entries.

MinerU and every custom model license require an explicit release decision.
Commercial APIs are disclosed as subprocessors rather than bundled software.

Generated artifacts:

```text
release/notices/THIRD_PARTY_NOTICES.txt
release/notices/licenses/<component>.txt
release/sbom/application.cdx.json
release/sbom/container-<digest>.spdx.json
release/models/license-snapshots.json
```

Release is blocked when a license is absent, commercially incompatible,
changed since approval, or has unresolved attribution, dataset, or service-use
terms.
