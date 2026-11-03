# This identity is only for GitHub Actions releases. Runtime identities remain
# separate so a CI credential cannot read application data or runtime secrets.
resource "azurerm_user_assigned_identity" "github_deployment" {
  name                = "id-image-to-lego-github-deployment-dev"
  location            = var.resource_group_location
  resource_group_name = azurerm_resource_group.dev.name

  lifecycle { prevent_destroy = true }
}

resource "azurerm_federated_identity_credential" "github_main" {
  name                = "github-main"
  resource_group_name = azurerm_resource_group.dev.name
  parent_id           = azurerm_user_assigned_identity.github_deployment.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = var.github_oidc_subject
}

# The deployment identity can publish images and update only the four runtime
# resources. It intentionally has no Key Vault, Blob, Service Bus, or database
# data permissions.
resource "azurerm_role_assignment" "github_deployment_acr_push" {
  scope                = azurerm_container_registry.backend.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_api" {
  scope                = "${azurerm_resource_group.dev.id}/providers/Microsoft.Web/sites/app-image-to-lego-api-dev-2b70703f"
  role_definition_name = "Website Contributor"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_api_plan_reader" {
  scope                = "${azurerm_resource_group.dev.id}/providers/Microsoft.Web/serverFarms/ASP-rgimagetolegodev-8295"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_frontend" {
  scope                = "${azurerm_resource_group.dev.id}/providers/Microsoft.App/containerApps/ca-frontend-image-to-lego-dev"
  role_definition_name = "Container Apps Contributor"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_generation_worker" {
  scope                = "${azurerm_resource_group.dev.id}/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-generation-dev"
  role_definition_name = "Azure Container Instances Contributor Role"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_conversion_worker" {
  scope                = "${azurerm_resource_group.dev.id}/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-conversion-dev"
  role_definition_name = "Azure Container Instances Contributor Role"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

# Recreating an ACI group requires attaching its existing runtime identity. The
# deployment identity can operate only these two identities, not arbitrary ones.
resource "azurerm_role_assignment" "github_deployment_generation_identity_operator" {
  scope                = azurerm_user_assigned_identity.generation_worker.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_conversion_identity_operator" {
  scope                = azurerm_user_assigned_identity.conversion_worker.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

# Read-only metadata access supports the fail-closed preflight: it can inspect
# runtime identities and queue counts/role assignments but cannot read messages,
# Key Vault secrets, Blob data, or application settings.
resource "azurerm_role_assignment" "github_deployment_runtime_identity_reader" {
  for_each = {
    api        = azurerm_user_assigned_identity.api.id
    generation = azurerm_user_assigned_identity.generation_worker.id
    conversion = azurerm_user_assigned_identity.conversion_worker.id
  }

  scope                = each.value
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "github_deployment_queue_reader" {
  for_each = {
    generation = azurerm_servicebus_queue.generation.id
    conversion = azurerm_servicebus_queue.conversion.id
  }

  scope                = each.value
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id

  lifecycle { prevent_destroy = true }
}
