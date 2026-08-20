# Security policy

## Scope

Thought Leak Range is an offline ViZDoom research prototype. It sends prompts to OpenRouter only in
the explicit `live` mode. It does not generate native keyboard or mouse input and is not intended for
commercial games, anti-cheat environments, or untrusted remote control.

Only the latest code on the default branch is supported for security fixes.

## Reporting

Please do not publish credentials, private logs, or an exploitable report in a public issue. Use the
repository's **Security → Report a vulnerability** flow to open a private GitHub Security Advisory.

Include the affected revision, reproduction conditions, impact, and the smallest useful proof. Never
include a real OpenRouter key; use a redacted or test-only value.

## Secrets and generated data

- Supply `OPENROUTER_API_KEY` through the process environment or an ignored `.env` file.
- `runs/`, raw thought logs, summaries, and local ViZDoom configuration are intentionally ignored.
- Before sharing a replay or result, inspect it for account metadata and private prompt content.
