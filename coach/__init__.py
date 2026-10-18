"""AI coach subsystem: all LLM logic lives in this package."""
import os
import sys

# coach modules import `models` / `schemas` using the same flat names as api/index.py.
_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'api'))
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)
