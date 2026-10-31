variable "resource_group_name" {
  type    = string
  default = "rg-image-to-lego-dev"
}
variable "location" {
  type    = string
  default = "malaysiawest"
}
variable "api_backend_image_tag" {
  type    = string
  default = "dev-20261029-205014"
}
variable "worker_backend_image_tag" {
  type    = string
  default = "bootstrap-898adc56df2e"
}
variable "frontend_image_tag" {
  type    = string
  default = "dev-20261030-nginxfix"
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
