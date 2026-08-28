import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        pass
    def get(self, *args, **kwargs):
        return lambda function: function

    def on_event(self, *args, **kwargs):
        return lambda function: function


sys.modules.setdefault("fastapi", types.SimpleNamespace(FastAPI=_FakeFastAPI))
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object, HTTPError=Exception))

from main import poll_once


def test_poll_reports_per_job_failure_and_continues():
    claim = MagicMock(status_code=200)
    claim.json.return_value = {"job_id": 7, "job_type": "quick"}
    client = AsyncMock()
    client.post.side_effect = [claim, MagicMock(status_code=200)]
    with patch("main._process_job", new_callable=AsyncMock, side_effect=RuntimeError("decode failed")):
        assert asyncio.run(poll_once(client))
    assert client.post.call_count == 2
    assert client.post.call_args_list[1].kwargs["json"] == {"error": "decode failed"}
