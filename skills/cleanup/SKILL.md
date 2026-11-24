---
name: cleanup
description: Review and apply the machine cleanup queue — leftover worktrees, local branches, orphaned dev servers, compose (DB) stacks, idle Claude sessions, and what can be freed when the Mac is strained. Use when the user types /cleanup, says the machine is slow, or a session-start or load notice says cleanup items are waiting.
---

# Cleanup

Pick the script first. If the project ships its own `$CLAUDE_PROJECT_DIR/.claude/hooks/session-cleanup.py`,
use that one and its project skill's rules. Otherwise use
`~/.claude/skills/cleanup/session-cleanup.py` (called `$S` below). It runs from the project's hooks in
`.claude/settings.local.json`, cleans what is provably safe by itself, and queues everything else here
for a yes or no. State lives in `<git common dir>/claude-cleanup/` (`log.txt` lists everything it did).

This copy is tuned for web repos that squash-merge pull requests. A branch or worktree counts as merged
when its tip is in `origin/main` or is the head commit of a merged GitHub PR. Modifying `.env.local`
does not count as a change. Removing a worktree also stops its dev servers and runs
`docker compose -p <stack> down -v` on its compose stack. A branch is deleted only when its tip is merged.

1. Refresh and read the queue:

   ```
   python3 "$S" sweep && python3 "$S" report
   ```

   If the report says the machine is strained, lead with that and the top processes.

2. Ask with AskUserQuestion. Group the queue by kind (worktrees, branches, compose stacks, processes,
   Claude sessions). Each question offers "All of them", "None, and stop asking", and "Let me pick".
   Use multiSelect for "Let me pick" when a group has four or fewer items. A larger group gets a plain
   list in your reply, and the user names the ids. Say plainly what is lost: uncommitted changes,
   commits not pushed anywhere, ignored files that may matter, a running dev server or DB stack, an
   open Claude session.

3. Apply the answers:

   ```
   python3 "$S" apply <id> [<id>...]
   python3 "$S" keep <id> [<id>...]   # declined: never asked again
   ```

   Leave items the user skipped without deciding in the queue. Never stop a Claude session that is
   the current one, and never touch MCP-owned Chrome. Kill processes only by exact PID.

4. Report what was done, then run `report` again and show what is left.

`enable` / `disable` turn the automatic cleaning on or off. While it is off, the report shows what
it _would_ clean, and `apply` works on those items too. The user wants it left off: ask about the
"would clean automatically" items in step 2 too, grouped separately as "merged, safe" with
"All of them" recommended. Never run `enable` unless the user asks for it by name.

## Wiring a repo

Merge these into the repo's gitignored `.claude/settings.local.json` (never the committed settings):

```json
"hooks": {
  "SessionStart": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/cleanup/session-cleanup.py\" start", "timeout": 15 }] }],
  "Stop": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/cleanup/session-cleanup.py\" load", "timeout": 15 }] }],
  "SessionEnd": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/cleanup/session-cleanup.py\" end", "timeout": 15 }] }]
}
```

Start with automatic cleaning off. Show the user the first dry-run report before running `enable`.
