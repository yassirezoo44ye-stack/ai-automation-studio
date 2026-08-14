"""
Re-export shim: allows factory.py to import the App Builder schema
migration without the "009_" prefix (Python identifiers cannot start
with a digit).

This file is intentionally thin — all logic lives in 009_app_builder.py.
"""
from migrations.versions._009_app_builder import upgrade, downgrade

__all__ = ["upgrade", "downgrade"]
