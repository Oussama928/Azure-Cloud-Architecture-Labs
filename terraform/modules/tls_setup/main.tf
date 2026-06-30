# TLS/Certificates module for ChangeTrace - Production hardening

resource "azurerm_key_vault_certificate" "ingress" {
  count = var.enable_tls && var.key_vault_id != "" ? 1 : 0

  name         = "changetrace-${var.environment}-ingress-cert"
  key_vault_id = var.key_vault_id

  certificate_policy {
    issuer_parameters {
      name = "Self"
    }

    key_properties {
      exportable = true
      key_size   = 2048
      key_type   = "RSA"
      reuse_key  = true
    }

    lifetime_action {
      action {
        action_type = "AutoRenew"
      }

      trigger {
        days_before_expiry = 30
      }
    }

    secret_properties {
      content_type = "application/x-pkcs12"
    }

    x509_certificate_properties {
      key_usage = [
        "cRLSign",
        "dataEncipherment",
        "digitalSignature",
        "keyAgreement",
        "keyEncipherment",
        "keyCertSign",
      ]

      subject            = "CN=${var.dns_names[0]}"
      validity_in_months = 12

      subject_alternative_names {
        dns_names = var.dns_names
      }
    }
  }

  tags = var.common_tags
}

resource "azurerm_key_vault_certificate" "api" {
  count = var.enable_tls && var.key_vault_id != "" ? 1 : 0

  name         = "changetrace-${var.environment}-api-cert"
  key_vault_id = var.key_vault_id

  certificate_policy {
    issuer_parameters {
      name = "Self"
    }

    key_properties {
      exportable = true
      key_size   = 2048
      key_type   = "RSA"
      reuse_key  = true
    }

    lifetime_action {
      action {
        action_type = "AutoRenew"
      }

      trigger {
        days_before_expiry = 30
      }
    }

    secret_properties {
      content_type = "application/x-pkcs12"
    }

    x509_certificate_properties {
      key_usage = [
        "cRLSign",
        "dataEncipherment",
        "digitalSignature",
        "keyAgreement",
        "keyEncipherment",
        "keyCertSign",
      ]

      subject            = "CN=${var.dns_names[0]}"
      validity_in_months = 12

      subject_alternative_names {
        dns_names = var.dns_names
      }
    }
  }

  tags = var.common_tags
}
