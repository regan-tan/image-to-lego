data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "dev" { name = var.resource_group_name }
data "azurerm_container_registry" "backend" {
  name                = "itl2b70703f"
  resource_group_name = data.azurerm_resource_group.dev.name
}
data "azurerm_key_vault" "runtime" {
  name                = "kv-itl-2b70703f"
  resource_group_name = data.azurerm_resource_group.dev.name
}
data "azurerm_container_app_environment" "development" {
  name                = "cae-image-to-lego-dev"
  resource_group_name = data.azurerm_resource_group.dev.name
}
data "azurerm_user_assigned_identity" "api" {
  name                = "id-image-to-lego-api-dev"
  resource_group_name = data.azurerm_resource_group.dev.name
}
data "azurerm_user_assigned_identity" "generation_worker" {
  name                = "id-image-to-lego-generation-dev"
  resource_group_name = data.azurerm_resource_group.dev.name
}
data "azurerm_user_assigned_identity" "conversion_worker" {
  name                = "id-image-to-lego-conversion-dev"
  resource_group_name = data.azurerm_resource_group.dev.name
}
data "azurerm_user_assigned_identity" "frontend" {
  name                = "id-image-to-lego-frontend-dev"
  resource_group_name = data.azurerm_resource_group.dev.name
}

locals {
  worker_backend_image = "${data.azurerm_container_registry.backend.login_server}/image-to-lego-backend:${var.worker_backend_image_tag}"
  frontend_image       = "${data.azurerm_container_registry.backend.login_server}/image-to-lego-frontend:${var.frontend_image_tag}"
  common_worker_environment = {
    APP_ENV                            = var.app_environment
    AZURE_STORAGE_ACCOUNT_URL          = "https://storageimgtolego.blob.core.windows.net"
    AZURE_STORAGE_CONTAINER            = "artifacts"
    AZURE_SERVICE_BUS_NAMESPACE        = "image-to-lego-bus-dev-01.servicebus.windows.net"
    AZURE_SERVICE_BUS_QUEUE            = "conversion"
    AZURE_SERVICE_BUS_GENERATION_QUEUE = "generation"
  }
}
