"""Service layer package.

Re-export selected objects from subpackages for convenience.
"""

from .ai.ai_service import AIService, ai_service

__all__ = ["AIService", "ai_service"]