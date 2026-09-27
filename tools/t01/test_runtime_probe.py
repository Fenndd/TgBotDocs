"""Protect the measurement harness from recording false successes."""
import json
from pathlib import Path

import httpx
import pytest

from runtime_probe import EXPECTED, Runtime


def runtime_for(events, idle=True):
    runtime = Runtime(Path("unused"), {"context": 4096}, 18081)

    def handle(request):
        if request.url.path == "/slots":
            return httpx.Response(200, json=[{"is_processing": not idle}])
        if isinstance(events, Exception):
            raise events
        content = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(200, text=content)

    runtime.client = httpx.Client(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1")
    runtime.metrics = type("Metrics", (), {"snapshot": lambda *args: {"samples": 0}})()
    return runtime


def event(content, prompt=500):
    return {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}],
            "timings": {"prompt_n": prompt, "cache_n": 0}}


def test_rejects_valid_json_with_unrequested_field():
    runtime = runtime_for([event(json.dumps({**EXPECTED, "extra": "private"}))])
    result = runtime.request([], expected=EXPECTED)
    assert not result["ok"]
    assert result["parse_or_contract_error"]
    assert "private" not in json.dumps(result)


def test_shape_compliance_does_not_imply_accuracy():
    runtime = runtime_for([event(json.dumps({"reference": "wrong", "amount": "0"}))])
    result = runtime.request([], expected=EXPECTED)
    assert result["schema_valid"] and not result["exact_match"]


def test_short_answer_does_not_prove_full_output_reserve():
    runtime = runtime_for([event(json.dumps(EXPECTED), prompt=3900)])
    result = runtime.request([], expected=EXPECTED)
    assert result["ok"]
    assert result["output_reserve_fits_context"] is False


def test_no_next_request_after_unconfirmed_release():
    runtime = runtime_for([event(json.dumps(EXPECTED))])
    runtime.idle = lambda: {"confirmed": False, "release_s": 10.0}
    assert not runtime.request([])["slot"]["confirmed"]
    with pytest.raises(RuntimeError, match="restart is required"):
        runtime.request([])


def test_read_timeout_is_not_success_and_content_not_recorded():
    runtime = runtime_for(httpx.ReadTimeout("secret server content"))
    result = runtime.request([])
    assert result["timed_out"] and result["timeout_type"] == "ReadTimeout"
    assert not result["ok"] and result["slot"]["confirmed"]
    assert "secret" not in json.dumps(result)


def test_cancelled_partial_stream_not_recorded_as_valid_result():
    runtime = runtime_for([event('{"reference":"')])
    result = runtime.request([], cancel_after_chunks=1)
    assert result["cancelled"] and not result["ok"]
    assert result["received_content_chunks"] == 1
    assert result["slot"]["confirmed"]
