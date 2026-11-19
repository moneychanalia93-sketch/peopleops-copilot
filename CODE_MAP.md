# Code map

One line per file. Run everything from the `peopleops-copilot` folder.

## Top level
| File | What it is |
|---|---|
| `README.md` | What this is, quickstart, architecture, guardrails, honest evaluation and limitations. |
| `run_demo.ps1` | One-command demo for Windows PowerShell; finds Python and calls `python -m peopleops demo`. |
| `content/handbook/*.md` | The ten fictional policy documents the agent searches (one is managers-only). |
| `evals/golden_set.json` | The 98 test questions with expected route, source and sensitive category. |
| `docs/eval_report.json` | A saved copy of the latest evaluation report. |
| `var/` | Created at run time: database, Slack outbox file, eval report. Not committed. |

## `peopleops/` (the application)
| File | What it does |
|---|---|
| `__main__.py` | Command-line entry point: demo, serve, seed, eval, chat, approvals, audit, sample-hire. |
| `demo.py` | The scripted one-minute story used by `demo`. |
| `config.py` | Settings from environment variables; the server host is fixed to 127.0.0.1. |
| `db.py` | The SQLite schema (all tables, audit-log triggers) and the connection helper. |
| `seed.py` | Builds the fictional 60-person company, applications, ARR history and past onboarding plans. |
| `webhook.py` | Ashby webhook logic: signature check, dedupe, data minimisation, hire to onboarding plan. |
| `onboarding.py` | The task template (by team, location, role) and plan progress queries. |
| `adapters/__init__.py` | Chooses mock or real adapter per system from environment variables. |
| `adapters/ats.py` | Ashby interface, mock and real stub. |
| `adapters/hris.py` | BambooHR interface, mock and real stub. |
| `adapters/chat.py` | Slack interface: outbox-file mock and real incoming-webhook class. |
| `adapters/itsm.py` | IT ticket (Jira Service Management) and Okta interfaces, mocks and real stubs. |
| `adapters/http.py` | Tiny JSON-over-HTTP helper used by the real adapters. |
| `safety.py` | Sensitive-topic classifier, prompt-injection and PII-fishing detectors (plain pattern lists). |
| `retrieval.py` | BM25 keyword search over the handbook, with section citations and a confidence floor. |
| `llm.py` | Model interface: offline mock model, Anthropic and OpenAI classes. |
| `tools.py` | The six agent tools, argument checks, the low-risk allowlist, and approval decisions. |
| `agent.py` | The tool-calling loop: safety gates, then tools, then the output citation check. |
| `approvals.py` | Storage for the approval queue and escalation inbox. |
| `permissions.py` | Who may see whose data (employee, manager, People team). |
| `security.py` | Webhook signing, PII redaction and small-group (k-anonymity) hiding. |
| `audit.py` | Append-only audit log with a hash chain and a verifier. |
| `analytics.py` | Dashboard numbers: headcount, funnel, time to hire, onboarding, ARR per employee, time saved. |
| `context.py` | Small bundle of database, acting user and adapters passed to every tool. |
| `server.py` | Local HTTP server: dashboard page, JSON API, webhook endpoint. |
| `web/index.html` | The whole dashboard: HTML, CSS, JavaScript and SVG charts in one file. |
| `evaluate.py` | The evaluation harness and its pass/fail gate. |

## `tests/` (unittest, 75 tests)
| File | Covers |
|---|---|
| `helpers.py` | Fresh seeded database per test; runtime files go to a temp folder. |
| `test_security.py` | Signature check, redaction, k-anonymity. |
| `test_webhook.py` | Hire creates plan, bad signature, idempotency, salary never stored. |
| `test_permissions.py` | Role scoping, manager-only handbook, k-anonymity in analytics, no tool reads pay. |
| `test_safety.py` | Every sensitive category routes to a human; injection and PII detection. |
| `test_agent.py` | Cited answers, escalation summary, audit privacy, injection, citation check. |
| `test_approvals.py` | Queue, approve, reject, separation of duties, Slack outbox, bad arguments. |
| `test_audit.py` | Append-only triggers, hash chain, tamper detection. |
| `test_eval_gate.py` | Golden set coverage, the 100% recall gate, non-zero exit on failure. |
| `test_server.py` | Real HTTP: pages, role limits, host check, webhook, approvals. |
