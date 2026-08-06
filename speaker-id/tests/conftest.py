"""Conftest for speaker-id tests.

Mocks heavy ML dependencies (speechbrain) so tests can run without
GPU or model downloads.
"""
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("DEVICE", "cpu")

# Mock heavy ML modules before any application imports
for mod_name in [
    "speechbrain",
    "speechbrain.inference",
    "speechbrain.inference.speaker",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
