variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus"
  validation {
    condition     = contains(["eastus", "westus2", "centralus", "northeurope", "westeurope", "southeastasia", "swedencentral"], var.location)
    error_message = "Location must be a region that supports all required services (Cosmos DB free tier, etc.)"
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod"
  }
}

variable "common_tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default = {
    Project     = "ChangeTrace"
    Environment = "dev"
    Owner       = "internship-project"
    CostCenter  = "engineering"
  }
}

variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
  default     = ""
}

variable "enable_aks" {
  description = "Whether to provision AKS cluster (costs money!)"
  type        = bool
  default     = false
}

variable "aks_node_count" {
  description = "Number of nodes in AKS node pool"
  type        = number
  default     = 1
}

variable "aks_node_vm_size" {
  description = "VM size for AKS nodes"
  type        = string
  default     = "Standard_B2s" # Burstable, cheaper for dev
}

variable "github_repository" {
  description = "GitHub repository for OIDC federation (owner/repo)"
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Email address for budget and operational alerts"
  type        = string
  default     = ""
}

variable "cosmos_db_free_tier" {
  description = "Enable Cosmos DB free tier (400 RU/s, 25GB)"
  type        = bool
  default     = true
}

variable "app_insights_daily_cap_gb" {
  description = "Daily data cap for Application Insights in GB (0.1 = 100MB free tier)"
  type        = number
  default     = 0.1
}

variable "app_insights_sampling_percentage" {
  description = "Sampling percentage for Application Insights (10 = 10%)"
  type        = number
  default     = 10
}

variable "github_actions_sp_object_id" {
  description = "Object ID of the GitHub Actions service principal for Key Vault access"
  type        = string
  default     = ""
}

variable "enable_hardening" {
  description = "Enable production hardening (private endpoints, network policies, TLS certs)"
  type        = bool
  default     = false
}

variable "vnet_id" {
  description = "Virtual Network ID for private endpoints and DNS zone links"
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Subnet ID for private endpoints and NSG association"
  type        = string
  default     = ""
}

variable "allowed_ip_ranges" {
  description = "Allowed IP ranges for network security group rules"
  type        = list(string)
  default     = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
}

variable "dns_names" {
  description = "DNS names for TLS certificates"
  type        = list(string)
  default     = []
}