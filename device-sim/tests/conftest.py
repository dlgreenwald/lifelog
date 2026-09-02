"""Pytest fixtures for the device simulator integration tests.

The simulator uses client-credentials OIDC for its own identity (DEVICE_SIM_OIDC_*).
DEVICE_SIM_TEST_OIDC_SUB is the OIDC ``sub`` claim that the server resolves to a
user row — this user must exist in the DB (provisioned manually or via the server's
auto-provision logic). conftest.py only validates that the required env var is set.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def test_oidc_sub() -> str:
    """Return the configured DEVICE_SIM_TEST_OIDC_SUB.

    The test user corresponding to this sub must exist in the DB before running
    integration tests. No DB provisioning is performed here.
    """
    sub = os.environ.get("DEVICE_SIM_TEST_OIDC_SUB")
    if not sub:
        pytest.fail(
            "DEVICE_SIM_TEST_OIDC_SUB is not set. "
            "Set it to the oidc_sub of a pre-provisioned test user.",
        )
    return sub


@pytest.fixture
def ami_data_dir():
    meeting_id = os.environ.get("MEETING_ID", "EN2001a")
    return os.path.join(os.path.dirname(__file__), "..", "data", meeting_id)
