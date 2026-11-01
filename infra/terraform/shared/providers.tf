provider "azurerm" {
  features {}

  use_cli                         = true
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

data "azurerm_client_config" "current" {}
