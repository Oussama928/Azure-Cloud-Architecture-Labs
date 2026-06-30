# Network Policies module for ChangeTrace - Production hardening

resource "azurerm_network_security_group" "main" {
  count = var.enable_network_policies ? 1 : 0

  name                = "changetrace-${var.environment}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.common_tags
}

resource "azurerm_network_security_rule" "allow_internal_vnet" {
  count = var.enable_network_policies ? 1 : 0

  name                        = "AllowInternalVNet"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefixes     = var.allowed_source_addresses
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main[0].name
}

resource "azurerm_network_security_rule" "allow_azure_lb" {
  count = var.enable_network_policies ? 1 : 0

  name                        = "AllowAzureLoadBalancer"
  priority                    = 101
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "AzureLoadBalancer"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main[0].name
}

resource "azurerm_network_security_rule" "deny_all_inbound" {
  count = var.enable_network_policies ? 1 : 0

  name                        = "DenyAllInbound"
  priority                    = 200
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main[0].name
}

resource "azurerm_network_security_rule" "allow_outbound_https" {
  count = var.enable_network_policies ? 1 : 0

  name                        = "AllowOutboundHTTPS"
  priority                    = 100
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Internet"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main[0].name
}

resource "azurerm_network_security_rule" "deny_all_outbound" {
  count = var.enable_network_policies ? 1 : 0

  name                        = "DenyAllOutbound"
  priority                    = 200
  direction                   = "Outbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main[0].name
}

resource "azurerm_subnet_network_security_group_association" "main" {
  count = var.enable_network_policies && var.subnet_id != "" ? 1 : 0

  subnet_id                 = var.subnet_id
  network_security_group_id = azurerm_network_security_group.main[0].id
}

resource "azurerm_subnet_service_endpoint_storage" "main" {
  count = var.enable_network_policies && var.subnet_id != "" ? 1 : 0

  subnet_id = var.subnet_id
  service_endpoints = [
    "Microsoft.Storage",
    "Microsoft.KeyVault",
    "Microsoft.AzureCosmosDB",
    "Microsoft.ContainerRegistry",
    "Microsoft.EventGrid",
  ]

  depends_on = [
    azurerm_subnet_network_security_group_association.main
  ]
}
