"""Conftest for speaker-id tests.

Mocks heavy ML dependencies (speechbrain) so tests can run without
GPU or model downloads.
"""

import os
import sys
from unittest.mock import MagicMock

import numpy as np

os.environ.setdefault("DEVICE", "cpu")

# Mock heavy ML modules before any application imports
for mod_name in [
    "speechbrain",
    "speechbrain.inference",
    "speechbrain.inference.speaker",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

_FAKE_EPS = 1e-12


class _Tensor:
    """Minimal numpy-backed stand-in for torch.Tensor."""

    def __init__(self, array):
        self._array = np.asarray(array)

    def mean(self, dim):
        return _Tensor(self._array.mean(axis=dim))

    def cpu(self):
        return self

    def numpy(self):
        return self._array


def _normalize(tensor, p, dim):
    array = np.asarray(tensor._array, dtype=np.float32)
    norm = np.linalg.norm(array, ord=p, axis=dim, keepdims=True)
    return _Tensor(array / np.maximum(norm, _FAKE_EPS))


_fake_functional = MagicMock()
_fake_functional.normalize = _normalize
_fake_torch = MagicMock()
_fake_torch.tensor = lambda x, dtype=None: _Tensor(x)
_fake_torch.nn.functional = _fake_functional


class _FakeOutOfMemoryError(RuntimeError):
    """Stand-in for ``torch.OutOfMemoryError`` (a RuntimeError subclass)."""


_fake_torch.OutOfMemoryError = _FakeOutOfMemoryError

sys.modules.setdefault("torch", _fake_torch)
sys.modules.setdefault("torch.nn", MagicMock())
sys.modules["torch.nn"].functional = _fake_functional
sys.modules.setdefault("torch.nn.functional", _fake_functional)
