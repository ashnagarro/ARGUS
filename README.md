# ARGUS

ARGUS reviews Terraform plan JSON before infrastructure changes are merged. Deterministic rules enforce known risks; Scholar researches uncovered changes against a local document corpus and verifies quotations; Smith can turn a human-approved finding into a tested rule.

## Setup (Windows PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -q
```

Keep credentials in environment variables. `OPENAI_API_KEY` is needed only for `--live` Scholar runs. `CODEX_API_KEY` is needed when Smith compiles a rule. Neither belongs in a project file. Configure the Scholar model and optional Codex executable or home in `argus.toml`.

## Works now vs Prototype

| Feature | State | Configuration |
| --- | --- | --- |
| Terraform plan checks, secret redaction, four-act demo, ledger archive, offline console, MCP tools, local web upload | Works now | Core commands; `python -m argus serve --port 8765` binds to 127.0.0.1 |
| Policy from English, governance rule pack, team overlays | Works now | `policy_compiler`, `governance_pack`, `team_overlays` are enabled in `argus.toml` |
| CAB brief, rollback notes, compliance mapping, cost delta, learning report, control coverage, CloudFormation adapter | Prototype / roadmap | Their flags are disabled in `argus.toml` |
| Act 7 real-plan comparison | Prototype / roadmap | The supplied fixed fixture has the same risky resource settings; the attempted Act 7 task was reverted after two failed test gates |

The web page accepts Terraform plan JSON up to 5 MB, stores a redacted copy in ignored `ledger/uploads/`, and enables live AI research only when `OPENAI_API_KEY` is set. Its six sample buttons include both Act 7 fixtures; the fixed button is labeled with the current fixture limitation.

## Review a plan

```powershell
.\.venv\Scripts\python -m argus check fixtures\plans\act2_major_upgrade.json --offline --disable-rule R007
.\.venv\Scripts\python -m argus check fixtures\plans\act3_major_upgrade_second.json
```

`--offline` replays an exact cached Scholar answer without an API call. `--live` calls the API. Every check prints a run ID, writes `ledger/runs/<run_id>.json`, appends a trace in `ledger/traces/`, and refreshes `reports/latest.md` and `reports/latest.html`. `NEEDS HUMAN` exits with code 2; `NO-GO` exits with code 1.

To compile a verified finding, run `argus compile F1 --run <run_id>` or `argus compile F1 --from <plan>`. Smith asks for human approval before its write attempts, runs tests, checks file scope, and records the result. A compiled rule is enforced on later checks.

## Policy from English

With `[flags] policy_compiler = true` in `argus.toml`, Smith can compile a human-supplied sentence into a deterministic rule and a positive and negative test:

```powershell
.\.venv\Scripts\python -m argus policy "A change must not remove the owner tag from a resource."
```

This uses the existing `CODEX_API_KEY` and `[smith]` settings. Smith asks for approval before writing, makes at most three attempts, runs the generated tests, and keeps changes within `argus/rules/` and `tests/rules/`. A failed compile rolls back those files and reports `needs human`. The rule records the exact policy sentence and approval date. This command expresses your policy; it does not claim a supporting corpus citation. Review the proposed sentence carefully before approving because its rule will be enforced on later checks.

## Demo

```powershell
.\.venv\Scripts\python -m argus demo all
.\.venv\Scripts\python -m argus demo --present
```

The offline demo covers stateful replacement, sourced AI advice, an enforced learned rule, and an out-of-scope agent change. `--present` writes a self-contained projector page at `reports/presentation.html`. To record a new act3 before baseline in a PowerShell session with `OPENAI_API_KEY` set, run `argus check fixtures\plans\act3_major_upgrade_second.json --live --disable-rule R007` through the virtual-environment Python executable.

## Offline console

```powershell
.\.venv\Scripts\python -m argus console
.\.venv\Scripts\python -m argus console --open
.\.venv\Scripts\python -m argus console --all
```

The console writes `reports/console.html` from saved run records, traces, the learned-rule ledger, and the cached act3 baseline. It is one self-contained page with no server or CDN. By default it shows the latest session: runs since the last archive. `--session latest` selects that view explicitly; `--all` includes archived runs and their traces. The page shows evidence, permission timelines, learned rules, and measured before/after values. Offline replays display the original live run's AI calls and elapsed time, with a link to that run when its record is available.

Run `.\.venv\Scripts\python -m argus ledger archive` before a new demo session. It moves the current `ledger.jsonl`, `runs/`, and `traces/` into `ledger/archive/<timestamp>/` without deleting them. The console footer lists archived sessions and shows optional features under “Works now” or “Prototype / roadmap” according to `argus.toml` flags.

## Governance rule pack

The `governance_pack` flag enables G01–G26 and G28–G29 for normal checks. Each rule has a positive and negative synthetic test. `controls.yaml` maps rule IDs to ARGUS internal control labels; it does not assert a legal or certification mapping. Organization-specific `required_tags`, `approved_regions`, `allowed_instance_classes`, and `minimum_retention_days` can be set under `[governance]` in `argus.toml`. An empty list or omitted retention minimum leaves that particular policy unset.

Use `--ticket` for a production change, `--approver` to record a distinct human reviewer, and repeat `--tf-file` for Terraform files that need a literal-secret scan. The canonical four-act `argus demo all` stays on its baseline rules; `argus check fixtures\plans\act6_governance_sweep.json --ticket SYNTH-1` exercises the governance pack with synthetic violations.

## Team portability

The Git package exposes an `argus` command. In a team infrastructure repository, run `argus init`, set `[flags] team_overlays = true` in `argus.toml`, then edit `.argus/team.toml`. ARGUS always evaluates the baseline pack and layers approved regions, required tags, owners, enabled packs, and extra rules on top. Team settings cannot disable or lower an organization-mandated rule; an attempted relaxation produces a critical configuration finding. `argus promote RULE_ID` copies a reviewed team rule and its test into the AWS core pack and prints the review checklist.

[The five-minute adoption guide](docs/ADOPTION.md) includes Git installation and CI templates. The synthetic [analytics](examples/team-analytics/README.md) and [payments](examples/team-payments/README.md) teams review the same plan with different results.

## Codex MCP plugin

Register the local MCP server using [docs/CODEX_PLUGIN.md](docs/CODEX_PLUGIN.md). Its two tools check project-local plan JSON and explain saved findings. MCP calls write only ledger records. The synthetic Terraform workflow is in [examples/agent-demo](examples/agent-demo/AGENTS.md).

## Corpus and packaging

`argus corpus fetch` mechanically extracts public reference text into `corpus/`. Do not hand-edit those files. `scripts/package_submission.ps1` creates `dist/argus-demo.zip` from committed files and verifies that the ZIP excludes caches, Terraform work directories, keys, uploads, and virtual environments. Its secret scan permits the clearly marked fake credential in the risky test fixture.

See [the implementation plan](docs/PLAN.md), [the build log](docs/BUILD_LOG.md), and [the overnight task log](docs/OVERNIGHT_LOG.md).
