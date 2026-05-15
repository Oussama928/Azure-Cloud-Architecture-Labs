"""
Template Renderer for ChangeTrace Postmortem Generator

Renders structured postmortem data into markdown using Jinja2 templates.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


class TemplateRenderer:
    """Renders postmortem documents from structured data using Jinja2 templates."""
    
    def __init__(self, template_dir: Optional[str] = None):
        if template_dir is None:
            template_dir = "services/postmortem-generator/templates"
        
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        self.env.filters['datetime_format'] = self._datetime_format
        self.env.filters['percentage'] = self._percentage
        self.env.filters['duration_minutes'] = self._duration_minutes
    
    def _datetime_format(self, value: str, format_str: str = "%Y-%m-%d %H:%M UTC") -> str:
        """Format ISO datetime string."""
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.strftime(format_str)
        except:
            return value
    
    def _percentage(self, value: float, decimals: int = 1) -> str:
        """Format as percentage."""
        return f"{value * 100:.{decimals}f}%"
    
    def _duration_minutes(self, start: str, end: str) -> int:
        """Calculate duration in minutes between two ISO timestamps."""
        try:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            return int((end_dt - start_dt).total_seconds() / 60)
        except:
            return 0
    
    def render_postmortem(self, postmortem_data: Dict[str, Any]) -> str:
        """Render postmortem from structured data."""
        
        template = self.env.get_template("postmortem.md.j2")
        return template.render(**postmortem_data)
    
    def render_slack_summary(self, postmortem_data: Dict[str, Any]) -> str:
        """Render Slack-friendly summary."""
        
        template = self.env.get_template("slack_summary.md.j2")
        return template.render(**postmortem_data)
    
    def render_approval_request(self, approval_data: Dict[str, Any]) -> str:
        """Render approval request for Teams/Slack."""
        
        template = self.env.get_template("approval_request.md.j2")
        return template.render(**approval_data)


# Default templates as strings (used if template files don't exist)
DEFAULT_POSTMORTEM_TEMPLATE = "to be defined"