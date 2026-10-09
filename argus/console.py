"""Offline, self-contained HTML console built from saved ARGUS run records."""

from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import quote, urlsplit

from .corpus import load_corpus
from .report import _local_time
from .rules import load_rules
from .verdict import verdict_explanation, verdict_label
from .warden import W001_NAME, W001_TITLE


_KEY_PATTERN = re.compile(r"(?i)sk-[A-Za-z0-9_-]*")
_SECRET_NAME = re.compile(r"(?i)(?:key|token|secret|password|credential)")
_RUN_ID = re.compile(r"[A-Za-z0-9_-]+")
_OPTIONAL_FEATURES = (
    ("policy_compiler", "policy from English"),
    ("cab_brief", "CAB brief"),
    ("rollback", "rollback notes"),
    ("compliance", "compliance mapping"),
    ("cost", "cost delta"),
    ("learning_report", "learning report"),
    ("governance_pack", "governance rule pack"),
    ("control_coverage", "control coverage"),
    ("cloudformation_adapter", "CloudFormation adapter"),
    ("team_overlays", "team overlays"),
)


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


def _findings(record: dict, rule_catalog: dict[str, object]) -> str:
    items: list[str] = []
    for finding in record.get("rule_findings", []):
        status = "WAIVED" if finding.get("waived") else "ENFORCED"
        rule_id = str(finding.get("rule_id") or "")
        rule = rule_catalog.get(rule_id)
        legacy_title = W001_TITLE if rule_id == "W001" else getattr(rule, "title", "")
        legacy_name = W001_NAME if rule_id == "W001" else getattr(rule, "name", "")
        # Preserve metadata recorded at run time; installed rules fill legacy records.
        title = str((finding.get("title") if finding.get("name") else "") or
                    legacy_title or finding.get("title") or "Rule finding")
        name = str(finding.get("name") or legacy_name or
                   re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "rule")
        resource = str(finding.get("resource") or "")
        tool = str(finding.get("source_tool") or
                   ("agent" if rule_id == "W001" else "terraform" if resource.startswith("aws_") else ""))
        cloud = str(finding.get("cloud") or
                    ("n/a" if rule_id == "W001" else "aws" if resource.startswith("aws_") else ""))
        trigger = str(finding.get("message") or "")
        headline = str(finding.get("headline") or "")
        if headline and headline != title and headline != trigger:
            trigger = f"{headline} — {trigger}" if trigger else headline
        detail = [f"Resource: {resource}"]
        if tool:
            detail.append(f"Tool: {tool}")
        if cloud:
            detail.append(f"Cloud: {cloud}")
        detail.append(f"Trigger: {trigger}")
        rule_reference = f"({rule_id} · {name})"
        details = [
            f'<strong class="finding-title">{_safe(title)}</strong>',
            '<p class="finding-detail">' + ' · '.join(_safe(part) for part in detail) + '</p>',
            f'<small class="rule-ref">{_safe(rule_reference)}</small> [{status}]',
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
            f'<strong class="finding-title">{_safe(finding.get("claim"))}</strong>',
            f'<p class="finding-detail">Resource: {_safe(finding.get("resource"))}</p>',
            f'<small class="rule-ref">({_safe(finding.get("id"))})</small> [AI {status}]',
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
    path = record.get("_trace_dir", root / "ledger" / "traces") / f"{run_id}.jsonl"
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


def _replay_calls(record: dict, targets: dict[str, str], archives: list[Path]) -> str:
    """Show cached work with the measured live source and a local source link."""
    source_id = str(record.get("replayed_from_run_id") or "")
    if not _RUN_ID.fullmatch(source_id):
        return _safe(record.get("ai_calls", 0))
    calls = record.get("original_ai_calls")
    seconds = record.get("original_elapsed_seconds")
    if calls is None or seconds is None:
        label = "metrics unavailable"
    else:
        label = f"{int(calls)} AI calls, {float(seconds):.2f} s"
    href = targets.get(source_id)
    if href:
        href = f"#{href}"
    else:
        for archive in archives:
            if (archive / "runs" / f"{source_id}.json").is_file():
                href = f"../ledger/archive/{quote(archive.name, safe='')}/runs/{quote(source_id, safe='')}.json"
                break
    source = f'<a href="{_safe(href)}">{_safe(label)}</a>' if href else _safe(label)
    return f"replayed (offline) - original live run: {source}"


def _archives(root: Path) -> list[Path]:
    folder = root / "ledger" / "archive"
    if not folder.is_dir():
        return []
    return sorted((path for path in folder.iterdir() if path.is_dir() and not path.is_symlink()),
                  key=lambda path: path.name, reverse=True)


def _runs(root: Path, *, include_archives: bool = False) -> list[dict]:
    folders = [root / "ledger" / "runs"]
    if include_archives:
        folders.extend(path / "runs" for path in _archives(root))
    records: list[dict] = []
    for folder in folders:
        if folder.is_dir():
            for path in folder.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["_trace_dir"] = folder.parent / "traces"
                records.append(record)
    return sorted(records, key=lambda item: str(item.get("run_at", "")), reverse=True)


def _learned(root: Path, rule_catalog: dict[str, object]) -> list[dict]:
    compiled: dict[str, dict] = {}
    paths = [archive / "ledger.jsonl" for archive in reversed(_archives(root))]
    paths.append(root / "ledger" / "ledger.jsonl")
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (entry.get("type") in {"compile", "policy_compile"}
                    and entry.get("status") == "compiled" and entry.get("rule_id")):
                compiled[entry["rule_id"]] = entry
    documents = load_corpus(root / "corpus") if (root / "corpus").is_dir() else {}
    results = []
    for rule_id, entry in sorted(compiled.items()):
        rule = rule_catalog.get(rule_id)
        sources = []
        for doc_id in getattr(rule, "source_doc_ids", ()):
            doc = documents.get(doc_id)
            sources.append({"doc_id": doc_id,
                            "date": doc.retrieved_at if doc else "unknown",
                            "url": doc.url if doc else ""})
        results.append({
            "rule_id": rule_id,
            "title": getattr(rule, "title", "") or entry.get("title") or "Rule details unavailable",
            "name": getattr(rule, "name", "") or entry.get("name") or rule_id.lower(),
            "source_finding": ("human policy" if entry.get("type") == "policy_compile"
                               else getattr(rule, "source_finding_id", "")
                               or (entry.get("finding_ids") or [""])[0]),
            "sources": sources,
            "policy": entry.get("type") == "policy_compile",
            "enforced": rule is not None,
            "test_status": "passed at compile" if (rule is not None and
                (root / "tests" / "rules" / f"test_{rule_id.lower()}.py").is_file()) else "not confirmed",
        })
    return results


def write_console(root: Path, *, include_archives: bool = False) -> Path:
    """Render saved runs; never connect to a service or read credentials."""
    root = Path(root)
    rule_catalog = {rule.id: rule for rule in load_rules(include_governance=True)}
    runs = _runs(root, include_archives=include_archives)
    learned = _learned(root, rule_catalog)
    archives = _archives(root)
    settings_path = root / "argus.toml"
    settings = tomllib.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    flags = settings.get("flags", {})
    baseline_path = root / ".cache" / "act3_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else {}
    avoided = int(baseline.get("ai_calls", 0)) if any(item["rule_id"] == "R007" for item in learned) else 0

    totals = [
        ("Runs", len(runs)), ("NO-GO", sum(item.get("verdict") == "NO-GO" for item in runs)),
        (verdict_label("GO-WITH-CONDITIONS"), sum(item.get("verdict") == "GO-WITH-CONDITIONS" for item in runs)),
        ("GO", sum(item.get("verdict") == "GO" for item in runs)),
        ("Learned rules", len(learned)), ("AI calls avoided", avoided),
    ]
    metric_html = ''.join(f'<div class="metric"><strong>{_safe(value)}</strong><span>{_safe(label)}</span></div>'
                          for label, value in totals)

    targets = {
        str(record["run_id"]): f"run-{index}"
        for index, record in enumerate(runs)
        if _RUN_ID.fullmatch(str(record.get("run_id", "")))
    }
    rows = []
    for index, record in enumerate(runs):
        verdict = str(record.get("verdict", "NEEDS HUMAN"))
        badge = {"NO-GO": "no-go", "GO-WITH-CONDITIONS": "conditions",
                 "GO": "go"}.get(verdict, "needs-human")
        target = f"detail-{index}"
        plan = Path(str(record.get("plan", ""))).name
        upgrade = record.get("upgrade")
        if isinstance(upgrade, dict):
            plan = (f"Act 8 · {upgrade.get('provider', '')} "
                    f"{upgrade.get('from_version', '')} → {upgrade.get('to_version', '')} · {plan}")
        replay_calls = _replay_calls(record, targets, archives)
        rows.append(
            f'<tr id="run-{index}"><td>{_safe(_local_time(str(record.get("run_at", ""))))}</td>'
            f'<td><button type="button" data-target="{target}" aria-expanded="false">{_safe(plan)}</button></td>'
            f'<td><span class="badge {badge}">{_safe(verdict_label(verdict))}</span>'
            + (f'<p class="verdict-note">{_safe(verdict_explanation(verdict))}</p>'
               if verdict_explanation(verdict) else '') + '</td>'
            f'<td>{_safe(record.get("author", "human"))}</td>'
            f'<td>{replay_calls}</td>'
            f'<td>{float(record.get("elapsed_seconds", 0)):.2f}</td></tr>'
            f'<tr id="{target}" class="detail-row" hidden><td colspan="6">'
            '<h3>Findings</h3>' + _findings(record, rule_catalog)
            + ('<h3>Required fixes before merge</h3>' if record.get("verdict") == "NO-GO"
               else '<h3>Conditions</h3>') + _conditions(record)
            + '<h3>Agentic-loop timeline</h3>' + _timeline(root, record)
            + '</td></tr>'
        )

    library = []
    savings = []
    for item in learned:
        sources = ', '.join(
            f'{_source_link(doc["url"], doc["doc_id"])} (retrieved {_safe(doc["date"])})'
            for doc in item["sources"]
        ) or ("Human-supplied policy (no corpus citation)" if item["policy"]
              else "No source document recorded")
        rule_reference = f'({item["rule_id"]} · {item["name"]})'
        rule_cell = (f'<strong>{_safe(item["title"])}</strong><br>'
                     f'<small class="rule-ref">{_safe(rule_reference)}</small>')
        library.append(
            f'<tr><td>{rule_cell}</td><td>{_safe(item["source_finding"])}</td>'
            f'<td>{sources}</td><td>{"ENFORCED" if item["enforced"] else "not installed"}</td>'
            f'<td>{_safe(item["test_status"])}</td></tr>'
        )
        if item["rule_id"] == "R007" and baseline:
            savings.append(
                f'<tr><td>{rule_cell}</td>'
                f'<td>{_safe(baseline.get("ai_calls", 0))} calls / '
                f'{float(baseline.get("elapsed_seconds", 0)):.2f} s</td>'
                '<td>0 calls / 0.00 s</td></tr>'
            )
        else:
            savings.append(f'<tr><td>{rule_cell}</td>'
                           '<td>Not measured</td><td>Not measured</td></tr>')

    works_now = ["local plan checks", "cited Scholar findings", "enforced rules",
                 "agent scope", "offline replay"]
    works_now.extend(label for flag, label in _OPTIONAL_FEATURES if flags.get(flag) is True)
    prototypes = [label for flag, label in _OPTIONAL_FEATURES if flags.get(flag) is not True]
    archive_items = [f"{_safe(path.name)} ({len(list((path / 'runs').glob('*.json')))} runs)"
                     for path in archives]
    footer = (
        '<footer><strong>Works now:</strong>' + _items([_safe(item) for item in works_now])
        + '<strong>Prototype / roadmap:</strong>' + _items([_safe(item) for item in prototypes])
        + '<strong>Archives:</strong>' + _items(archive_items) + '</footer>'
    )

    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>ARGUS Console</title><style>'
        'body{font:16px/1.55 system-ui,sans-serif;color:#17212b;background:#f3f6f8;'
        'margin:0 auto;max-width:1500px;padding:1.5rem}h1{font-size:3rem;margin:.2rem 0}'
        'h2{font-size:2rem}h3{font-size:1.4rem}.metrics{display:grid;'
        'grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:.7rem;margin:1.5rem 0}'
        '.metric{background:white;border:1px solid #ccd7df;border-radius:.6rem;padding:.8rem}'
        '.metric strong{display:block;font-size:2rem}.metric span{font-size:.9rem}'
        'table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #ccd7df;'
        'padding:.7rem;text-align:left;vertical-align:top}th{background:#e2eaf0}section{margin:2rem 0}'
        'button{font:inherit;color:#064f78;background:none;border:0;text-decoration:underline;cursor:pointer}'
        '.badge{display:block;padding:.7rem 1rem;border-radius:.6rem;color:white;font-size:1.2rem;font-weight:800}'
        '.no-go{background:#a11825}.conditions{background:#9a5a00}.go{background:#176833}'
        '.needs-human{background:#70479a}.detail-row td{background:#f9fbfd}.verdict-note{font-size:.85rem;color:#526677}'
        '.timeline{border-left:4px solid #2c678a;padding-left:1.5rem}.timeline li{margin:.7rem 0}'
        '.timeline span{font-weight:800}blockquote{border-left:4px solid #9a5a00;padding-left:1rem}'
        '.finding-detail{margin:.25rem 0;color:#34485e}.rule-ref{font-size:.75em;color:#526677}'
        'footer{border-top:2px solid #ccd7df;margin-top:2rem;padding-top:1rem}'
        '</style></head><body><header><h1>ARGUS</h1>'
        '<p>Evidence-backed safety gate for infrastructure changes</p></header>'
        f'<div class="metrics">{metric_html}</div>'
        f'<section><h2>Runs — {"all sessions" if include_archives else "latest session"}</h2>'
        '<table><thead><tr><th>Time (IST)</th><th>Plan</th>'
        '<th>Verdict</th><th>Author</th><th>AI calls</th><th>Seconds</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></section>'
        '<section><h2>Learned rules library</h2><table><thead><tr><th>Rule</th>'
        '<th>Source finding</th><th>Source document and date</th><th>Status</th>'
        '<th>Test status</th></tr></thead><tbody>' + ''.join(library) + '</tbody></table></section>'
        '<section><h2>Savings</h2><table><thead><tr><th>Rule</th><th>Before</th><th>After</th>'
        '</tr></thead><tbody>' + ''.join(savings) + '</tbody></table></section>'
        + footer +
        '<script>document.querySelectorAll("button[data-target]").forEach(function(button){'
        'button.addEventListener("click",function(){var row=document.getElementById(button.dataset.target);'
        'row.hidden=!row.hidden;button.setAttribute("aria-expanded",String(!row.hidden));});});</script>'
        '</body></html>\n'
    )
    output = root / "reports" / "console.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
