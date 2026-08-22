"""Stable processing-scene contract boundary.

The route remains registered by :mod:`akc_api.trust_api`; this module exposes
the masterplan-named surface without duplicating authorization or query logic.
"""

from akc_api.trust_api import SceneResponse, job_scene

__all__ = ["SceneResponse", "job_scene"]
