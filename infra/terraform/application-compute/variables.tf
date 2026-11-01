variable "resource_group_name" {
  type    = string
  default = "rg-image-to-lego-dev"
}
variable "location" {
  type    = string
  default = "malaysiawest"
}
variable "api_backend_image_tag" {
  description = "Approved immutable backend image tag from a release record."
  type        = string
}
variable "worker_backend_image_tag" {
  description = "Approved immutable worker image tag from a release record."
  type        = string
}
variable "frontend_image_tag" {
  description = "Approved immutable frontend image tag from a release record."
  type        = string
}
variable "supabase_url" {
  type     = string
  default  = null
  nullable = true
}
variable "supabase_publishable_key" {
  type     = string
  default  = null
  nullable = true
}
variable "database_url_secret_name" {
  type    = string
  default = "database-url"
}
variable "fal_key_secret_name" {
  type    = string
  default = "fal-key"
}
variable "app_environment" {
  type    = string
  default = "development"
}

# New APIs must start paused. The existing App Service settings map is ignored
# during adoption, so changing this default cannot modify the live API.
variable "job_submissions_enabled" {
  type    = bool
  default = false
}
