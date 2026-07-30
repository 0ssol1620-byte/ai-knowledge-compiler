output "bucket_arns" {
  description = "Bucket ARNs keyed by lifecycle class."
  value       = { for key, bucket in aws_s3_bucket.data : key => bucket.arn }
}

output "bucket_names" {
  description = "Bucket names keyed by lifecycle class for Kubernetes overlays."
  value       = { for key, bucket in aws_s3_bucket.data : key => bucket.id }
}

output "kms_key_arn" {
  description = "Customer-content storage key."
  value       = aws_kms_key.object_storage.arn
}

output "deletion_worker_object_purge_policy_arn" {
  description = "Attach to the deletion worker workload role; includes version inventory and physical version deletion, never object reads."
  value       = aws_iam_policy.deletion_worker_object_purge.arn
}
