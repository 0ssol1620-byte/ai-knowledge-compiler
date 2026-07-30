data "aws_caller_identity" "current" {}

locals {
  bucket_prefix = "${var.project_name}-${var.environment}-${data.aws_caller_identity.current.account_id}"
  purgeable_bucket_keys = toset([
    "quarantine",
    "source",
    "working",
    "derived",
    "exports",
  ])
  buckets = {
    quarantine = {
      expiry_days = 1
    }
    source = {
      expiry_days = var.retention_days
    }
    working = {
      expiry_days = var.working_retention_days
    }
    derived = {
      expiry_days = var.retention_days
    }
    exports = {
      expiry_days = var.retention_days
    }
    audit-evidence = {
      expiry_days = 365
    }
  }
}

data "aws_iam_policy_document" "deletion_worker_object_purge" {
  statement {
    sid    = "InventoryExactKeyVersions"
    effect = "Allow"
    actions = [
      "s3:GetBucketVersioning",
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [
      for key in local.purgeable_bucket_keys : aws_s3_bucket.data[key].arn
    ]
  }

  statement {
    sid    = "PurgeObjectVersionsAndMultipartUploads"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = [
      for key in local.purgeable_bucket_keys : "${aws_s3_bucket.data[key].arn}/*"
    ]
  }
}

resource "aws_iam_policy" "deletion_worker_object_purge" {
  name        = "${local.bucket_prefix}-deletion-worker-object-purge"
  description = "Least-privilege version inventory and physical purge for the deletion worker."
  policy      = data.aws_iam_policy_document.deletion_worker_object_purge.json
}

resource "aws_kms_key" "object_storage" {
  description             = "${local.bucket_prefix} object storage"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  multi_region            = false
}

resource "aws_kms_alias" "object_storage" {
  name          = "alias/${local.bucket_prefix}-objects"
  target_key_id = aws_kms_key.object_storage.key_id
}

resource "aws_s3_bucket" "data" {
  for_each = local.buckets

  bucket              = "${local.bucket_prefix}-${each.key}"
  force_destroy       = var.environment != "production" && var.force_destroy_nonproduction
  object_lock_enabled = each.key == "audit-evidence"
}

resource "aws_s3_bucket_public_access_block" "data" {
  for_each = aws_s3_bucket.data

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  for_each = aws_s3_bucket.data

  bucket = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "data" {
  for_each = aws_s3_bucket.data

  bucket = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = aws_s3_bucket.data

  bucket = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.object_storage.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  for_each = local.buckets

  bucket = aws_s3_bucket.data[each.key].id

  depends_on = [
    aws_s3_bucket_versioning.data,
  ]

  rule {
    id     = "expire-by-product-retention"
    status = "Enabled"

    filter {}

    expiration {
      days = each.value.expiry_days
    }

    noncurrent_version_expiration {
      noncurrent_days = each.value.expiry_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit_evidence" {
  bucket = aws_s3_bucket.data["audit-evidence"].id

  depends_on = [
    aws_s3_bucket_versioning.data,
  ]

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.audit_object_lock_days
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "quarantine" {
  bucket = aws_s3_bucket.data["quarantine"].id

  cors_rule {
    allowed_headers = ["Content-Type", "x-amz-checksum-sha256"]
    allowed_methods = ["PUT"]
    allowed_origins = var.upload_allowed_origins
    expose_headers  = ["ETag", "x-amz-checksum-sha256"]
    max_age_seconds = 600
  }
}

data "aws_iam_policy_document" "bucket_guardrails" {
  for_each = aws_s3_bucket.data

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "guardrails" {
  for_each = aws_s3_bucket.data

  bucket = each.value.id
  policy = data.aws_iam_policy_document.bucket_guardrails[each.key].json
}
