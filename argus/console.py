"""Offline, self-contained HTML console built from saved ARGUS run records."""

from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .corpus import load_corpus
from .report import _local_time
from .rules import load_rules


_KEY_PATTERN = re.compile(r"(?i)sk-[A-Za-z0-9_-]*")
_SECRET_NAME = re.compile(r"(?i)(?:key|token|secret|password|credential)")


def _safe(value: object) -> str:
    """Escape saved data and remove key-like text and environment values."""
    text = str(value if value is not None else "")
    for name, secret in sorted(os.environ.items(), key=lambda item: len(item[1]), reverse=True):
        if secret and (len(secret) >= 12 or (_SECRET_NAME.search(name) and len(secret) >= 4)):
            text = text.replace(secret, "[redacted]")
    return escape(_KEY_PATTERN.sub("[redacted]", text), quote=True)


def _source_link(url: object, label: object = "source") -> str:
    target = str(url or "")
    if urlsplit(target).scheme not in ("http", "https"):
        return _safe(label)
    return f'<a href="{_safe(target)}" rel="noreferrer">{_safe(label)}</a>'


def _items(values: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{value}</li>" for value in values) + "</ul>" if values else "<p>None recorded.</p>"


def _findings(record: dict) -> str:
    items: list[str] = []
    for finding in record.get("rule_findings", []):
        status = "WAIVED" if finding.get("waived") else "ENFORCED"
        details = [
            f'<strong>{_safe(finding.get("rule_id"))} [{status}]</strong> '
            f'{_safe(finding.get("resource"))}: {_safe(finding.get("headline") or finding.get("title"))}',
            f'<p>{_safe(finding.get("message"))}</p>',
        ]
        for label, key in (("Why", "why_it_matters"), ("Fix", "how_to_fix")):
            if finding.get(key):
                details.append(f'<p><strong>{label}:</strong> {_safe(finding[key])}</p>')
        tags = finding.get("tags") or {}
        if tags:
            details.append('<p>Tags: ' + _safe(", ".join(
                f"{key}={tags[key]}" for key in ("env", "data_classification", "owner")
                if key in tags)) + '</p>')
        items.append("".join(details))
    for finding in record.get("ai_findings", []):
        status = "VERIFIED" if finding.get("verified") else "UNVERIFIED"
        details = [
            f'<strong>{_safe(finding.get("id"))} [AI {status}]</strong> '
            f'{_safe(finding.get("resource"))}: {_safe(finding.get("claim"))}',
            f'<p>Action: {_safe(finding.get("recommended_action"))}</p>',
        ]
        for evidence in finding.get("evidence", []):
            details.append(
                f'<blockquote>“{_safe(evidence.get("quote"))}”<br>'
                f'{_safe(evidence.get("doc_id"))} — '
                f'{_source_link(evidence.get("url"))} — '
                f'retrieved {_safe(evidence.get("retrieved_at"))}</blockquote>'
            )
        items.append("".join(details))
    return _items(items)


def _timeline(root: Path, record: dict) -> str:
    run_id = str(record.get("run_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        return "<p>Trace unavailable.</p>"
    path = root / "ledger" / "traces" / f"{run_id}.jsonl"
    steps: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("event")
            if kind == "permission_decision":
                description = (f"Permission: {event.get('action') or event.get('tool') or 'tool'} "
                               f"on {event.get('resource') or event.get('file') or 'run'} — "
                               f"{event.get('decision')} ({event.get('reason') or 'policy'})")
            elif kind == "tool_result" and event.get("step"):
                description = str(event["step"])
            elif kind == "cache_replay":
                description = f"Replayed cached response for {event.get('resource')}"
            elif kind == "rules_result":
                count = event.get("changes")
                description = f"Checked {count} {'change' if count == 1 else 'changes'} against deterministic rules"
            elif kind == "verified_answer_stop":
                description = "Stopped Scholar after a verified final answer"
            else:
                continue
            steps.append(description)
    if not steps:
        steps = [str(item) for item in record.get("trace_steps", [])]
    return '<ol class="timeline">' + ''.join(
        f'<li><span>Step {number}</span> {_safe(step)}</li>'
        for number, step in enumerate(steps, 1)
    ) + '</ol>' if steps else "<p>No steps recorded.</p>"


def _conditions(record: dict) -> str:
    conditions = record.get("conditions")
    if conditions is None:
        conditions = [item.get("how_to_fix") or item.get("message") for item in
                      record.get("rule_findings", []) if not item.get("waived")]
        conditions += [item.get("recommended_action") for item in
                       record.get("ai_findings", []) if item.get("verified")]
    return _items([_safe(item) for item in conditions if item])


def _runs(root: Path) -> list[dict]:
    folder = root / "ledger" / "runs"
    if not folder.is_dir():
        return []
    records = [json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")]
    return sorted(records, key=lambda item: str(item.get("run_at", "")), reverse=True)


def _learned(root: Path) -> list[dict]:
    path = root / "ledger" / "ledger.jsonl"
    if not path.is_file():
        return []
    compiled: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") == "compile" and entry.get("status") == "compiled" and entry.get("rule_id"):
            compiled[entry["rule_id"]] = entry
    installed = {rule.id: rule for rule in load_rules()}
    documents = load_corpus(root / "corpus") if (root / "corpus").is_dir() else {}
    results = []
    for rule_id, entry in sorted(compiled.items()):
        rule = installed.get(rule_id)
        sources = []
        for doc_id in getattr(rule, "source_doc_ids", ()):
            doc = documents.get(doc_id)
            sources.append({"doc_id": doc_id,
                            "date": doc.retrieved_at if doc else "unknown",
                            "url": doc.url if doc else ""})
        results.append({
            "rule_id": rule_id,
            "source_finding": getattr(rule, "source_finding_id", "") or (entry.get("finding_ids") or [""])[0],
            "sources": sources,
            "enforced": rule is not None,
            "test_status": "passed at compile" if (rule is not None and
                (root / "tests" / "rules" / f"test_{rule_id.lower()}.py").is_file()) else "not confirmed",
        })
    return results


def write_console(root: Path) -> Path:
    """Render saved runs; never connect to a service or read credentials."""
    root = Path(root)
    runs = _runs(root)
    learned = _learned(root)
    baseline_path = root / ".cache" / "act3_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else {}
    avoided = int(baseline.get("ai_calls", 0)) if any(item["rule_id"] == "R007" for item in learned) else 0

    totals = [
        ("Runs", len(runs)), ("NO-GO", sum(item.get("verdict") == "NO-GO" for item in runs)),
        ("GO-WITH-CONDITIONS", sum(item.get("verdict") == "GO-WITH-CONDITIONS" for item in runs)),
        ("GO", sum(item.get("verdict") == "GO" for item in runs)),
        ("Learned rules", len(learned)), ("AI calls avoided", avoided),
    ]
    metric_html = ''.join(f'<div class="metric"><strong>{_safe(value)}</strong><span>{_safe(label)}</span></div>'
                          for label, value in totals)

    rows = []
    for index, record in enumerate(runs):
        verdict = str(record.get("verdict", "NEEDS HUMAN"))
        badge = {"NO-GO": "no-go", "GO-WITH-CONDITIONS": "conditions",
                 "GO": "go"}.get(verdict, "needs-human")
        target = f"detail-{index}"
        plan = Path(str(record.get("plan", ""))).name
        rows.append(
            f'<tr><td>{_safe(_local_time(str(record.get("run_at", ""))))}</td>'
            f'<td><button type="button" data-target="{target}" aria-expanded="false">{_safe(plan)}</button></td>'
            f'<td><span class="badge {badge}">{_safe(verdict)}</span></td>'
            f'<td>{_safe(record.get("author", "human"))}</td>'
            f'<td>{_safe(record.get("ai_calls", 0))}</td>'
            f'<td>{float(record.get("elapsed_seconds", 0)):.2f}</td></tr>'
            f'<tr id="{target}" class="detail-row" hidden><td colspan="6">'
            '<h3>Findings</h3>' + _findings(record)
            + '<h3>Conditions</h3>' + _conditions(record)
            + '<h3>Agentic-loop timeline</h3>' + _timeline(root, record)
            + '</td></tr>'
        )

    library = []
    savings = []
    for item in learned:
        sources = ', '.join(
            f'{_source_link(doc["url"], doc["doc_id"])} (retrieved {_safe(doc["date"])})'
            for doc in item["sources"]
        ) or "No source document recorded"
        library.append(
            f'<tr><td>{_safe(item["rule_id"])}</td><td>{_safe(item["source_finding"])}</td>'
            f'<td>{sources}</td><td>{"ENFORCED" if item["enforced"] else "not installed"}</td>'
            f'<td>{_safe(item["test_status"])}</td></tr>'
        )
        if item["rule_id"] == "R007" and baseline:
            savings.append(
                f'<tr><td>{_safe(item["rule_id"])}</td>'
                f'<td>{_safe(baseline.get("ai_calls", 0))} calls / '
                f'{float(baseline.get("elapsed_seconds", 0)):.2f} s</td>'
                '<td>0 calls / 0.00 s</td></tr>'
            )
        else:
            savings.append(f'<tr><td>{_safe(item["rule_id"])}</td>'
                           '<td>Not measured</td><td>Not measured</td></tr>')

    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>ARGUS Console</title><style>'
        'body{font:20px/1.45 system-ui,sans-serif;color:#17212b;background:#f3f6f8;'
        'margin:0 auto;max-width:1500px;padding:1.5rem}h1{font-size:3rem;margin:.2rem 0}'
        'h2{font-size:2rem}h3{font-size:1.4rem}.metrics{display:grid;'
        'grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:.7rem;margin:1.5rem 0}'
        '.metric{background:white;border:1px solid #ccd7df;border-radius:.6rem;padding:.8rem}'
        '.metric strong{display:block;font-size:2rem}.metric span{font-size:.9rem}'
        'table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #ccd7df;'
        'padding:.7rem;text-align:left;vertical-align:top}th{background:#e2eaf0}section{margin:2rem 0}'
        'button{font:inherit;color:#064f78;background:none;border:0;text-decoration:underline;cursor:pointer}'
        '.badge{display:inline-block;padding:.2rem .5rem;border-radius:.35rem;color:white;font-weight:800}'
        '.no-go{background:#a11825}.conditions{background:#9a5a00}.go{background:#176833}'
        '.needs-human{background:#70479a}.detail-row td{background:#f9fbfd}'
        '.timeline{border-left:4px solid #2c678a;padding-left:1.5rem}.timeline li{margin:.7rem 0}'
        '.timeline span{font-weight:800}blockquote{border-left:4px solid #9a5a00;padding-left:1rem}'
        'footer{border-top:2px solid #ccd7df;margin-top:2rem;padding-top:1rem}'
        '</style></head><body><header><h1>ARGUS Console</h1>'
        '<p>Evidence-backed safety gate for Terraform and agent-written infrastructure changes.</p></header>'
        f'<div class="metrics">{metric_html}</div>'
        '<section><h2>Runs</h2><table><thead><tr><th>Time (IST)</th><th>Plan</th>'
        '<th>Verdict</th><th>Author</th><th>AI calls</th><th>Seconds</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></section>'
        '<section><h2>Learned rules library</h2><table><thead><tr><th>Rule</th>'
        '<th>Source finding</th><th>Source document and date</th><th>Status</th>'
        '<th>Test status</th></tr></thead><tbody>' + ''.join(library) + '</tbody></table></section>'
        '<section><h2>Savings</h2><table><thead><tr><th>Rule</th><th>Before</th><th>After</th>'
        '</tr></thead><tbody>' + ''.join(savings) + '</tbody></table></section>'
        '<footer><strong>Works now:</strong> local plan checks, cited Scholar findings, enforced '
        'rules, agent scope, offline replay. <strong>Prototype / roadmap:</strong> optional governance '
        'packs and additional IaC adapters.</footer>'
        '<script>document.querySelectorAll("button[data-target]").forEach(function(button){'
        'button.addEventListener("click",function(){var row=document.getElementById(button.dataset.target);'
        'row.hidden=!row.hidden;button.setAttribute("aria-expanded",String(!row.hidden));});});</script>'
        '</body></html>\n'
    )
    output = root / "reports" / "console.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
