# review-kit

AI code review before you push, sized to the risk of the change. No credentials are stored: every step runs in the developer's own signed-in Claude Code session.

| Skill           | What it does                                                                                                                                                                                                                 |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `branch-review` | Triage the branch diff, run `/simplify` and `/code-review --fix` scoped to the branch, re-run the project's checks, and offer a six-angle parallel deep review (always confirmed first) when the change is large or sensitive. |
| `cross-review`  | Claude and GitHub Copilot, pinned to a non-Anthropic model, answer independently, cross-examine each other, and Claude writes one confidence-graded report. Works for code and for design decisions. |

## Install

```
/plugin marketplace add glazebro/claude-skills
/plugin install review-kit@claude-skills
```

To have a repo suggest the plugin to everyone who opens it, add this to the repo's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "claude-skills": {
      "source": { "source": "github", "repo": "glazebro/claude-skills" }
    }
  },
  "enabledPlugins": { "review-kit@claude-skills": true }
}
```

## Requirements

- Claude Code with the built-in `/simplify` and `/code-review` skills.
- `git`, and `gh` for PR-mode reviews.
- `cross-review` only: the GitHub Copilot CLI (`brew install --cask copilot-cli`, then `copilot login`), plus the one Bash permission rule in the skill's Team setup section, added by a human to `~/.claude/settings.json`. Without Copilot, `cross-review` stops and says so; `branch-review` is unaffected.

## How it adapts to a repo

Both skills read the repo's `AGENTS.md`, `CLAUDE.md` or `CONTRIBUTING.md` for the check command and the rules to enforce, and infer security-sensitive paths from the layout. Nothing is hard-coded to one project.

## Cost

`branch-review` skips docs, infrastructure and lockfile-only changes. `/simplify` and `/code-review` each run several sub-agents on a cheaper model. The deep review and `cross-review` never start without an explicit yes.
