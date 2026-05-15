"""
Activity: Notify Teams (Approval Requests, Escalations)

Sends notifications via Teams webhook, email, or other channels.
Supports approval requests with approve/reject buttons.
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import azure.functions as func
import httpx

logger = logging.getLogger(__name__)


async def main(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send notification for approval request or escalation.
    
    Input:
    {
        "workflow_id": "wf-123",
        "incident_id": "INC-123",
        "title": "Incident INC-123: Approve remediation for payment-service",
        "description": "High-confidence root cause identified...",
        "details": {...},
        "expires_at": "2024-01-15T10:30:00Z",
        "callback_url": "https://func.azurewebsites.net/api/approval/token",
        "token": "secure-token",
        "notification_type": "approval_request" | "escalation"
    }
    
    Output:
    {
        "sent": true,
        "channels": ["teams", "email"],
        "approval_url": "https://...",
        "reject_url": "https://..."
    }
    """
    workflow_id = activity_input.get("workflow_id")
    notification_type = activity_input.get("notification_type", "approval_request")
    
    logger.info(f"Sending {notification_type} notification for workflow {workflow_id}")
    
    # Generate signed approval URLs
    token = activity_input.get("token")
    callback_base = activity_input.get("callback_url")
    expires_at = activity_input.get("expires_at")
    
    if not token or not callback_base:
        raise ValueError("token and callback_url are required")
    
    approve_url = f"{callback_base}?token={token}&decision=approve"
    reject_url = f"{callback_base}?token={token}&decision=reject"
    
    # Send to Teams
    teams_sent = await _send_teams_notification(
        activity_input, approve_url, reject_url, expires_at
    )
    
    # Send email (placeholder)
    email_sent = await _send_email_notification(
        activity_input, approve_url, reject_url, expires_at
    )
    
    return {
        "sent": teams_sent or email_sent,
        "channels": ["teams"] if teams_sent else [] + (["email"] if email_sent else []),
        "approval_url": approve_url,
        "reject_url": reject_url,
        "expires_at": expires_at
    }


async def _send_teams_notification(
    activity_input: Dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: Optional[str]
) -> bool:
    """Send Teams adaptive card notification."""
    
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL not configured, skipping Teams notification")
        return False
    
    notification_type = activity_input.get("notification_type", "approval_request")
    
    if notification_type == "approval_request":
        card = _build_approval_card(activity_input, approve_url, reject_url, expires_at)
    else:
        card = _build_escalation_card(activity_input, expires_at)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=card)
            response.raise_for_status()
            logger.info("Teams notification sent successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to send Teams notification: {e}")
        return False


async def _send_email_notification(
    activity_input: Dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: Optional[str]
) -> bool:
    """Send email notification (placeholder - integrate with SendGrid, etc.)."""
    
    # TODO: Implement actual email sending via SendGrid, Azure Communication Services, etc.
    logger.info("Email notification would be sent here (not implemented)")
    return False


def _build_approval_card(
    activity_input: Dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: Optional[str]
) -> Dict[str, Any]:
    """Build Teams adaptive card for approval request."""
    
    title = activity_input.get("title", "Approval Required")
    description = activity_input.get("description", "")
    details = activity_input.get("details", {})
    
    # Extract key details
    top_candidate = details.get("top_candidate", {})
    confidence = details.get("confidence", 0)
    blast_radius = details.get("blast_radius", {})
    recommended_action = details.get("recommended_action", "rollback_deployment")
    remediation_params = details.get("remediation_params", {})
    
    facts = [
        {"title": "Incident ID", "value": activity_input.get("incident_id", "N/A")},
        {"title": "Affected Service", "value": details.get("affected_service", "N/A")},
        {"title": "Top Candidate", "value": f"{top_candidate.get('service_name', 'N/A')} ({top_candidate.get('change_type', 'N/A')})"},
        {"title": "Confidence", "value": f"{confidence:.1%}"},
        {"title": "Recommended Action", "value": recommended_action.replace("_", " ").title()},
        {"title": "Blast Radius", "value": f"{blast_radius.get('total_services_affected', 0)} services"},
    ]
    
    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        facts.append({"title": "Expires", "value": expires_dt.strftime("%Y-%m-%d %H:%M UTC")})
    
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": " Approval Required",
                            "weight": "Bolder",
                            "size": "Large",
                            "color": "Attention"
                        },
                        {
                            "type": "TextBlock",
                            "text": title,
                            "wrap": True,
                            "size": "Medium"
                        },
                        {
                            "type": "TextBlock",
                            "text": description,
                            "wrap": True,
                            "color": "Default"
                        },
                        {
                            "type": "FactSet",
                            "facts": facts
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Recommended Action:** {recommended_action.replace('_', ' ').title()}",
                            "wrap": True,
                            "weight": "Bolder"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Parameters: {json.dumps(remediation_params, indent=2)}",
                            "wrap": True,
                            "fontType": "Monospace",
                            "size": "Small"
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Approve",
                            "url": approve_url,
                            "style": "positive"
                        },
                        {
                            "type": "Action.OpenUrl",
                            "title": " Reject",
                            "url": reject_url,
                            "style": "destructive"
                        }
                    ]
                }
            }
        ]
    }


def _build_escalation_card(
    activity_input: Dict[str, Any],
    expires_at: Optional[str]
) -> Dict[str, Any]:
    """Build Teams adaptive card for escalation."""
    
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": " Escalation Required",
                            "weight": "Bolder",
                            "size": "Large",
                            "color": "Attention"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Workflow {activity_input.get('workflow_id')} requires escalation",
                            "wrap": True,
                            "size": "Medium"
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Incident ID", "value": activity_input.get("incident_id", "N/A")},
                                {"title": "Original Approver", "value": activity_input.get("original_approver", "primary_oncall")},
                                {"title": "Escalation Level", "value": str(activity_input.get("escalation_level", 1))},
                                {"title": "Escalation Target", "value": activity_input.get("escalation_target", "secondary_oncall")},
                            ]
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "View in ChangeTrace",
                            "url": activity_input.get("dashboard_url", "#")
                        }
                    ]
                }
            }
        ]
    }