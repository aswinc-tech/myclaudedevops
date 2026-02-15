# CLAUDE.md — AI Assistant Guide for myclaudedevops

This file provides instructions and context for AI assistants (such as Claude Code) working in this repository.

---

## Project Overview

- **Repository**: myclaudedevops
- **Status**: Newly initialized — no framework or language is established yet
- **Purpose**: DevOps project (to be defined as the codebase grows)

As files and structure are added, update this section to reflect the chosen language, framework, and architecture.

---

## Repository Structure

```
myclaudedevops/
├── CLAUDE.md          # This file — AI assistant instructions
└── .git/              # Git metadata
```

> Update this tree as the project grows.

---

## Development Workflows

No build, test, or lint commands are configured yet. When they are added, document them here:

- **Build**: _TBD_
- **Test**: _TBD_
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
