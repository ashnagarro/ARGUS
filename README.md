# ARGUS

ARGUS reviews Terraform plan JSON before infrastructure changes are merged. Deterministic rules enforce known risks; Scholar researches uncovered changes against a local document corpus and verifies quotations; Smith can turn a human-approved finding into a tested rule.

## Setup (Windows PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -q
```

Keep credentials in environment variables. `OPENAI_API_KEY` is needed only for `--live` Scholar runs. `CODEX_API_KEY` is needed when Smith compiles a rule. Neither belongs in a project file. Configure the Scholar model and optional Codex executable or home in `argus.toml`.

## Review a plan

```powershell
.\.venv\Scripts\python -m argus check fixtures\plans\act2_major_upgrade.json --offline --disable-rule R007
.\.venv\Scripts\python -m argus check fixtures\plans\act3_major_upgrade_second.json
```

`--offline` replays an exact cached Scholar answer without an API call. `--live` calls the API. Every check prints a run ID, writes `ledger/runs/<run_id>.json`, appends a trace in `ledger/traces/`, and refreshes `reports/latest.md` and `reports/latest.html`. `NEEDS HUMAN` exits with code 2; `NO-GO` exits with code 1.

To compile a verified finding, run `argus compile F1 --run <run_id>` or `argus compile F1 --from <plan>`. Smith asks for human approval before its write attempts, runs tests, checks file scope, and records the result. A compiled rule is enforced on later checks.

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
```

The console writes `reports/console.html` from saved run records, traces, the learned-rule ledger, and the cached act3 baseline. It is one self-contained page with no server or CDN. The generated page shows the run history, evidence, permission timeline, learned rules, and measured before/after values.

## Corpus and packaging

`argus corpus fetch` mechanically extracts public reference text into `corpus/`. Do not hand-edit those files. `scripts/package.ps1` creates `dist/argus-demo.zip` from committed files only, so ignored caches, ledgers, keys, and virtual environments stay out of the package.

See [the implementation plan](docs/PLAN.md) and [the build log](BUILD_LOG.md).
