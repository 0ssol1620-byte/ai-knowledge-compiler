# Terraform Scaffold

This root provisions the six logical storage classes in the architecture:
quarantine, source, working, derived, exports, and audit evidence. Every bucket
is regional, private, KMS-encrypted, and versioned. Bucket names include the AWS
account ID, quarantine CORS accepts only explicit HTTPS origins, working data
has a separately bounded short retention, and audit evidence has
governance-mode Object Lock. It does not create credentials, commit state, or
claim residency outside the selected AWS region.

Tenant-controlled source, derived, and export retention is enforced by the
application's durable deletion sweep. Their bucket lifecycle is only a
3650-day safety net, matching the largest value accepted by
`tenants.data_retention_days`, so infrastructure cannot delete an active
tenant object before its configured deadline. Quarantine and working buckets
remain separate, explicitly short-lived scratch classes.

`deletion_worker_object_purge_policy_arn` is the policy to attach to the
deletion worker's workload role. It permits version inventory, exact version
and delete-marker removal, and multipart aborts for the five purgeable data
buckets. It grants no object-read permission and intentionally excludes the
Object-Locked audit-evidence bucket.

Before apply:

1. Configure a remote encrypted backend with locking outside this directory.
2. Use workload identity, never long-lived keys in variables or files.
3. Review unique bucket names, retention, legal hold, backup, access logging,
   and organization SCPs.
4. Attach the emitted deletion policy only to the deletion workload identity;
   add separate least-privilege policies for other services.
5. Run `terraform fmt -check`, `init -backend=false`, `validate`, policy scan,
   plan review, and production approval.

`upload_allowed_origins` has no default and must list the exact web origins for
the environment. `audit_object_lock_days` is a governance baseline, not a legal
hold policy. Use an approved, separately audited workflow for legal holds and
retention overrides.

`staging.tfvars.example` is non-secret documentation only. Copy it outside the
repository or inject equivalent reviewed values in CI; replace every `.invalid`
placeholder before planning.

Runpod endpoint credentials and model revisions are deliberately not Terraform
variables here. They belong in the deployment secret manager and model
registry, respectively.
