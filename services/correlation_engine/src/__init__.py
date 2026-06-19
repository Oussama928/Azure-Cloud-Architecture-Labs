"""
Correlation Engine Service

Correlates incidents with recent changes to identify root causes.
"""

from .correlator import IncidentCorrelator

__all__ = ["IncidentCorrelator"]