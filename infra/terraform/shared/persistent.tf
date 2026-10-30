locals {
  deployment_suffix       = lower(substr(replace(data.azurerm_client_config.current.subscription_id, "-", ""), 0, 8))
  container_registry_name = "itl${local.deployment_suffix}"
  key_vault_name          = "kv-itl-${local.deployment_suffix}"
  tags = {
    environment = "dev"
    project     = "image-to-lego"
  }
}

resource "azurerm_resource_group" "dev" {
  name     = var.resource_group_name
  location = var.resource_group_location
  tags     = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_storage_account" "artifacts" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.dev.name
  location                 = var.storage_account_location
  account_tier             = var.storage_account_tier
  account_replication_type = var.storage_account_replication_type
  account_kind             = "StorageV2"
  access_tier              = "Hot"

  allow_nested_items_to_be_public  = false
  cross_tenant_replication_enabled = false
  default_to_oauth_authentication  = true
  https_traffic_only_enabled       = true
  min_tls_version                  = "TLS1_2"
  public_network_access_enabled    = true
  shared_access_key_enabled        = false
  tags                             = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_storage_container" "artifacts" {
  name                  = var.artifact_container_name
  storage_account_id    = azurerm_storage_account.artifacts.id
  container_access_type = "private"
  metadata              = {}
  lifecycle { prevent_destroy = true }
}

resource "azurerm_servicebus_namespace" "jobs" {
  name                = var.servicebus_namespace_name
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  sku                 = var.servicebus_sku

  local_auth_enabled            = false
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_servicebus_queue" "generation" {
  name         = var.generation_queue_name
  namespace_id = azurerm_servicebus_namespace.jobs.id

  auto_delete_on_idle                     = "P10675199DT2H48M5.4775807S"
  batched_operations_enabled              = true
  dead_lettering_on_message_expiration    = true
  default_message_ttl                     = "P1D"
  duplicate_detection_history_time_window = "PT10M"
  express_enabled                         = false
  lock_duration                           = "PT5M"
  max_delivery_count                      = 5
  max_size_in_megabytes                   = 1024
  partitioning_enabled                    = false
  requires_duplicate_detection            = false
  requires_session                        = false
  status                                  = "Active"
  lifecycle { prevent_destroy = true }
}

resource "azurerm_servicebus_queue" "conversion" {
  name         = var.conversion_queue_name
  namespace_id = azurerm_servicebus_namespace.jobs.id

  auto_delete_on_idle                     = "P10675199DT2H48M5.4775807S"
  batched_operations_enabled              = true
  dead_lettering_on_message_expiration    = true
  default_message_ttl                     = "P1D"
  duplicate_detection_history_time_window = "PT10M"
  express_enabled                         = false
  lock_duration                           = "PT5M"
  max_delivery_count                      = 5
  max_size_in_megabytes                   = 1024
  partitioning_enabled                    = false
  requires_duplicate_detection            = false
  requires_session                        = false
  status                                  = "Active"
  lifecycle { prevent_destroy = true }
}

resource "azurerm_log_analytics_workspace" "application" {
  name                = "log-image-to-lego-dev"
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5
  tags                = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_container_registry" "backend" {
  name                = local.container_registry_name
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  sku                 = "Basic"

  admin_enabled                 = false
  anonymous_pull_enabled        = false
  public_network_access_enabled = true
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_key_vault" "runtime" {
  name                = local.key_vault_name
  location            = var.servicebus_location
  resource_group_name = azurerm_resource_group.dev.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled    = true
  purge_protection_enabled      = false
  soft_delete_retention_days    = 7
  public_network_access_enabled = true
  network_acls {
    bypass         = "AzureServices"
    default_action = "Allow"
  }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}

# A durable shared dependency: deleting it would delete the frontend's hosting environment.
resource "azurerm_container_app_environment" "development" {
  name                       = "cae-image-to-lego-dev"
  location                   = var.servicebus_location
  resource_group_name        = azurerm_resource_group.dev.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.application.id
  logs_destination           = "log-analytics"
  tags                       = local.tags
  lifecycle {
    ignore_changes  = [workload_profile]
    prevent_destroy = true
  }
}
