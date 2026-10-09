# ARGUS Codex MCP plugin

ARGUS exposes two local stdio tools. `argus_check` reviews a JSON plan and returns a verdict, findings, conditions, and run ID. `argus_explain` explains a saved finding with its available evidence. Calls are recorded as `agent:codex` in `ledger/`; the tools do not update reports or caches.

Add this block to your Codex `config.toml`:

```toml
[mcp_servers.argus]
command = 'C:\Users\ashwanitiwari\ARGUS\.venv\Scripts\python.exe'
args = ['C:\Users\ashwanitiwari\ARGUS\argus_mcp.py']
enabled_tools = ["argus_check", "argus_explain"]
default_tools_approval_mode = "writes"
```

Restart Codex to load the server. The launcher uses its file location to import ARGUS, so Codex can start from any working directory. The MCP process uses stdio; no web server, AWS account, or API key is needed for the default rule-only check. `default_tools_approval_mode = "writes"` automatically allows the two tools while they advertise `readOnlyHint = true`; it does not change the approval policy for other servers or shell commands. If your config already has an `[mcp_servers.argus.env]` table, place these server settings above that table.

To test registration, ask Codex to call `argus_check` with `fixtures/plans/act1_replace_pii_db.json` and `live=false`. Expect `NO-GO` and a run ID. Then ask it to call `argus_explain` for `R001`. Inspect `ledger/runs/<run_id>.json` and `ledger/ledger.jsonl` for the recorded `agent:codex` invocation. For a Terraform workflow, see `examples/agent-demo/AGENTS.md`.

`argus_check` accepts only JSON plans inside this project. A live Scholar check needs `OPENAI_API_KEY` in the server process environment; the key is never included in tool results or ledger records. A Scholar failure is displayed as **HOLD FOR REVIEW** with a one-line explanation; the tool preserves its existing structured verdict field.

The MCP read-only annotation describes the tools' effect on the reviewed infrastructure. Calls still append ARGUS ledger and trace records. `live=true` can contact the OpenAI API.
