variable "project_name" {
  description = "Short lowercase project prefix."
  type        = string
  default     = "akc"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "project_name must be a short lowercase DNS-style label."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "aws_region" {
  description = "Guaranteed AWS data region; do not infer residency from a location hint."
  type        = string
}

variable "retention_days" {
  description = "Infrastructure safety-net expiry for tenant-controlled source/derived/export data. The application sweep is authoritative, so this cannot precede the maximum 3650-day tenant policy."
  type        = number
  default     = 3650

  validation {
    condition     = var.retention_days == 3650
    error_message = "retention_days must remain 3650 so bucket lifecycle never preempts any valid tenant retention policy."
  }
}

variable "working_retention_days" {
  description = "Short-lived page render, crop, and intermediate response expiry."
  type        = number
  default     = 1

  validation {
    condition     = var.working_retention_days >= 1 && var.working_retention_days <= 7
    error_message = "working_retention_days must be between 1 and 7."
  }
}

variable "audit_object_lock_days" {
  description = "Default governance retention for immutable audit evidence."
  type        = number
  default     = 30

  validation {
    condition     = var.audit_object_lock_days >= 7 && var.audit_object_lock_days <= 3650
    error_message = "audit_object_lock_days must be between 7 and 3650."
  }
}

variable "upload_allowed_origins" {
  description = "Exact HTTPS web origins allowed to use presigned quarantine uploads."
  type        = list(string)

  validation {
    condition = (
      length(var.upload_allowed_origins) > 0
      && alltrue([
        for origin in var.upload_allowed_origins :
        can(regex("^https://[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?$", origin)) && !strcontains(origin, "*")
      ])
    )
    error_message = "upload_allowed_origins must contain exact HTTPS origins without wildcards."
  }
}

variable "force_destroy_nonproduction" {
  description = "Allows teardown only for nonproduction after an explicit plan review."
  type        = bool
  default     = false

  validation {
    condition     = !(var.environment == "production" && var.force_destroy_nonproduction)
    error_message = "Production buckets can never use force_destroy."
  }
}
