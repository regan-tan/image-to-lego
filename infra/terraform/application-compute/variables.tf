variable "resource_group_name" {
  type    = string
  default = "rg-image-to-lego-dev"
}
variable "location" {
  type    = string
  default = "malaysiawest"
}
variable "backend_image_tag" {
  type    = string
  default = "dev-20261029-205014"
}
variable "frontend_image_tag" {
  type    = string
  default = "dev-20261030-nginxfix"
}
variable "api_upstream" {
  type    = string
  default = "https://app-image-to-lego-api-dev-2b70703f-gncbcjh9hua6hmek.malaysiawest-01.azurewebsites.net"
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
