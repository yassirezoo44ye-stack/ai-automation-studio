"""Isolated BYOK test imports: avoid booting the production AI gateway.

Only for the focused BYOK test suite invoked with --confcutdir=tests/ai.
Source modules below remain the real repository modules, not mocks.
"""
import sys
from pathlib import Path
from types import ModuleType

root = Path(__file__).resolve().parents[2]
for name, relative in (("app.ai", "app/ai"), ("app.tenancy", "app/tenancy")):
    if name not in sys.modules:
        package = ModuleType(name)
        package.__package__ = name
        package.__path__ = [str(root / relative)]
        sys.modules[name] = package
