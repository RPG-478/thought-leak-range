# Public release checklist

Snapshot prepared on 2026-08-21. Changing repository visibility is intentionally a separate action.

## Ready

- [x] Current tracked tree contains no credential-shaped OpenRouter, GitHub, Google, or private-key value
- [x] All reachable Git commits contain no matching credential value or tracked `.env` / key file
- [x] Commit identity uses a GitHub `users.noreply.github.com` address
- [x] Runtime output (`runs/`, thoughts, summaries, local config, virtualenv, build output) is ignored
- [x] API errors redact the active key and omit raw upstream/account metadata
- [x] Native input, commercial games, and anti-cheat integration are explicitly out of scope
- [x] Documentation and replay indexes distinguish formal numbers from visual-only runs
- [x] CI workflow uses read-only repository permission and commit-pinned actions
- [x] CI passes on Ubuntu and Windows with Python 3.12

## Must decide before public

- [x] Add the MIT `LICENSE`
- [x] Land the V3 and V4 pull requests so the default `main` branch contains both
- [x] Move 88 replay GIFs to experiment-specific GitHub Release assets
- [x] Enable GitHub Dependabot vulnerability alerts

## Replay-storage decision

Replay GIFs are migrated to GitHub Release assets. Documentation keeps direct per-episode image links,
while the private Git history is rewritten before publication to remove the old 228 MiB blob archive.

The pre-rewrite repository bundle and SHA-256 GIF manifest remain offline under the workspace artifact
directory; they are not published with the repository.
