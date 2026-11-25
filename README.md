# claude-skills

Claude Code skills, plugins and hooks I use every day to run AI agents as an engineering team: review that scales with risk, two different models checking each other, a ticket-to-PR pipeline with human gates, and the housekeeping that keeps parallel agent sessions from stepping on each other.

Everything here is generic. The skills read each project's own `AGENTS.md`, `CLAUDE.md` or `CONTRIBUTING.md` for its check command, conventions and test setup, so nothing is tied to one codebase.

## How I run agents

- **Outcomes, not chat.** I give agents an outcome and let them build, test, review and ship it, with human approval gates before anything outward-facing.
- **Verify against the live system.** "Done" means the agent read back the real state: the checks passed, the page renders, the API answered.
- **Size review to risk.** Most diffs get a quick, cheap pass. Large or sensitive ones get a parallel multi-angle review, and contested calls get a second model.
- **Different models audit each other.** Claude and a non-Anthropic model answer independently, then challenge each other. What survives is worth acting on.
- **Spend tokens where they matter.** The strongest model advises and critiques; cheaper models do the fan-out work.

## Review (plugin)

Install with `/plugin marketplace add glazebro/claude-skills`, then `/plugin install review-kit@claude-skills`. See [`plugins/review-kit`](plugins/review-kit/README.md).

| Skill           | What it does |
| --------------- | ------------ |
| `branch-review` | Triage the branch diff and run the right amount of review before you push: a quick simplify-and-fix pass for most changes, a six-angle parallel deep review (correctness, security, tests, performance, maintainability, conventions) for large or sensitive ones, always confirmed first. |
| `cross-review`  | Claude and GitHub Copilot, pinned to a non-Anthropic model, answer independently, cross-examine each other, and Claude writes one confidence-graded conclusion. Works on code and on plans or design decisions. |

## Agent workflows

| Skill                | What it does |
| -------------------- | ------------ |
| `ticket-to-pr`       | Take one ticket from intake to a push-ready branch: read it, judge whether it is groomed, grill scope, plan, build test-first, prove, choose the review depth, and hand back a drafted PR. Three human gates. Works with any tracker. |
| `review-pr-comments` | Fetch unresolved PR review threads, judge which are valid, fix the valid ones test-first one commit at a time (proving each regression test fails without the fix), and resolve the threads. |
| `critic-loop`        | A strong-model critic scores the real thing against the best in its class; cheaper builders fix it in non-overlapping packages; the critic re-scores until everything reaches the target. Works on apps, features, documents and profiles. |
| `ai-bridge`          | Claude and OpenAI Codex analyze a question blind, critique and rebut each other, and the report keeps any disagreement visible instead of averaging it away. Resumable task folders, and consequential actions wait in an approvals ledger for your own yes. |
| `visual-review`      | Drive a real, visible browser through the screens a branch changed, with captions, before-and-after screenshots and a UX findings pass. |
| `cloud-handoff`      | Push work in progress and brief a cloud Claude Code session to finish it, then pull it back with `/teleport`. |

## Housekeeping

| Item                               | What it does |
| ---------------------------------- | ------------ |
| `rebase-and-push`                  | Rebase onto the latest default branch, walk through conflicts, and pause for review before a `--force-with-lease` push. |
| `cleanup`                          | Find and clear leftovers from parallel agent sessions: merged worktrees and branches, orphaned dev servers and container stacks, idle sessions. Asks before anything it cannot prove is safe. |
| `hooks/guard-destructive-git.sh`   | A `PreToolUse` hook that stops `rm -rf`, `git clean`, `git reset --hard`, `git checkout --` and `git restore` until the user confirms. |

## Install the skills

```bash
git clone https://github.com/glazebro/claude-skills ~/claude-skills
for s in ~/claude-skills/skills/*/; do
  ln -sfn "$s" ~/.claude/skills/"$(basename "$s")"
done
```

To use the git guard, copy `hooks/guard-destructive-git.sh` somewhere stable, make it executable, and add it to `~/.claude/settings.json` (it needs `jq`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "~/.claude/hooks/guard-destructive-git.sh" }]
      }
    ]
  }
}
```

## Credits

The grilling and planning skills I use alongside these come from [mattpocock/skills](https://github.com/mattpocock/skills). Use them from there.

## License

MIT
