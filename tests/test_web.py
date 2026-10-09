"""The local upload page never persists or renders plan secrets as HTML."""

import json
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from argus import cli
from argus.redaction import redact_plan
from argus.web import MAX_UPLOAD, _plan, home_page, make_handler, result_page, review_upload


ROOT = Path(__file__).resolve().parents[1]


def test_home_controls_and_rejects_nonplans(monkeypatch):
    disabled = home_page(live_available=False).decode()
    enabled = home_page(live_available=True).decode()
    assert "Use AI research (live)" in disabled and " disabled" in disabled
    assert "Use AI research (live)" in enabled and " disabled" not in enabled
    assert all(f"/sample/{sample}" in disabled for sample in
               ("act1", "act2", "act3", "act5", "act7-risky", "act7-fixed"))
    with pytest.raises(ValueError, match="Terraform plan"):
        _plan(b'{"hello":"world"}')
    with pytest.raises(ValueError, match="5 MB"):
        _plan(b"x" * (MAX_UPLOAD + 1))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="unavailable"):
        review_upload(b"{}", filename="plan.json", author="human", live=True, root=ROOT)


def test_upload_saves_redacted_plan_and_html_escapes_untrusted_values(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    plan = json.loads((ROOT / "fixtures" / "plans" / "real_risky_plan.json").read_text())
    plan["resource_changes"][1]["address"] = "<script>alert(1)</script>"
    data = json.dumps(plan).encode()
    record = review_upload(data, filename="risky.json", author="<img src=x>", live=False,
                           root=tmp_path)
    saved = list((tmp_path / "ledger" / "uploads").glob("*.json"))
    assert len(saved) == 1
    page = result_page(record).decode()
    for output in (saved[0].read_text(), page,
                   (tmp_path / ".cache" / "last_run.json").read_text(),
                   (tmp_path / "ledger" / "ledger.jsonl").read_text()):
        assert "Sup3rSecret-FAKE-123" not in output
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img src=x>" not in page
    assert "Run ID" in page and "Step timeline" in page and "Ask you" in page
    assert "[REDACTED]" in saved[0].read_text()
    assert redact_plan(plan)["resource_changes"][1]["change"]["after"]["password"] == "[REDACTED]"


def test_result_page_escapes_evidence_and_rejects_unsafe_source_links():
    record = {"verdict": "NO-GO", "run_id": "abc", "rule_findings": [],
              "ai_findings": [{"claim": "<script>x</script>", "recommended_action": "fix",
                               "evidence": [{"doc_id": "d", "quote": "<b>unsafe</b>",
                                             "url": "javascript:alert(1)"}]}],
              "conditions": ["<img>"], "trace_steps": ["checked"], "ask_you": []}
    page = result_page(record).decode()
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page
    assert "href='javascript:" not in page
    assert "&lt;img&gt;" in page


def test_loopback_server_serves_page_and_accepts_multipart(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    server = HTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200 and b"Check a Terraform plan" in response.read()

        plan = (ROOT / "fixtures" / "plans" / "clean_change.json").read_bytes()
        boundary = "argus-test-boundary"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"author\"\r\n\r\nhuman\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"plan\"; filename=\"plan.json\"\r\n"
                "Content-Type: application/json\r\n\r\n").encode() + plan + f"\r\n--{boundary}--\r\n".encode()
        connection.request("POST", "/check", body,
                           {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        response = connection.getresponse()
        page = response.read()
        assert response.status == 200 and b"Run ID" in page
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
