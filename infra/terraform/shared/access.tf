resource "azurerm_user_assigned_identity" "api" {
  name                = "id-image-to-lego-api-dev"
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  lifecycle { prevent_destroy = true }
}
resource "azurerm_user_assigned_identity" "generation_worker" {
  name                = "id-image-to-lego-generation-dev"
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  lifecycle { prevent_destroy = true }
}
resource "azurerm_user_assigned_identity" "conversion_worker" {
  name                = "id-image-to-lego-conversion-dev"
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  lifecycle { prevent_destroy = true }
}
resource "azurerm_user_assigned_identity" "frontend" {
  name                = "id-image-to-lego-frontend-dev"
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = azurerm_container_registry.backend.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "generation_acr_pull" {
  scope                = azurerm_container_registry.backend.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.generation_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "conversion_acr_pull" {
  scope                = azurerm_container_registry.backend.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.conversion_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "frontend_acr_pull" {
  scope                = azurerm_container_registry.backend.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.frontend.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "api_artifact_access" {
  scope                = azurerm_storage_container.artifacts.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "generation_artifact_access" {
  scope                = azurerm_storage_container.artifacts.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.generation_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "conversion_artifact_access" {
  scope                = azurerm_storage_container.artifacts.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.conversion_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "api_blob_delegator" {
  scope                = azurerm_storage_account.artifacts.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "generation_blob_delegator" {
  scope                = azurerm_storage_account.artifacts.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_user_assigned_identity.generation_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "api_generation_sender" {
  scope                = azurerm_servicebus_queue.generation.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "api_conversion_sender" {
  scope                = azurerm_servicebus_queue.conversion.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "generation_queue_receiver" {
  scope                = azurerm_servicebus_queue.generation.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_user_assigned_identity.generation_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "generation_queue_sender" {
  scope                = azurerm_servicebus_queue.generation.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.generation_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "conversion_queue_receiver" {
  scope                = azurerm_servicebus_queue.conversion.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_user_assigned_identity.conversion_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "conversion_queue_sender" {
  scope                = azurerm_servicebus_queue.conversion.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.conversion_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "api_key_vault_secrets" {
  scope                = azurerm_key_vault.runtime.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "generation_key_vault_secrets" {
  scope                = azurerm_key_vault.runtime.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.generation_worker.principal_id
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "conversion_key_vault_secrets" {
  scope                = azurerm_key_vault.runtime.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.conversion_worker.principal_id
  lifecycle { prevent_destroy = true }
}
