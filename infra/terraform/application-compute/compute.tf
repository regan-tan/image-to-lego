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
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.api.id]
  }

  site_config {
    always_on                                     = false
    ftps_state                                    = "FtpsOnly"
    minimum_tls_version                           = "1.2"
    container_registry_use_managed_identity       = true
    container_registry_managed_identity_client_id = data.azurerm_user_assigned_identity.api.client_id

    application_stack {
      docker_image_name   = "image-to-lego-backend:${var.api_backend_image_tag}"
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
      JOB_SUBMISSIONS_ENABLED        = tostring(var.job_submissions_enabled)
      WEBSITES_PORT                  = "8000"
      WEBSITE_SKIP_RUNNING_KUDUAGENT = "true"
    },
    var.supabase_url == null ? {} : { SUPABASE_URL = var.supabase_url },
  )

  lifecycle {
    ignore_changes = [
      app_settings,
      # The adopted API still has worker identities. Preserve that live
      # assignment until teardown; a newly created API gets only its own.
      identity,
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
    image    = local.worker_backend_image
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
      # The adopted workers predate the bootstrap image. Retain their existing
      # image and runtime contract until the approved compute teardown; a new
      # container group uses the bootstrap-capable image declared above.
      container[0].image,
      # AzureRM reads this Azure resource ID with a lowercase resourcegroups
      # segment but only accepts the canonical spelling as configuration.
      image_registry_credential[0].user_assigned_identity_id,
      # AzureRM 4.81.0 accepts None for a new group, but refreshes these
      # imported stopped groups without it. Removing this guard replaces them.
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
    image    = local.worker_backend_image
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
      # See the matching generation-worker explanation above.
      container[0].image,
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
      # API client paths already begin with /api/v1. A /api base would
      # duplicate the prefix and cause 404s through the Nginx proxy.
      env {
        name  = "VITE_API_BASE_URL"
        value = ""
      }
      # nginx.conf.template forwards /api to this HTTPS App Service origin.
      env {
        name  = "API_UPSTREAM"
        value = "https://${azurerm_linux_web_app.api.default_hostname}"
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
    # Preserve existing frontend environment settings during reconciliation.
    # The empty API base above is the clean-room creation contract; the live
    # frontend was separately corrected and verified. Remove this safeguard
    # only with a reviewed frontend release and runtime configuration test.
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
