output "backend_default_hostname" { value = azurerm_linux_web_app.api.default_hostname }
output "frontend_url" { value = "https://${azurerm_container_app.frontend.ingress[0].fqdn}" }
