# Variables for Container Registry module

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

variable "enable_acr" {
  description = "Enable Container Registry creation (costs money!)"
  type        = bool
  default     = false
}

variable "sku" {
  description = "ACR SKU (Basic, Standard, Premium)"
  type        = string
  default     = "Basic"
}

variable "geo_replication_location" {
  description = "Geo-replication location for production"
  type        = string
  default     = ""
}

variable "allowed_ip_range" {
  description = "Allowed IP range for ACR access"
  type        = string
  default     = "0.0.0.0/0"
}

variable "subnet_id" {
  description = "Subnet ID for private endpoint (production)"
  type        = string
  default     = ""
}

variable "function_app_identity_id" {
  description = "Function App managed identity object ID for ACR pull access"
  type        = string
  default     = ""
}

variable "aks_identity_id" {
  description = "AKS managed identity object ID for ACR pull access"
  type        = string
  default     = ""
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}