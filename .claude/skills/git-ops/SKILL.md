---
name: git-ops
description: "Git commit skill for the Insight AI Agent project. Defines commit message conventions, branch strategies, and standard Git workflows."
---

# Git Operations Skill

**Announce at start:** "I'm using the git-ops skill to perform Git operations."

## Purpose

Standardize Git commit behavior for the Insight AI Agent project. This skill defines commit message format, staging rules, and branch conventions that Claude Code must follow when making commits.

## Commit Message Convention

All commit messages MUST follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type (required)

| Type | When to use |
|------|-------------|
| `feat` | New feature or functionality |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behavior change |
| `docs` | Documentation only changes |
| `test` | Adding or updating tests |
| `chore` | Build process, dependency updates, tooling |
| `style` | Formatting, whitespace, semicolons (no logic change) |
| `perf` | Performance improvement |
| `ci` | CI/CD configuration changes |

### Scope (optional but recommended)

Use the module or area affected. Common scopes for this project:

- `agent` -- changes to `agents/`
- `skills` -- changes to `skills/`
- `services` -- changes to `services/`
- `config` -- changes to `config.py` or `.env`
- `api` -- changes to Flask endpoints in `app.py`
- `docs` -- documentation updates
- `tests` -- test changes

### Subject (required)

- Use imperative mood: "add feature" not "added feature"
- Lowercase first letter
- No period at the end
- Max 50 characters

### Body (optional)

- Explain **what** and **why**, not how
- Wrap at 72 characters
- Separate from subject with a blank line

### Footer (optional)

- Reference issues: `Closes #123`
- Note breaking changes: `BREAKING CHANGE: description`

## Examples

```
feat(skills): add web search skill with Brave API

Implements WebSearchSkill that queries Brave Search API
and returns formatted results with titles and URLs.

Closes #12
```

```
fix(agent): prevent infinite tool loop on empty response
```

```
refactor(services): migrate from anthropic SDK to LiteLLM

Replace direct Anthropic API calls with LiteLLM to support
multiple LLM providers through a unified interface.

BREAKING CHANGE: AnthropicService removed, use LLMService instead.
```

```
chore: update requirements.txt with litellm dependency
```

## Commit Workflow

When asked to commit, follow these steps in order:

1. **Check status** -- Run `git status` to understand current changes.
2. **Review diff** -- Run `git diff` (and `git diff --staged`) to review all changes.
3. **Stage selectively** -- Stage specific files by name. Avoid `git add .` or `git add -A` unless explicitly asked. Never stage:
   - `.env` or any file containing secrets/API keys
   - `data/memory.json` (runtime data)
   - `__pycache__/` or `.pyc` files
   - IDE/editor config files (`.vscode/`, `.idea/`)
4. **Compose message** -- Write a commit message following the convention above based on the actual diff content.
5. **Commit** -- Execute the commit.
6. **Verify** -- Run `git log -1` to confirm the commit was created correctly.

## Branch Naming Convention

When creating branches:

```
<type>/<short-description>
```

Examples:
- `feat/git-ops-skill`
- `fix/memory-file-lock`
- `refactor/fastapi-migration`

## Rules

- **Never force push** to `main`.
- **Never commit secrets** -- check for `.env`, API keys, tokens before staging.
- **One logical change per commit** -- don't mix unrelated changes.
- **Always review the diff** before committing to ensure no unintended changes are included.
- **Chinese comments in commit body are acceptable** if the change context is in Chinese.
