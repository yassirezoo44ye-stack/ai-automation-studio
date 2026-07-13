"""
AI Infrastructure — provider-agnostic gateway.

Import the gateway from this package:
    from app.ai import gateway
"""
from app.ai.gateway import AIGateway
from app.ai.schema import init_ai_usage_schema

__all__ = ["AIGateway", "init_ai_usage_schema"]
