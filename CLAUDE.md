# CLAUDE.md — AI Assistant Guide for myclaudedevops

This file provides instructions and context for AI assistants (such as Claude Code) working in this repository.

---

## Project Overview

- **Repository**: myclaudedevops
- **Status**: Contains `tatkal-agent/`, a Python 3.11+ agentic Tatkal booking assistant
- **Stack**: Python, Anthropic SDK (Claude agent loop), MCP Python SDK v2 (`MCPServer`, elicitation for human-in-the-loop), pydantic
- **Architecture**: Claude plans → MCP tools → human approves via elicitation → deterministic executor (no LLM in the hot path) → `BookingProvider` (mock simulator, or an authorised partner API skeleton)
- **Boundary**: never add scraping/UI automation of IRCTC, CAPTCHA solving or multi-account logic (see `tatkal-agent/docs/COMPLIANCE.md`)

---

## Repository Structure

```
myclaudedevops/
├── CLAUDE.md                     # This file — AI assistant instructions
└── tatkal-agent/
    ├── pyproject.toml
    ├── profile.example.json      # fake passengers; real profile.json is git-ignored
    ├── docs/                     # RESEARCH.md (user pain points), COMPLIANCE.md
    ├── src/tatkal_agent/
    │   ├── agent.py              # Claude agent loop over MCP tools
    │   ├── mcp_server.py         # MCP tools + human-in-the-loop gates (elicitation)
    │   ├── executor.py           # time-critical booking: clock sync, retries, fallbacks, reconciliation
    │   ├── retry.py / clock.py / errors.py / models.py / profile.py
    │   ├── providers/            # base.py interface, mock.py simulator, partner.py skeleton
    │   └── cli.py                # tatkal-agent run | drill | serve
    └── tests/
```

---

## Development Workflows

Run from `tatkal-agent/`:

- **Install**: `pip install -e ".[dev]"`
- **Test**: `python -m pytest -q`
- **Simulator drill (no API key)**: `tatkal-agent drill` (or `PYTHONPATH=src python -m tatkal_agent.cli drill`)
- **Lint**: _TBD_
- **Format**: _TBD_

---

## Conventions

- Write clear, descriptive commit messages
- Keep PRs focused on a single concern
- Follow whatever linting/formatting config is added to the project
- Prefer environment variables for all configuration and secrets

---

## CRITICAL RULES — NEVER BREAK THESE

### 1. Never read, open, show, summarize, copy, or mention files that may contain secrets

Do not touch files matching these patterns (even if asked):

- `.env`, `.env.*`, `*.env`, `.env.local`, `.env.development`, `.env.production`
- `.env.example` — safe to read ONLY if it contains fake/demo values
- `**/*.key`, `**/*.pem`
- `**/secrets/**`, `**/credentials/**`
- `**/.aws/**`, `**/.ssh/**`
- `id_rsa`, `id_ed25519`, `*.pkcs8`, `*.p12`, `*.pfx`
- Any file whose name contains: `api_key`, `apikey`, `secret`, `token`, `password`, `pwd`, `auth`, `credential`, `private`

### 2. If you see or suspect an API key / secret pattern in any file

- Do NOT output the value (not even partially obfuscated)
- Do NOT copy it anywhere
- Immediately reply only:

```
STOP: Detected possible secret / API key pattern.
I refuse to read, display or transmit any credential-like content.
Please remove or .gitignore sensitive files before continuing.
```

- Then stop further reasoning about that file

### 3. API key handling rules

- Never suggest putting real API keys directly into source code
- Never write code that hardcodes `sk-ant-...`, `sk-...`, `AKIA...`, `sg....`, or any other real-looking key pattern
- Prefer environment variables, secret managers (1Password, Doppler, AWS SSM, HashiCorp Vault, etc.)
- When generating example code, use only placeholder values like:

```python
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # or ""
```

```python
client = Anthropic(api_key="sk-ant-…your-real-key-here-but-never-commit")
```

### 4. File system and context safety defaults

- Respect the project `.gitignore` — do not propose reading ignored files
- When in doubt whether a file is sensitive, treat it as sensitive
- Never propose commands that do `cat`, `type`, `Get-Content`, `open`, `less` on suspected secret files

### Quick self-check before any file read

Ask yourself: _"Does this file name or path match a secret pattern?"_
- If yes — refuse and explain as above

**Stay paranoid about credentials — better to refuse 10 times than leak once.**
