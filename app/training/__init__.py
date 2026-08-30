"""
Training Studio — module root.

Exposes init_training_schema() so factory.py can set up the 12 training
tables on application startup (idempotent, CREATE TABLE IF NOT EXISTS).
"""

from app.training.schema import init_training_schema

__all__ = ["init_training_schema"]
