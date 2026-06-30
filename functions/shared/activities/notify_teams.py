"""
Activity: Notify Teams (Approval Requests, Escalations)

Sends notifications via Teams webhook, email, or other channels.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def main(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Send notification for approval request or escalation.
    """
    workflow_id = activity_input.get("workflow_id")
    notification_type = activity_input.get("notification_type", "approval_request")

    logger.info(f"Sending {notification_type} notification for workflow {workflow_id}")

    token = activity_input.get("token")
    callback_base = activity_input.get("callback_url")
    expires_at = activity_input.get("expires_at")

    if not token or not callback_base:
        raise ValueError("token and callback_url are required")

    approve_url = f"{callback_base}?token={token}&decision=approve"
    reject_url = f"{callback_base}?token={token}&decision=reject"

    teams_sent = await _send_teams_notification(
        activity_input, approve_url, reject_url, expires_at
    )

    email_sent = await _send_email_notification(
        activity_input, approve_url, reject_url, expires_at
    )

    return {
        "sent": teams_sent or email_sent,
        "channels": (["teams"] if teams_sent else []) + (["email"] if email_sent else []),
        "approval_url": approve_url,
        "reject_url": reject_url,
        "expires_at": expires_at
    }


async def _send_teams_notification(
    activity_input: dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: str | None
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
    activity_input: dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: str | None
) -> bool:
    """Send email notification via SendGrid."""
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "changetrace@company.com")

    if not api_key:
        logger.warning("SENDGRID_API_KEY not configured, skipping email notification")
        return False

    notification_type = activity_input.get("notification_type", "approval_request")
    details = activity_input.get("details", {})
    top_candidate = details.get("top_candidate", {})

    if notification_type == "approval_request":
        subject = f"🚨 Approval Required: {activity_input.get('title', 'Incident Approval')}"
        html_content = f"""
        <h2>🚨 {activity_input.get('title', 'Incident Approval Required')}</h2>
        <p>{activity_input.get('description', '')}</p>
        <table>
            <tr><td><strong>Incident ID</strong></td><td>{activity_input.get('incident_id', 'N/A')}</td></tr>
            <tr><td><strong>Affected Service</strong></td><td>{details.get('affected_service', 'N/A')}</td></tr>
            <tr><td><strong>Top Candidate</strong></td><td>{top_candidate.get('service_name', 'N/A')} ({top_candidate.get('change_type', 'N/A')})</td></tr>
            <tr><td><strong>Confidence</strong></td><td>{details.get('confidence', 0)*100:.1f}%</td></tr>
            <tr><td><strong>Recommended Action</strong></td><td>{details.get('recommended_action', 'rollback_deployment').replace('_', ' ').title()}</td></tr>
            <tr><td><strong>Blast Radius</strong></td><td>{details.get('blast_radius', {}).get('total_services_affected', 0)} services</td></tr>
            <tr><td><strong>Expires</strong></td><td>{expires_at or 'N/A'}</td></tr>
        </table>
        <p><strong>Recommended Action:</strong> {details.get('recommended_action', 'rollback_deployment').replace('_', ' ').title()}</p>
        <p>Parameters: <pre>{json.dumps(details.get('remediation_params', {}), indent=2)}</pre></p>
        <p>
            <a href="{approve_url}" style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">✅ Approve</a>
            <a href="{reject_url}" style="background-color: #dc3545; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin-left: 10px;">❌ Reject</a>
        </p>
        <p><small>Expires: {expires_at or 'N/A'}</small></p>
        """
    else:
        subject = f"⚠️ ESCALATION: {activity_input.get('title', 'Incident Approval Timeout')}"
        html_content = f"""
        <h2>⚠️ ESCALATION: Incident Approval Timeout</h2>
        <p>Primary approval expired for workflow {activity_input.get('workflow_id')}. Escalated to secondary on-call.</p>
        <table>
            <tr><td><strong>Incident ID</strong></td><td>{activity_input.get('incident_id', 'N/A')}</td></tr>
            <tr><td><strong>Original Approver</strong></td><td>{activity_input.get('original_approver', 'primary_oncall')}</td></tr>
            <tr><td><strong>Escalation Level</strong></td><td>{activity_input.get('escalation_level', 1)}</td></tr>
            <tr><td><strong>Escalation Target</strong></td><td>{activity_input.get('escalation_target', 'secondary_oncall')}</td></tr>
            <tr><td><strong>Expires</strong></td><td>{expires_at or 'N/A'}</td></tr>
        </table>
        <p><a href="{activity_input.get('approval_url', '#')}" style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">✅ Approve (Escalated)</a></p>
        """

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=from_email,
            to_emails=os.getenv("ONCALL_EMAIL", "oncall@company.com"),
            subject=subject,
            html_content=html_content
        )

        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info(f"Email notification sent: {response.status_code}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        return False


def _build_approval_card(
    activity_input: dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: str | None
) -> dict[str, Any]:
    """Build Teams adaptive card for approval request."""

    title = activity_input.get("title", "Approval Required")
    description = activity_input.get("description", "")
    details = activity_input.get("details", {})

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
    activity_input: dict[str, Any],
    expires_at: str | None
) -> dict[str, Any]:
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
