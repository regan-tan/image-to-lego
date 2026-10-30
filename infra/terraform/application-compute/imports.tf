# These import blocks make adoption reviewable in a plan. They must only be
# applied after the frontend is detached from the shared state by its reviewed
# removed block; otherwise two state backends would claim the same resource.
import {
  to = azurerm_service_plan.api
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Web/serverfarms/ASP-rgimagetolegodev-8295"
}

import {
  to = azurerm_linux_web_app.api
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Web/sites/app-image-to-lego-api-dev-2b70703f"
}

import {
  to = azurerm_container_group.generation_worker
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-generation-dev"
}

import {
  to = azurerm_container_group.conversion_worker
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-conversion-dev"
}

import {
  to = azurerm_container_app.frontend
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.App/containerApps/ca-frontend-image-to-lego-dev"
}
