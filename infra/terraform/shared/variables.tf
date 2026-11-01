variable "resource_group_location" { type = string }
variable "storage_account_location" { type = string }
variable "servicebus_location" { type = string }
variable "storage_account_tier" { type = string }
variable "storage_account_replication_type" { type = string }
variable "servicebus_sku" { type = string }

variable "resource_group_name" {
  type    = string
  default = "rg-image-to-lego-dev"
}
variable "storage_account_name" {
  type    = string
  default = "storageimgtolego"
}
variable "artifact_container_name" {
  type    = string
  default = "artifacts"
}
variable "servicebus_namespace_name" {
  type    = string
  default = "image-to-lego-bus-dev-01"
}
variable "generation_queue_name" {
  type    = string
  default = "generation"
}
variable "conversion_queue_name" {
  type    = string
  default = "conversion"
}

variable "github_oidc_subject" {
  description = "Exact verified GitHub OIDC subject for main."
  type        = string

  validation {
    condition     = can(regex("^repo:[^/@:]+(@[0-9]+)?/[^/@:]+(@[0-9]+)?:ref:refs/heads/main$", var.github_oidc_subject))
    error_message = "github_oidc_subject must be the legacy or immutable main-branch GitHub OIDC subject."
  }
}
