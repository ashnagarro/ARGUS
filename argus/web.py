"""Small loopback-only plan upload and review UI using the Python standard library."""

from __future__ import annotations

from collections import Counter
from email.parser import BytesParser
from email.policy import default
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .redaction import redact_plan
from .verdict import verdict_explanation, verdict_label


MAX_UPLOAD = 5 * 1024 * 1024


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _document(title: str, body: str) -> bytes:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(title)} · ARGUS</title><style>"
            "body{font:16px/1.55 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#17212b;background:#f3f6f8}"
            "main,section{background:white;border:1px solid #ccd7df;border-radius:12px;padding:1.5rem;margin:1rem 0}"
            "h1,h2,h3{line-height:1.2}h1{font-size:3rem;margin:.2rem 0}label{display:block;margin:.8rem 0}"
            "select{font:inherit;padding:.65rem;border:1px solid #bccbd7;border-radius:7px;margin-left:.5rem}"
            "button{font:inherit;padding:.7rem 1.2rem;margin:.25rem 0;border:0;border-radius:7px;background:#15467d;color:white;cursor:pointer}"
            "button:hover{background:#0c355f}button:disabled{background:#9aa7b5;cursor:not-allowed}"
            ".drop{display:block;position:relative;border:2px dashed #7899b5;padding:3rem 1.5rem;border-radius:12px;text-align:center;background:#f8fbfd;cursor:pointer}"
            ".drop.drag,.drop:focus-within{background:#e8f2ff;border-color:#15467d}.drop input{position:absolute;width:1px;height:1px;opacity:0}"
            ".drop strong{font-size:1.3rem}.drop p{margin:.5rem 0}.error{color:#a11825;font-weight:700}"
            ".verdict{padding:1.2rem;border-radius:12px;color:white;font-size:2.4rem;font-weight:800}.go{background:#176833}"
            ".no-go{background:#a11825}.conditions{background:#9a5a00}.needs-human{background:#70479a}"
            ".severity{display:flex;flex-wrap:wrap;gap:.65rem;margin:1rem 0}.severity span{background:#e2eaf0;border-radius:8px;padding:.45rem .8rem}"
            "article{border-top:1px solid #e1e7ee;padding:.9rem 0}.rule-ref,small,.muted{color:#526677}"
            "a{color:#15467d}code{overflow-wrap:anywhere}ul,ol{padding-left:1.4rem}"
            "footer{border-top:2px solid #ccd7df;margin:2rem 0;padding:1rem 0;color:#526677}</style></head><body>"
            f"<header><h1>ARGUS</h1><p>Evidence-backed safety gate for infrastructure changes</p></header>{body}"
            "<footer>Uploads go to the local server on 127.0.0.1; a redacted copy is saved in ledger/uploads/. "
            "If AI research is selected, the redacted change is sent to OpenAI.</footer></body></html>"
            ).encode("utf-8")


def home_page(*, live_available: bool) -> bytes:
    live = "" if live_available else " disabled"
    hint = "" if live_available else "<small>Set OPENAI_API_KEY to enable live research.</small>"
    return _document("Upload a plan", "<main><h2>Check a Terraform plan</h2>"
                     "<p>Maximum file size: 5 MB.</p>"
                     "<form action='/check' method='post' enctype='multipart/form-data'>"
                     "<label class='drop' id='drop' for='plan'>"
                     "<input id='plan' name='plan' type='file' accept='.json,application/json'>"
                     "<strong>Drop a Terraform plan JSON here or click to choose</strong>"
                     "<p id='file-info'>No file selected · Maximum 5 MB</p></label>"
                     "<p class='error' id='upload-error' role='alert' hidden></p>"
                     "<label>Change made by <select name='author'>"
                     "<option value='human'>A person</option><option value='agent'>An AI agent</option>"
                     "</select></label>"
                     f"<label><input type='checkbox' name='live' value='1'{live}> "
                     "Research with AI (sends the redacted change to OpenAI)</label>"
                     f"{hint}"
                     "<p><button type='submit'>Review plan</button></p></form>"
                     "</main><p><a href='/console'>Open console</a></p>"
                     "<script>const d=document.getElementById('drop'),f=document.getElementById('plan'),"
                     "info=document.getElementById('file-info'),err=document.getElementById('upload-error');"
                     "function selected(file){err.hidden=true;if(!file){info.textContent='No file selected · Maximum 5 MB';return false;}"
                     "if(!file.name.toLowerCase().endsWith('.json')){err.textContent='Choose a Terraform plan .json file.';}"
                     "else if(file.size>5242880){err.textContent='File exceeds the 5 MB limit. Choose a smaller JSON file.';}"
                     "else{info.textContent=file.name+' · '+file.size.toLocaleString()+' bytes';return true;}"
                     "err.hidden=false;f.value='';info.textContent='No file selected · Maximum 5 MB';return false;}"
                     "f.addEventListener('change',()=>selected(f.files[0]));"
                     "f.form.addEventListener('submit',e=>{if(!selected(f.files[0])){e.preventDefault();"
                     "if(!f.files[0]&&err.hidden){err.textContent='Choose a Terraform plan JSON file.';err.hidden=false;}}});"
                     "d.addEventListener('dragover',e=>{e.preventDefault();d.classList.add('drag')});"
                     "d.addEventListener('dragleave',()=>d.classList.remove('drag'));"
                     "d.addEventListener('drop',e=>{e.preventDefault();d.classList.remove('drag');"
                     "if(e.dataTransfer.files.length){f.files=e.dataTransfer.files;selected(f.files[0]);}});</script>")


def _list(items: list[Any] | tuple[Any, ...], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{_e(item)}</li>" for item in items) + f"</{tag}>" if items else "<p>None.</p>"


def _safe_source(url: Any) -> str:
    if not isinstance(url, str) or urlparse(url).scheme not in ("http", "https"):
        return ""
    return f" <a href='{_e(url)}' rel='noopener noreferrer'>Source</a>"


def result_page(record: dict[str, Any]) -> bytes:
    verdict = str(record.get("verdict", "NEEDS HUMAN"))
    css = {"GO": "go", "NO-GO": "no-go", "GO-WITH-CONDITIONS": "conditions"}.get(verdict, "needs-human")
    counts = Counter(
        str(finding.get("severity", "unknown")).lower()
        for finding in record.get("rule_findings", []) + record.get("ai_findings", [])
        if isinstance(finding, dict)
    )
    severities = ("critical", "high", "medium", "low", "info")
    severity_html = "".join(
        f"<span><strong>{_e(level.title())}</strong> {counts[level]}</span>"
        for level in (*severities, *(level for level in counts if level not in severities))
    )
    cards = []
    for finding in record.get("rule_findings", []):
        if not isinstance(finding, dict):
            continue
        reference = f"({finding.get('rule_id', '')} · {finding.get('name', '')})"
        controls = finding.get("controls") or []
        cards.append("<article>" + f"<h3>{_e(finding.get('title', 'Finding'))}</h3>"
                     f"<p>Resource: {_e(finding.get('resource', ''))} · "
                     f"Trigger: {_e(finding.get('message', ''))}</p>"
                     f"<p><small class='rule-ref'>{_e(reference)}"
                     + (f" · Controls: {_e(', '.join(controls))}" if controls else "") + "</small></p>"
                     f"<p><strong>Why:</strong> {_e(finding.get('why_it_matters', ''))}</p>"
                     f"<p><strong>How to fix:</strong> {_e(finding.get('how_to_fix', ''))}</p></article>")
    for finding in record.get("ai_findings", []):
        if not isinstance(finding, dict):
            continue
        evidence = "".join(
            f"<li>{_e(item.get('doc_id', ''))}: {_e(item.get('quote', ''))}{_safe_source(item.get('url'))}</li>"
            for item in finding.get("evidence", []) if isinstance(item, dict)
        )
        reference = f"({finding.get('id', '')} · {finding.get('name') or 'AI research'})"
        cards.append(f"<article><h3>{_e(finding.get('headline') or finding.get('claim', 'AI finding'))}</h3>"
                     f"<p>{_e(finding.get('claim', ''))}</p>"
                     f"<p><small class='rule-ref'>{_e(reference)}</small></p>"
                     f"<p><strong>How to fix:</strong> "
                     f"{_e(finding.get('recommended_action', ''))}</p><p>Evidence:</p><ul>{evidence}</ul></article>")
    explanation = verdict_explanation(verdict)
    body = (f"<main><div class='verdict {css}'>{_e(verdict_label(verdict))}</div>"
            + (f"<p>{_e(explanation)}</p>" if explanation else "")
            + f"<div class='severity' aria-label='Findings by severity'>{severity_html}</div>"
            f"<p>Run ID: <code>{_e(record.get('run_id', ''))}</code></p>"
            "<form action='/' method='get'><button type='submit'>Review another plan</button></form>"
            "<p><a href='/console'>Open console</a></p></main>"
            "<section><h2>Findings</h2>" + ("".join(cards) if cards else "<p>None.</p>") + "</section>"
            "<section><h2>" + ("Required fixes before merge" if verdict == "NO-GO" else "Conditions")
            + "</h2>" + _list(record.get("conditions") or []) + "</section>"
            "<section><h2>Step timeline</h2>" + _list(record.get("trace_steps") or [], ordered=True) + "</section>"
            "<section><h2>Ask you</h2>" + _list(record.get("ask_you") or []) + "</section>")
    return _document("Review result", body)


def _plan(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD:
        raise ValueError("Plan is larger than 5 MB. Choose a smaller JSON export.")
    try:
        plan = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("This is not valid UTF-8 Terraform plan JSON.") from error
    if (not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list)
            or not isinstance(plan.get("format_version"), str)):
        raise ValueError("This file does not look like a Terraform plan JSON export.")
    return plan


def review_upload(data: bytes, *, filename: str, author: str, live: bool, root: Path) -> dict[str, Any]:
    """Validate and save only a redacted plan before invoking the review flow."""
    if Path(filename).suffix.lower() != ".json":
        raise ValueError("Choose a Terraform plan .json file.")
    if live and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Live AI research is unavailable until OPENAI_API_KEY is set.")
    if not author.strip() or len(author) > 120:
        raise ValueError("Enter an author of at most 120 characters.")
    plan = redact_plan(_plan(data))
    uploads = root / "ledger" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    path = uploads / f"{uuid4().hex}.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    from . import cli

    demo_options: dict[str, Any] = {
        "author": author.strip(), "scholar_mode": "live" if live else None,
        "check_agent_scope": False,
    }
    cli.run_check(path, emit_output=False, **demo_options)
    return json.loads((root / ".cache" / "last_run.json").read_text(encoding="utf-8"))


def make_handler(root: Path) -> type[BaseHTTPRequestHandler]:
    root = root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, message: str, status: int = 400) -> None:
            self._send(_document("Could not review plan", f"<main><h2>Could not review plan</h2>"
                                 f"<p>{_e(message)}</p><a href='/'>Try another plan</a></main>"), status)

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(home_page(live_available=bool(os.environ.get("OPENAI_API_KEY"))))
            elif self.path == "/console":
                from .console import write_console

                path = write_console(root)
                self._send(path.read_bytes())
            else:
                self._error("Page not found.", 404)

        def do_POST(self) -> None:
            try:
                if self.path == "/check":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > MAX_UPLOAD + 65536:
                        raise ValueError("Upload must be a Terraform plan JSON file of at most 5 MB.")
                    content_type = self.headers.get("Content-Type", "")
                    if not content_type.lower().startswith("multipart/form-data;"):
                        raise ValueError("Use the plan upload form to send a JSON file.")
                    message = BytesParser(policy=default).parsebytes(
                        (f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n").encode()
                        + self.rfile.read(length))
                    fields = {part.get_param("name", header="content-disposition"): part
                              for part in message.iter_parts()}
                    file_part = fields.get("plan")
                    if file_part is None or not file_part.get_filename():
                        raise ValueError("Choose a Terraform plan JSON file.")
                    author_part = fields.get("author")
                    author = author_part.get_content() if author_part else "human"
                    if author == "agent":
                        author = "agent:web"
                    record = review_upload(file_part.get_payload(decode=True),
                                           filename=file_part.get_filename(), author=str(author),
                                           live="live" in fields, root=root)
                else:
                    self._error("Page not found.", 404)
                    return
            except (ValueError, OSError, TypeError, KeyError) as error:
                self._error(str(error))
                return
            self._send(result_page(record))

    return Handler


def serve(root: Path, port: int = 8765) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    with HTTPServer(("127.0.0.1", port), make_handler(root)) as server:
        print(f"ARGUS Web: http://127.0.0.1:{port}/")
        server.serve_forever()
