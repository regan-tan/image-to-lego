output "resource_group_name" { value = azurerm_resource_group.dev.name }
output "artifact_storage_account_url" { value = "https://${azurerm_storage_account.artifacts.name}.blob.core.windows.net" }
output "artifact_container_name" { value = azurerm_storage_container.artifacts.name }
output "service_bus_namespace" { value = "${azurerm_servicebus_namespace.jobs.name}.servicebus.windows.net" }
output "generation_queue_name" { value = azurerm_servicebus_queue.generation.name }
output "conversion_queue_name" { value = azurerm_servicebus_queue.conversion.name }
output "container_registry_login_server" { value = azurerm_container_registry.backend.login_server }
output "key_vault_name" { value = azurerm_key_vault.runtime.name }
output "github_deployment_client_id" {
  description = "Configure this as the AZURE_DEPLOYMENT_CLIENT_ID GitHub repository variable."
  value       = azurerm_user_assigned_identity.github_deployment.client_id
}
output "github_deployment_tenant_id" {
  description = "Configure this as the AZURE_TENANT_ID GitHub repository variable."
  value       = data.azurerm_client_config.current.tenant_id
}
output "github_deployment_subscription_id" {
  description = "Configure this as the AZURE_SUBSCRIPTION_ID GitHub repository variable."
  value       = data.azurerm_client_config.current.subscription_id
}
