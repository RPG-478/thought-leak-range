# Replay archive

Replays are evidence, not decoration. Filenames include seed and outcome so individual episodes remain
inspectable without relying on color alone.

| Set | Runs | Purpose |
|---|---:|---|
| [V4 Async flat-4 visual-only](2026-08-21-v4-async-clock-flat-4-visual-only/README.md) | 10 | Observe the unpaused body; excluded from formal timing averages |
| [V4-S VAGO flat-4](2026-08-21-v4-s-vago-flat-4/README.md) | 10 | Stopped-world flat four-tic diagnostic |
| [V4-S VAGO scaled frame-skip 4](2026-08-21-v4-s-vago-frame-skip-4/README.md) | 10 | Failure where LONG becomes 20 tics |
| [V4 async side lease and V4-S control](2026-08-21-v4-side-lease/README.md) | 36 | Paired stale-direction experiment |
| [Marine recognition repair baseline](2026-08-21-v4-s-marine-fixed-before-overshoot/README.md) | 18 | Enemy-label correction before overshoot changes |

The 88 GIFs live in experiment-specific GitHub Releases instead of normal Git history. Each experiment
README embeds the corresponding release assets directly, so failed episodes remain individually
inspectable without turning every clone into a 228 MiB replay download.
