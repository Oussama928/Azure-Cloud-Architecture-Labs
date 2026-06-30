import logging
import os
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

class TemplateRenderer:
    """Renders postmortem documents from structured data using Jinja2 templates."""

    def __init__(self, template_dir: str | None = None):
        if template_dir is None:
            template_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "templates",
            )
        self.template_dir = template_dir

        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters['datetime_format'] = self._datetime_format
        self.env.filters['percentage'] = self._percentage
        self.env.filters['duration_minutes'] = self._duration_minutes

    def _datetime_format(self, value: str, format_str: str = "%Y-%m-%d %H:%M UTC") -> str:
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.strftime(format_str)
        except Exception:
            return value

    def _percentage(self, value: float | None, decimals: int = 1) -> str:
        if value is None:
            return "N/A"
        return f"{value * 100:.{decimals}f}%"

    def _duration_minutes(self, start: str, end: str) -> int:
        try:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            return int((end_dt - start_dt).total_seconds() / 60)
        except Exception:
            return 0

    def _render_with_template(self, name: str, data: dict[str, Any]) -> str:
        try:
            template = self.env.get_template(name)
            return template.render(**data)
        except Exception as e:
            logger.warning("Template %s rendering failed: %s", name, e)
            return ""

    def render_postmortem(self, postmortem_data: dict[str, Any]) -> str:
        return self._render_with_template("postmortem.md.j2", postmortem_data)

    def render_slack_summary(self, postmortem_data: dict[str, Any]) -> str:
        return self._render_with_template("slack_summary.md.j2", postmortem_data)

    def render_approval_request(self, approval_data: dict[str, Any]) -> str:
        return self._render_with_template("approval_request.md.j2", approval_data)
