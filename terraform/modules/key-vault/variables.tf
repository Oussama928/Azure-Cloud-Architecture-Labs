# Variables for Key Vault module

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

variable "function_app_identity_id" {
  description = "Function App managed identity object ID (for Key Vault access)"
  type        = string
  default     = ""
}

variable "aks_identity_id" {
  description = "AKS managed identity object ID (for Key Vault access)"
  type        = string
  default     = ""
}

variable "cosmos_connection_string" {
  description = "Cosmos DB connection string"
  type        = string
  default     = ""
  sensitive   = true
}

variable "cosmos_primary_key" {
  description = "Cosmos DB primary key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "eventgrid_cicd_endpoint" {
  description = "Event Grid CI/CD topic endpoint"
  type        = string
  default     = ""
}

variable "eventgrid_cicd_key" {
  description = "Event Grid CI/CD topic key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "eventgrid_git_endpoint" {
  description = "Event Grid Git topic endpoint"
  type        = string
  default     = ""
}

variable "eventgrid_git_key" {
  description = "Event Grid Git topic key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "eventgrid_alert_endpoint" {
  description = "Event Grid Alert topic endpoint"
  type        = string
  default     = ""
}

variable "eventgrid_alert_key" {
  description = "Event Grid Alert topic key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "eventgrid_argo_endpoint" {
  description = "Event Grid Argo topic endpoint"
  type        = string
  default     = ""
}

variable "eventgrid_argo_key" {
  description = "Event Grid Argo topic key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "appinsights_key" {
  description = "Application Insights instrumentation key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "appinsights_connection_string" {
  description = "Application Insights connection string"
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_webhook_secret" {
  description = "GitHub webhook secret"
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_app_id" {
  description = "GitHub App ID"
  type        = string
  default     = ""
}

variable "github_app_private_key" {
  description = "GitHub App private key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "approval_webhook_secret" {
  description = "Approval webhook HMAC secret"
  type        = string
  default     = ""
  sensitive   = true
}

variable "argo_api_token" {
  description = "Argo Rollouts API token"
  type        = string
  default     = ""
  sensitive   = true
}

variable "azure_ml_workspace_key" {
  description = "Azure ML workspace key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}