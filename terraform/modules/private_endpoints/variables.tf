variable "enable_private_endpoints" {
  description = "Enable private endpoint creation"
  type        = bool
  default     = false
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "vnet_id" {
  description = "Virtual Network ID for DNS zone links"
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Subnet ID for private endpoints"
  type        = string
  default     = ""
}

variable "cosmos_db_id" {
  description = "Cosmos DB account resource ID"
  type        = string
  default     = ""
}

variable "acr_id" {
  description = "Container Registry resource ID"
  type        = string
  default     = ""
}

variable "key_vault_id" {
  description = "Key Vault resource ID"
  type        = string
  default     = ""
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}
