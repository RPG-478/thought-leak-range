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

- [ ] Choose and add a `LICENSE`. No open-source permission is granted without one
- [ ] Land the stacked draft PRs so the default `main` branch contains V3 and V4
- [ ] Decide replay storage: 88 tracked GIFs use about 228 MiB in the current tree
- [ ] Enable GitHub dependency/security alerts; Dependabot alerts are currently disabled

## Replay-storage choices

1. **Keep Git history as-is.** Simplest and preserves every episode inline, but clones are heavy.
2. **Move GIFs to GitHub Release assets.** Keeps the code repository light, but requires rewriting links
   and deciding whether to rewrite existing private history before publication.
3. **Use Git LFS.** Keeps normal Git objects smaller going forward, but public contributors need LFS and
   existing history remains large unless rewritten.

History rewriting and public visibility both affect every future clone, so neither is performed by the
cleanup commit.
