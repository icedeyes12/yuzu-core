# \[PROJECT: HKKM - Yuzu Companion\]

---

## What Even Is This?

Honestly, what are you looking for here? This is just another AI project.

You know what's more interesting? Mending scroll [**Fesnuk**](https://www.facebook.com/groups/programmerhandal/). Or maybe some cat videos on YouTube.

Seriously, go scroll some social media. This code isn't going to entertain you like that latest meme trend.

---

## No Really, What Does It Do?

It's an AI companion. It talks. It remembers things. Sometimes it generates images.

But let's be real - you're probably just here because you're bored. Might as well go watch some TikTok.

---

## Installation

If you insist on actually installing this, go read [INSTALL.md](INSTALL.md) for instructions.

But honestly, just ask ChatGPT. It will explain it better.

## Remote frontend validation

Termux runs the local gates first, then syncs the current working tree to Zo
Computer over the configured SSH alias `2`. No Git operation or automatic
commit is involved; the local workspace remains authoritative.

```bash
yuzu-validate
# or
python -m scripts.remote_validation
```

Pipeline is fail-fast.

Termux:

1. `ruff format --check .`
2. `ruff check .`
3. Local `python -m compileall .`
4. Remote `git status --porcelain` preflight
5. Stop if the remote working tree is dirty
6. Detect the local Git branch
7. SSH to Zo Computer
8. Remote `git fetch --all --prune`
9. Remote `git checkout -B <branch> origin/<branch>`
10. `rsync` over SSH to `/home/workspace/yuzu-companion`
11. Remote conditional `bun install --frozen-lockfile`
12. Remote `node --check` for every `static/**/*.js`
13. Remote `bunx biome check static/`
14. Remote `pytest`

Native Linux:

1. `ruff format --check .`
2. `ruff check .`
3. Local `python -m compileall .`
4. Conditional local `bun install --frozen-lockfile`
5. Local `node --check` for every `static/**/*.js`
6. Local `bunx biome check static/`
7. Local `pytest`

Before sync, the remote working tree is checked because Zo may contain active
Hermes or builtin-agent work. A dirty remote checkout stops the pipeline before
fetch, checkout, rsync, or validators. No reset, stash, stash pop, or global
Git config mutation is performed. The branch preparation uses `fetch` plus
checkout, never `git pull`; rsync then makes the local working tree
authoritative. Excluded from sync: `.git/`,
`.venv/`, `__pycache__/`, `.ruff_cache/`, `node_modules/`, `.pytest_cache/`.
When `rsync` is unavailable, the command falls back to a streamed `tar`
archive over SSH. Every command's stdout and stderr is returned.

Example output:

```text
All checks passed!
3 passed in 0.19s
sent 42.1K bytes  received 1.2K bytes
Checked 87 files in 0.31s
```

---

## For the 3 People Actually Reading This

If you're still here, congratulations on your attention span. This is an intimate AI companion system with:

- Emotional bonding protocols
- Multimodal interaction (text + images)
- Session-based memory
- Encrypted conversations
- Web and terminal interfaces

But honestly, you could have just asked ChatGPT to explain it.

---

## Disclaimer

All code is AI-generated. The developer just pressed some buttons and prayed.

Now go away and do something more productive. Like scrolling through memes.

---

## Author

### Project Lead

- [Bani Baskara](https://github.com/icedeyes12/)

### Team

- [Aihara](https://github.com/icedeyes12/yuzu-companion)
- [Claude](https://www.anthropic.com/)
- [DeepSeek](https://www.deepseek.com/)
- [Gemini](https://gemini.google.com/)
- [GitHub Copilot](https://github.com/copilot)
- [GPT](https://chatgpt.com/)
- [Hermes](https://hermes-agent.nousresearch.com/)
- [KiloCode](https://kilocode.ai/)
- [Moonshot ai](https://www.moonshot.cn/)
- [Qwen](https://github.com/QwenLM/Qwen3-Coder)

---

©2025-2026 \[HKKM project\](https://guthib.com/icedeyes12/) | Built with love 💕