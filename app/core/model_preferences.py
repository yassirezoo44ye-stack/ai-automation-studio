"""User-selectable models for general chat and code generation (not agent configs)."""
from typing import Literal

ChatModel = Literal['claude-sonnet-4-6', 'claude-opus-4-8', 'claude-haiku-4-5-20251001']
BuildModel = Literal['claude-sonnet-4-6', 'claude-opus-4-8']
DEFAULT_MODEL = 'claude-sonnet-4-6'
