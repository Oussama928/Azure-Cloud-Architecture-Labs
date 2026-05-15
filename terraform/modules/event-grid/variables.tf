# Variables for Event Grid module

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "resource_group_id" {
  description = "Resource group ID for event subscription scope"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "storage_account_id" {
  description = "Storage account ID for dead letter destination"
  type        = string
}

variable "function_app_id" {
  description = "Function App resource ID for event subscriptions"
  type        = string
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}