resource "azurerm_service_plan" "api" {
  name                = "ASP-rgimagetolegodev-8295"
  resource_group_name = data.azurerm_resource_group.dev.name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "B1"
  worker_count        = 1
  tags                = { environment = "dev", project = "image-to-lego" }
}

resource "azurerm_linux_web_app" "api" {
  name                = "app-image-to-lego-api-dev-2b70703f"
  resource_group_name = data.azurerm_resource_group.dev.name
  location            = var.location
  service_plan_id     = azurerm_service_plan.api.id

  https_only                                     = true
  public_network_access_enabled                  = true
  key_vault_reference_identity_id                = data.azurerm_user_assigned_identity.api.id
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  tags                                           = { environment = "dev", project = "image-to-lego" }

  identity {
    type = "UserAssigned"
    # The live API has all three runtime identities. Retain them during state
    # adoption; removing the worker identities would change a live site.
    identity_ids = [
      data.azurerm_user_assigned_identity.api.id,
      data.azurerm_user_assigned_identity.generation_worker.id,
      data.azurerm_user_assigned_identity.conversion_worker.id,
    ]
  }

  site_config {
    always_on                                     = false
    ftps_state                                    = "FtpsOnly"
    minimum_tls_version                           = "1.2"
    container_registry_use_managed_identity       = true
    container_registry_managed_identity_client_id = data.azurerm_user_assigned_identity.api.client_id

    application_stack {
      docker_image_name   = "image-to-lego-backend:${var.backend_image_tag}"
      docker_registry_url = "https://${data.azurerm_container_registry.backend.login_server}"
    }
  }

  # These are the verified non-secret application contract. Existing additional
  # settings remain untouched until a read-only inventory is reviewed.
  app_settings = merge(
    local.common_worker_environment,
    {
      AZURE_CLIENT_ID                = data.azurerm_user_assigned_identity.api.client_id
      DATABASE_URL                   = "@Microsoft.KeyVault(SecretUri=${data.azurerm_key_vault.runtime.vault_uri}secrets/${var.database_url_secret_name})"
      WEBSITES_PORT                  = "8000"
      WEBSITE_SKIP_RUNNING_KUDUAGENT = "true"
    },
    var.supabase_url == null ? {} : { SUPABASE_URL = var.supabase_url },
  )

  lifecycle {
    ignore_changes = [
      app_settings,
      key_vault_reference_identity_id,
      site_config[0].ip_restriction_default_action,
      site_config[0].scm_ip_restriction_default_action,
    ]
  }
}

resource "azurerm_container_group" "generation_worker" {
  name                = "aci-image-to-lego-generation-dev"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.dev.name
  os_type             = "Linux"
  ip_address_type     = "None"
  restart_policy      = "Never"

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.generation_worker.id]
  }
  image_registry_credential {
    server                    = data.azurerm_container_registry.backend.login_server
    user_assigned_identity_id = data.azurerm_user_assigned_identity.generation_worker.id
  }
  container {
    name     = "generation"
    image    = local.backend_image
    cpu      = 1
    memory   = 2
    commands = ["python", "-m", "app.workers.aci_bootstrap", "generation"]
    environment_variables = merge(local.common_worker_environment, {
      AZURE_CLIENT_ID          = data.azurerm_user_assigned_identity.generation_worker.client_id
      AZURE_KEY_VAULT_URL      = data.azurerm_key_vault.runtime.vault_uri
      DATABASE_URL_SECRET_NAME = var.database_url_secret_name
      FAL_KEY_SECRET_NAME      = var.fal_key_secret_name
    })
  }

  # The current image has a different verified custom command. Ignore command
  # and environment drift during adoption; a new bootstrap-enabled image is a
  # separately reviewed recreation/release prerequisite.
  lifecycle {
    ignore_changes = [
      container[0].commands,
      container[0].environment_variables,
      container[0].secure_environment_variables,
      # AzureRM reads this Azure resource ID with a lowercase resourcegroups
      # segment but only accepts the canonical spelling as configuration.
      image_registry_credential[0].user_assigned_identity_id,
      # Azure reports this stopped worker with no IP type, but AzureRM defaults
      # an omitted value to Public and cannot configure None. Its derived port
      # would otherwise force a replacement too.
      ip_address_type,
      exposed_port,
    ]
  }
}

resource "azurerm_container_group" "conversion_worker" {
  name                = "aci-image-to-lego-conversion-dev"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.dev.name
  os_type             = "Linux"
  ip_address_type     = "None"
  restart_policy      = "Never"

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.conversion_worker.id]
  }
  image_registry_credential {
    server                    = data.azurerm_container_registry.backend.login_server
    user_assigned_identity_id = data.azurerm_user_assigned_identity.conversion_worker.id
  }
  container {
    name     = "conversion"
    image    = local.backend_image
    cpu      = 1
    memory   = 2
    commands = ["python", "-m", "app.workers.aci_bootstrap", "conversion"]
    environment_variables = merge(local.common_worker_environment, {
      AZURE_CLIENT_ID          = data.azurerm_user_assigned_identity.conversion_worker.client_id
      AZURE_KEY_VAULT_URL      = data.azurerm_key_vault.runtime.vault_uri
      AZURE_TOKEN_CREDENTIALS  = "ManagedIdentityCredential"
      DATABASE_URL_SECRET_NAME = var.database_url_secret_name
    })
  }
  lifecycle {
    ignore_changes = [
      container[0].commands,
      container[0].environment_variables,
      container[0].secure_environment_variables,
      image_registry_credential[0].user_assigned_identity_id,
      ip_address_type,
      exposed_port,
    ]
  }
}

resource "azurerm_container_app" "frontend" {
  name                         = "ca-frontend-image-to-lego-dev"
  resource_group_name          = data.azurerm_resource_group.dev.name
  container_app_environment_id = data.azurerm_container_app_environment.development.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.frontend.id]
  }
  registry {
    server   = data.azurerm_container_registry.backend.login_server
    identity = data.azurerm_user_assigned_identity.frontend.id
  }
  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  template {
    min_replicas = 0
    max_replicas = 1
    http_scale_rule {
      name                = "http-scaler"
      concurrent_requests = "10"
    }
    container {
      name   = "frontend"
      image  = local.frontend_image
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name  = "VITE_API_BASE_URL"
        value = "/api"
      }
      # nginx.conf.template forwards /api to this HTTPS App Service origin.
      env {
        name  = "API_UPSTREAM"
        value = var.api_upstream
      }
      dynamic "env" {
        for_each = var.supabase_url == null ? [] : [var.supabase_url]
        content {
          name  = "VITE_SUPABASE_URL"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.supabase_publishable_key == null ? [] : [var.supabase_publishable_key]
        content {
          name  = "VITE_SUPABASE_PUBLISHABLE_KEY"
          value = env.value
        }
      }
    }
  }

  lifecycle {
    # The current frontend was built with a public absolute API URL and
    # Supabase build settings. They must remain unchanged while adopting its
    # state. The declared /api value remains the intended clean-room contract;
    # retire this narrowly scoped safeguard only in a separately reviewed
    # frontend release that verifies its built runtime configuration.
    ignore_changes = [
      ingress[0].traffic_weight,
      # The live Container App predates provider validation and stores zero
      # timings, while AzureRM requires either omitted defaults or >= 1.
      template[0].cooldown_period_in_seconds,
      template[0].polling_interval_in_seconds,
      template[0].container[0].env,
    ]
  }
}
