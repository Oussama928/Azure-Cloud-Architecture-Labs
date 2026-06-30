# Private Endpoints module for ChangeTrace - Production hardening

resource "azurerm_private_dns_zone" "cosmos" {
  count = var.enable_private_endpoints ? 1 : 0

  name                = "privatelink.documents.azure.com"
  resource_group_name = var.resource_group_name

  tags = var.common_tags
}

resource "azurerm_private_dns_zone" "acr" {
  count = var.enable_private_endpoints ? 1 : 0

  name                = "privatelink.azurecr.io"
  resource_group_name = var.resource_group_name

  tags = var.common_tags
}

resource "azurerm_private_dns_zone" "key_vault" {
  count = var.enable_private_endpoints ? 1 : 0

  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name

  tags = var.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "cosmos" {
  count = var.enable_private_endpoints ? 1 : 0

  name                  = "cosmos-privatelink-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.cosmos[0].name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false

  tags = var.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  count = var.enable_private_endpoints ? 1 : 0

  name                  = "acr-privatelink-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.acr[0].name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false

  tags = var.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "key_vault" {
  count = var.enable_private_endpoints ? 1 : 0

  name                  = "kv-privatelink-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.key_vault[0].name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false

  tags = var.common_tags
}

resource "azurerm_private_endpoint" "cosmos" {
  count = var.enable_private_endpoints && var.cosmos_db_id != "" ? 1 : 0

  name                = "changetrace-${var.environment}-cosmos-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.subnet_id

  private_service_connection {
    name                           = "changetrace-cosmos-psc"
    private_connection_resource_id = var.cosmos_db_id
    subresource_names              = ["SQL"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "cosmos-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.cosmos[0].id]
  }

  tags = var.common_tags
}

resource "azurerm_private_endpoint" "acr" {
  count = var.enable_private_endpoints && var.acr_id != "" ? 1 : 0

  name                = "changetrace-${var.environment}-acr-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.subnet_id

  private_service_connection {
    name                           = "changetrace-acr-psc"
    private_connection_resource_id = var.acr_id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "acr-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr[0].id]
  }

  tags = var.common_tags
}

resource "azurerm_private_endpoint" "key_vault" {
  count = var.enable_private_endpoints && var.key_vault_id != "" ? 1 : 0

  name                = "changetrace-${var.environment}-kv-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.subnet_id

  private_service_connection {
    name                           = "changetrace-kv-psc"
    private_connection_resource_id = var.key_vault_id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "kv-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.key_vault[0].id]
  }

  tags = var.common_tags
}
