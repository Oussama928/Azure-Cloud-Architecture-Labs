# Variables for Monitor module

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

variable "daily_data_cap_gb" {
  description = "Daily data cap for Application Insights in GB (0.1 = 100MB free tier)"
  type        = number
  default     = 0.1
}

variable "sampling_percentage" {
  description = "Sampling percentage for Application Insights (10 = 10%)"
  type        = number
  default     = 10
}

variable "alert_email" {
  description = "Email address for alerts"
  type        = string
  default     = ""
}

variable "webhook_url" {
  description = "Webhook URL for alerts"
  type        = string
  default     = ""
}

variable "key_vault_id" {
  description = "Key Vault resource ID for diagnostic settings"
  type        = string
  default     = ""
}

variable "cosmos_db_id" {
  description = "Cosmos DB resource ID for diagnostic settings"
  type        = string
  default     = ""
}

variable "function_app_id" {
  description = "Function App resource ID for diagnostic settings"
  type        = string
  default     = ""
}

variable "eventgrid_cicd_topic_id" {
  description = "Event Grid CI/CD topic resource ID for diagnostic settings"
  type        = string
  default     = ""
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}