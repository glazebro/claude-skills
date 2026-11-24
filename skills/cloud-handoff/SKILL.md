---
name: cloud-handoff
description: >-
  Hand off the work in progress in this local Claude Code session to a cloud session at
  claude.ai/code so it can keep going while the user is away, then pull it back down with
  /teleport later. The shape is always: stop working locally now, let a cloud Claude session
  continue or finish the current task (often overnight or while they're gone), then resume it
  in the terminal tomorrow. Use it for any phrasing of that intent — "move/offload/hand this
  to the cloud", "finish this overnight in the cloud", "cloud handoff", "I'm leaving / end of
  day, get this running remotely and let me pick it up later" — even when the user doesn't say
  the word "skill". It commits and pushes the current branch's work-in-progress, then prints a
  paste-ready prompt that briefs a cloud session inline and tells it to finish on its own
  session branch (which the user later teleports down). Do NOT use it for deploying to a
  cloud/hosting environment, merely backing up or pushing a branch with no intent to continue
  elsewhere, pulling an existing cloud session down (that is plain /teleport), or debugging
  cloud logs — this is specifically about continuing the user's own in-progress work elsewhere
  and teleporting it home.
---

# Cloud handoff

## What this does and why

There is no way to push a running local CLI session straight onto Anthropic's cloud
infrastructure. The only cloud session you can later pull back down with `/teleport` is one
that was _started_ at claude.ai/code. So a clean handoff can't be fully hands-free — but
almost everything around the one manual step can be automated.

This skill does that automatable part: it gets the work-in-progress onto the remote branch and
hands the user a single paste-and-go prompt. The user starts the cloud session (a browser tap,
doable from a phone on the way out), the cloud finishes the work, and `/teleport` brings the
finished branch _and_ the conversation back into the terminal.

**Two hard constraints discovered in practice — the design depends on them:**

1. **The web branch picker usually lists only the repo's default branch** (whatever it is —
   `main`, `master`, etc.), even though the pushed branch exists on GitHub. The cloud session can still `git fetch` + `git checkout` or
   `git merge` any branch — the picker is just a UI limit. So the user leaves the picker on
   the default branch; the pasted prompt moves the work onto the session.
2. **The cloud git proxy returns HTTP 403 on pushes to any branch except the session's own
   `claude/...` branch.** The cloud therefore CANNOT push back to the handoff branch. The work
   must end up on the session's own branch, which is exactly what `/teleport` pulls down. The
   user then merges that branch into their feature branch locally. (Don't try to make the cloud
   push to the handoff branch — it will 403.)

Because of constraint 2, the briefing travels **inline in the pasted prompt**, not as a
committed file. That keeps the branch clean — nothing extra is ever committed, so there's
nothing to delete and nothing left lingering.

## Prerequisites (state them; you can't fully verify from the terminal)

- The repo is on **GitHub and connected to Claude Code on the web**.
- The user is signed in with their **claude.ai subscription account** (not API key / Bedrock /
  Vertex). `/login` if unsure.

## Procedure

### 1. Guard rails

```bash
git rev-parse --show-toplevel
git branch --show-current
pwd
git remote                              # verify an 'origin' exists — don't print its URL (an HTTPS remote can embed a token)
git rev-parse --abbrev-ref origin/HEAD  # the repo's real default branch, e.g. origin/main (empty if unset)
```

- If `git rev-parse --show-toplevel` fails with `not a git repository`, **stop**: tell the user
  to `cd` into the repo they want to hand off (don't surface the raw git error). Easy to hit if
  the shell's working directory drifted.
- If `git branch --show-current` is empty (detached HEAD), **stop** — there's no branch name to
  push and `git push -u origin ""` would fail. Ask the user to check out a feature branch first.
- If the current branch is the repo's default branch, **stop** — you don't hand off the default
  branch. Compare against `git rev-parse --abbrev-ref origin/HEAD` (don't assume `main`; it may be
  `master`, `develop`, etc.). Ask the user to switch to (or create) a feature branch.
- If `git remote` lists no `origin`, **stop** — there's nowhere for the cloud to pull from.
- A git worktree is fine; the current branch pushes normally.

### 2. Commit and push the work-in-progress

Get the actual code changes onto the remote so the cloud can fetch them. **Do not write a
handoff file** — the briefing goes inline in the prompt (step 4).

```bash
git add -A
git commit -m "wip: end-of-day cloud handoff" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin "$(git branch --show-current)"
```

- Use whatever Claude co-author trailer your environment specifies (model + variant if you have it).
- If the working tree is already clean, skip the commit but **still push** — the branch may have
  local commits the remote lacks.
- If a commit-msg hook rejects `wip:`, retry with `chore: end-of-day cloud handoff`.

### 3. Build the briefing

Compose the briefing from _this_ session's real context — the cloud agent has none of this
conversation, so this is its only context. Spend your effort here; a vague briefing means the
cloud guesses wrong. Cover:

- **Task** — what we're building/fixing and why.
- **Done so far** — what's implemented/decided, key files touched.
- **Remaining work** — concrete, ordered next steps (file paths, function names, the real change).
- **Acceptance criteria** — what "done" looks like, including the repo's check command if one
  exists (`bun run check`, `npm test`, `make check` — find the right one in package.json /
  Makefile / AGENTS.md).
- **Gotchas** — flaky tests, env quirks, conventions in AGENTS.md / CLAUDE.md.

### 4. Print the launch action

Print exactly two things and nothing else — the user wants one action plus a copyable prompt,
not a checklist. Do NOT print prerequisites, a "what to watch" list, or a closing paragraph;
everything operational lives inside the prompt, including the final teleport-down instructions
(which the cloud surfaces at the end of its run).

1. One line: **"Start a new session at https://claude.ai/code on this repo (leave the branch on
   the repo's default branch — the one the picker defaults to), then paste this:"**
2. The seed prompt — a single copyable block, with the branch name and the step-3 briefing
   filled in:

   ```
   You're finishing work I started locally on the branch <branch>. Do this in order:

   1. Load my work-in-progress: run `git fetch origin && git merge origin/<branch> --no-edit`
      so my pushed commits land on your current session branch. (The web picker only lists the
      default branch, so you likely started on it — this brings my work onto your session.)

   2. Complete the task described in the briefing below. Follow the repo's conventions
      (AGENTS.md / CLAUDE.md) and run its checks before finishing.

   --- BRIEFING ---
   <paste the step-3 briefing here>
   --- END BRIEFING ---

   3. Commit your work and keep it on YOUR session branch. The web git proxy returns HTTP 403
      on pushes to any other branch, so do NOT push to <branch> — pushing your own session
      branch is what makes this work teleportable.

   4. As your FINAL message, tell me exactly how to bring this down to my terminal: that from
      this repo I run `/teleport` (or `claude --teleport`) and pick this session from the list
      by its title (the name shown in the cloud sessions tab — the picker lists sessions by
      title, NOT by branch). It will then check out your session branch locally. Also state
      your session branch name so I know what got checked out, and remind me I can merge it
      into <branch>.
   ```

That's the entire output. The prompt is self-contained: it fetches the work, completes it,
keeps it on the session branch, and ends by telling the user the exact `/teleport` command and
branch name. Nothing was committed as a handoff file, so there's nothing to clean up.

## Keep it tight

This is a fast end-of-day action — the user is trying to leave. Don't ask for confirmations you
don't need. The one place to spend effort is the briefing: it's the cloud's only context.
