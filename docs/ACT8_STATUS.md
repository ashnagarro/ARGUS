# Act 8: provider upgrade check

## What works

- `argus upgrade-check` reads Terraform plan JSON `configuration`, groups managed AWS resources by type, and collects argument names from their expressions. It creates a `provider-upgrade` Change only when a configured argument is explicitly removed or changed in the local AWS provider v5 guide.
- Versions can come from `--from` and `--to` or two `.terraform.lock.hcl` files. This implementation accepts AWS provider 4.x to 5.x.
- Scholar researches only the fetched upgrade guide using the existing read-only tools, permission policy, eight-tool and 90-second budgets, quote verifier, cache, and ledger. A verified, relevant breaking quote blocks with `NO-GO`; incomplete research displays `HOLD FOR REVIEW`. An unsupported quote is `UNVERIFIED` and cannot block by itself.
- The generated fixture plan came from Terraform with AWS provider 4.67.0, fake credentials, and `-refresh=false`. It contains `aws_db_instance.name` and an unaffected `aws_s3_bucket`.
- `argus demo all` appends Act 8 after Acts 1, 2, 3, and 5. Act 8 uses a clearly synthetic offline Scholar replay carrying the exact local vendor quote. Its ledger run appears in `argus console`. The MCP server exposes `argus_upgrade_check` with the same read-only annotations as `argus_check`.

## What does not work yet

- Other providers, other major-version pairs, nested argument paths, and guide changes that do not explicitly say an argument was changed or removed are outside this check. A `GO` means no matching explicit breaking argument was found by this scoped check.
- The ordinary `upgrade-check` command needs a matching offline Scholar cache or `--live`; only the demo seeds its synthetic replay. No new provider-upgrade rule has been compiled by Smith.

## Commands (PowerShell, from the project root)

```powershell
.\.venv\Scripts\python -m argus corpus fetch
.\.venv\Scripts\python -m argus upgrade-check fixtures\upgrades\aws_v4_to_v5\plan.json --provider aws --from 4.67.0 --to 5.0.0 --live
.\.venv\Scripts\python -m argus demo all
.\.venv\Scripts\python -m argus console
```

For the live command, set `OPENAI_API_KEY` in the process environment first. The lock-file alternative is:

```powershell
.\.venv\Scripts\python -m argus upgrade-check fixtures\upgrades\aws_v4_to_v5\plan.json --provider aws --lock-before path\to\before\.terraform.lock.hcl --lock-after path\to\after\.terraform.lock.hcl --live
```
