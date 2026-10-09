# ARGUS build log

All work was done in phase order with mocked API tests, Git commits, and a backup bundle after each phase. The corpus was fetched mechanically; it was not rewritten by AI.

| Phase | Delivered | Verification |
| --- | --- | --- |
| 1–4 | CLI, normalized Terraform changes, deterministic risk rules, verdict reports | Local pytest and fixture checks |
| 5 | Public AWS/Terraform corpus and exact quote verification | Offline fixture tests |
| 6 | Scholar Responses loop, permission checks, cached replay, fail-closed review | Mocked client tests; live act2 finding verified by the user |
| 7 | Smith compile loop and learned R007 rule | Full suite; user confirmed act3 caught with zero AI calls |
| 8 | Agent scope, permission decisions, dated exceptions, durable runs | Full suite and isolated project tests |
| 9 | Repeatable four-scenario offline demo | Three runs with identical verdicts |
| 9B | Rule advice and provenance, advisory notice, projector report, early Scholar stop | Full suite and offline act2/act3 reports |
| 9C | Presentation page, documentation, tracked-file package | Full suite and package inspection |
| 9D | Offline ARGUS Console with saved runs, evidence, permission timeline, learned rules, and savings | Full suite; secret-redaction and local HTML tests |
| 10 | Policy from English behind an enabled flag | Full suite and four-act demo gate |
| 16 | Optional governance rule pack behind an enabled flag | Full suite and synthetic governance sweep |
| 19 | Team overlays, Git packaging, adoption guide | Full suite and team portability tests |
| 20 | Codex MCP server, local tool registration guide, synthetic Terraform agent demo | Mocked transport and full suite |
| 21 | Loopback-only ARGUS Web upload page with redacted saved plans | 261 full-suite tests and local HTTP upload test |
| Extra credit 1 | Sensitive Terraform values redacted before rule and Scholar processing | 257 full-suite tests; fake fixture password absent from outputs |
| Extra credit 2 | Act 7 attempt reverted after two failing full-suite gates | Existing baseline test expected an unsafe created volume to be ignored; see `docs/OVERNIGHT_LOG.md` |
| Extra credit 4 | Title, detail, then audit reference on every finding surface | 262 full-suite tests and four-act demo gate |
| Extra credit 5 | Final feature-state table, submission ZIP checks, and report wording polish | 271 full-suite tests, four-act demo gate, ZIP secret/exclusion scan |

The saved act3 before baseline used 13 AI calls and 42.51 seconds with R007 disabled. Once R007 was enabled, act3 was blocked by a deterministic rule with zero AI calls. This comparison uses the cached baseline and does not claim a general performance estimate.

ARGUS does not apply Terraform. A NO-GO report blocks the proposed change; a human decides how to fix it and whether to approve Smith's write step.

The current `argus.toml` enables policy from English, governance rules, and team overlays. CAB brief, rollback, compliance mapping, cost delta, learning report, control coverage, and CloudFormation remain disabled prototypes. `scripts/package_submission.ps1` builds a committed-file ZIP and checks exclusions and credential patterns before release.
