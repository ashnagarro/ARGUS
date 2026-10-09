# ARGUS Codex MCP plugin

ARGUS exposes two local stdio tools. `argus_check` reviews a JSON plan and returns a verdict, findings, conditions, and run ID. `argus_explain` explains a saved finding with its available evidence. Calls are recorded as `agent:codex` in `ledger/`; the tools do not update reports or caches.

Add this block to your Codex `config.toml`:

```toml
[mcp_servers.argus]
command = 'C:\Users\ashwanitiwari\ARGUS\.venv\Scripts\python.exe'
args = ["-m", "argus.mcp_server"]
```

Start Codex in `C:\Users\ashwanitiwari\ARGUS` so Python can import the project package, then restart Codex to load the server. The MCP process uses stdio; no web server, AWS account, or API key is needed for the default rule-only check.

To test registration, ask Codex to call `argus_check` with `fixtures/plans/act1_replace_pii_db.json` and `live=false`. Expect `NO-GO` and a run ID. Then ask it to call `argus_explain` for `R001`. Inspect `ledger/runs/<run_id>.json` and `ledger/ledger.jsonl` for the recorded `agent:codex` invocation. For a Terraform workflow, see `examples/agent-demo/AGENTS.md`.

`argus_check` accepts only JSON plans inside this project. A live Scholar check needs `OPENAI_API_KEY` in the server process environment; the key is never included in tool results or ledger records. A Scholar failure returns `NEEDS HUMAN`.
