"""
LLM Phraser for ChangeTrace Postmortem Generator

Uses LLM only for natural language phrasing
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMPhraser:
    """
    Uses LLM only for natural language phrasing of deterministic findings.
    
    """
    
    def __init__(self):
        self.enabled = os.getenv("USE_LLM_FOR_REPORTS", "false").lower() == "true"
        self.endpoint = os.getenv("LLM_ENDPOINT")
        self.api_key = os.getenv("LLM_API_KEY")
        self.model = os.getenv("LLM_MODEL", "gpt-4")
        
        if self.enabled and not self.endpoint:
            logger.warning("LLM enabled but no endpoint configured")
            self.enabled = False
    
    async def enhance_postmortem(
        self,
        markdown: str,
        structured_data: Dict[str, Any]
    ) -> str:
        """
        Enhance postmortem markdown with better phrasing.
        
        The LLM is given strict instructions to only improve phrasing.
        """
        if not self.enabled:
            return markdown
        
        prompt = self._build_enhancement_prompt(markdown, structured_data)
        
        try:
            enhanced = await self._call_llm(prompt)
            return enhanced
        except Exception as e:
            logger.error(f"LLM enhancement failed: {e}")
            return markdown
    
    def _build_enhancement_prompt(
        self,
        markdown: str,
        structured_data: Dict[str, Any]
    ) -> str:
        """Build strict prompt for LLM enhancement."""
        
        return f"""You are a technical writer improving a postmortem document.

STRICT RULES - VIOLATION MEANS YOUR OUTPUT WILL BE DISCARDED:
1. DO NOT change any facts, numbers, timestamps, or causal claims
2. DO NOT add new causal claims or root cause hypotheses
3. DO NOT change confidence scores, percentages, or metrics
4. DO NOT add new recommendations or action items
5. ONLY improve readability, flow, and professional tone
6. Keep all markdown structure intact
7. Preserve all tables, lists, and formatting exactly

STRUCTURED DATA (for reference - do not modify):
{structured_data}

ORIGINAL MARKDOWN:
{markdown}

Return ONLY the enhanced markdown with improved phrasing."""
    
    async def _call_llm(self, prompt: str) -> str:
        """Call LLM API."""
        
        # will use gemini flash 2.5 api 
        # For now, return original
        logger.info("LLM call would be made here")
        return prompt.split("ORIGINAL MARKDOWN:\n")[1] if "ORIGINAL MARKDOWN:\n" in prompt else prompt
    
    async def enhance_slack_summary(
        self,
        summary: str,
        incident_data: Dict[str, Any]
    ) -> str:
        """Enhance Slack notification summary."""
        
        if not self.enabled:
            return summary
        
        prompt = f"""Rewrite this Slack notification for clarity and professionalism.
        
DO NOT change any facts, numbers, or service names.
Only improve phrasing and tone.

Original: {summary}

Incident context: {incident_data.get('title', 'N/A')} - {incident_data.get('severity', 'N/A')}"""

        try:
            return await self._call_llm(prompt)
        except Exception as e:
            logger.error(f"LLM Slack enhancement failed: {e}")
            return summary
    
    async def enhance_approval_request(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhance approval request description."""
        
        if not self.enabled:
            return request
        
        # Only enhance the description field
        if "description" in request:
            prompt = f"""Rewrite this approval request description for clarity.
            
DO NOT change any facts, service names, confidence scores, or recommended actions.
Only improve readability.

Original: {request['description']}"""

            try:
                enhanced = await self._call_llm(prompt)
                request["description"] = enhanced
            except Exception as e:
                logger.error(f"LLM approval enhancement failed: {e}")
        
        return request