# A `removed.from` address cannot include an instance key such as `[0]`.
# This resource address therefore covers the old counted frontend instances.
# The handoff review must first confirm that only frontend[0] exists in state.
# It must never ask Terraform to destroy the live frontend.
removed {
  from = azurerm_container_app.frontend
  lifecycle { destroy = false }
}

# This unverified legacy environment must be detached, not destroyed, if it is
# in the old state. Its future ownership requires a separate inventory review.
removed {
  from = azurerm_container_app_environment.standard
  lifecycle { destroy = false }
}
