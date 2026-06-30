variable "enable_tls" {
  description = "Enable TLS certificate creation in Key Vault"
  type        = bool
  default     = false
}

variable "key_vault_id" {
  description = "Key Vault resource ID for certificate storage"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "dns_names" {
  description = "DNS names for TLS certificates"
  type        = list(string)
  default     = []
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}
