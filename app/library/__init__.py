"""
Flow Library — module root.

Exposes init_library_schema() so factory.py can set up the library
tables on application startup (idempotent, CREATE TABLE IF NOT EXISTS).
"""

from app.library.schema import init_library_schema

__all__ = ["init_library_schema"]
