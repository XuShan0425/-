---
name: "auto-skill-installer"
description: "Use when the user wants Codex to find and install an Agent Skill from a natural-language description rather than a known skill name. Search GitHub and agentskills.io for likely matches, prefer skills with a clear SKILL.md and installation path, install the best fit from GitHub into $CODEX_HOME/skills, then verify the installed files and tell the user the exact commands or prompts they can use next."
---

# Auto Skill Installer

Find, choose, install, and verify a Skill from a user description. This skill is for discovery plus installation, not just raw listing.

## When To Use

Use this skill when the user says things like:

- "帮我找一个能做 X 的 skill"
- "根据这个需求安装合适的 agent skill"
- "去 GitHub 或 agentskills.io 找个能处理 Y 的 skill"

Do not use this skill when the user already gave an exact local skill name that `skill-installer` can install directly without search.

## Outcome

By the end of the workflow you should:

1. Search for candidate skills on GitHub and agentskills.io.
2. Pick the best match and explain why it fits.
3. Install it from GitHub into `~/.codex/skills`.
4. Verify the installed directory contains a valid `SKILL.md`.
5. Tell the user whether a restart is needed and give exact follow-up commands they can say.

## Search Workflow

### 1. Turn the request into search terms

Extract:

- the task domain
- required tools or platforms
- hard constraints
- nice-to-have features

Produce 2 to 4 short search queries, for example:

- `<task> agent skill`
- `<task> codex skill`
- `site:agentskills.io <task>`
- `site:github.com SKILL.md <task> "agent skill"`

### 2. Search both sources

Use web search for discovery:

- Search agentskills.io first when the request is broad and the user wants an existing published skill.
- Search GitHub directly when the request is technical, niche, or likely to live in a repo rather than a directory site.

When a result is on agentskills.io:

- Open the page.
- Look for the underlying GitHub repository or installation source.
- If the page does not expose a usable GitHub source, do not fabricate one. Report that it is not auto-installable from the available page.

When a result is on GitHub:

- Confirm there is an actual skill directory, not just a mention.
- Prefer repositories that contain a `SKILL.md` in the candidate path.
- Prefer clear install paths such as `skills/<name>` or a top-level skill directory.

### 3. Rank candidates

Rank by:

1. Direct match to the user's description.
2. Presence of `SKILL.md`.
3. Clear repo/path installability.
4. Signs the skill is maintained and documented.
5. Low ambiguity about what the skill does.

Reject candidates that are only blog posts, prompts, or README mentions without a real skill folder.

## Installation Workflow

Use the existing system skill installer scripts. Read `/home/tong/.codex/skills/.system/skill-installer/SKILL.md` only if you need a refresher on flags.

All networked install commands require escalation in the sandbox. Do not ask the user to run them first; run them yourself and request approval if needed.

Preferred install method:

1. If you have a GitHub tree URL, run:
   `python3 /home/tong/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --url <github-tree-url>`
2. If you have repo plus path, run:
   `python3 /home/tong/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo <owner>/<repo> --path <path/to/skill>`

If multiple candidates are close, pick the smallest reasonable set and explain the tradeoff. Default to installing one skill unless the user explicitly wants multiple.

## Verification Workflow

After installation, always verify locally.

### Required checks

1. Confirm `~/.codex/skills/<installed-skill>/SKILL.md` exists.
2. Read the frontmatter `name` and `description`.
3. If present, read `agents/openai.yaml` for `display_name` and `default_prompt`.
4. Run:
   `python3 /home/tong/.codex/skills/auto-skill-installer/scripts/summarize_installed_skill.py ~/.codex/skills/<installed-skill>`

If verification fails, say exactly what is missing and do not claim the skill is ready.

## What To Tell The User

After a successful install:

1. Name the installed skill and where it was installed from.
2. State whether Codex restart is needed. Default: `Restart Codex to pick up new skills.`
3. Give exact commands or prompts the user can use next.

Use the verifier script output to build command suggestions. Prefer commands in this order:

1. `$<skill-name>`
2. `使用 <skill-name> ...`
3. If `display_name` exists, `使用 <display_name> ...`
4. A concrete natural-language example tailored to the user's original task

## Response Style

Keep the final response short and operational:

- what you found
- what you installed
- verification result
- exact next commands

If no safe, installable skill is found, say that clearly and include the best search result you found plus why it was rejected.
