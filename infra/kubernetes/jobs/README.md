# One-shot jobs

`migrate.yaml` is a template, not a kustomization resource. Before every
deployment, an overlay or release system must:

1. replace the image with the same signed API digest being released;
2. suffix the Job name with the immutable release revision;
3. inject the external-secret-backed database URL;
4. add a narrow database egress policy for the Job label;
5. run and archive the Job logs and exit status before rolling workloads.

Never run concurrent migration Jobs. Destructive or non-backward-compatible
migrations require a separate reviewed expand/migrate/contract plan.
