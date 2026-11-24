---
name: rebase-and-push
description: Rebase the current git branch onto the latest main, walk the user through resolving any conflicts, then pause for review before force-pushing with --force-with-lease. Use whenever the user says "rebase onto main", "rebase in main", "rebase and push", "catch my branch up to main", "update my branch with main", "sync with main", "resolve the conflicts and push", or otherwise wants their feature branch replayed on top of the latest main and pushed. Always rebases (never merges) and always stops for the user to review the result before pushing.
---

# Rebase onto main & push

Replay the current branch on top of the latest `main`, help resolve any conflicts, then **stop and let the user review** before force-pushing. Rewriting a pushed branch's history requires a force-push, so the review gate exists to make sure the user sees exactly what will be published before it happens.

This skill **always rebases** (never merges) and **always pauses before pushing** — those are deliberate, non-negotiable parts of its contract. If the user wants a merge instead, or wants an auto-push, that's a different workflow; tell them so rather than silently doing it here.

## Environment notes

- `git rebase --continue` and any editor-driven step will **hang** in this non-interactive environment because there's no editor to open. Prefix those calls with `GIT_EDITOR=true` (keeps the existing commit messages) so git doesn't wait on an editor.
- Never pass `--no-verify` or otherwise skip hooks unless the user explicitly asks. If a pre-push hook fails, surface it — don't route around it.

## Step 0 — Preflight (stop early if any of these fail)

Run these checks before touching anything. Each one has a failure mode that's much cheaper to catch now than mid-rebase.

```bash
git branch --show-current                # current branch (empty output = detached HEAD)
git status --porcelain                   # working-tree cleanliness
ls "$(git rev-parse --git-path rebase-merge)" "$(git rev-parse --git-path rebase-apply)" 2>/dev/null   # is a rebase already in progress?
git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##'   # repo's actual default branch name (origin/ prefix stripped so it's directly comparable to the current branch), empty if unset
```

`git rev-parse --git-path` resolves the real gitdir, so the rebase-in-progress check works in `git worktree` checkouts too (where `.git` is a file pointing elsewhere, not a directory).

| Condition                                                                                                                       | What to do                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Current branch **is** `main`, or matches the default branch printed above (fall back to `main` if that command printed nothing) | Stop. There's nothing to rebase the default branch onto itself — the user is probably on the wrong branch. Say so and ask which branch they meant.                                                                                           |
| Working tree is **dirty** (any porcelain output)                                                                                | Stop. Rebase refuses to run with uncommitted changes, and blindly stashing can surprise the user. Show them the dirty files and offer to either `git stash push -u` (and `git stash pop` after the rebase) or commit first. Let them choose. |
| A rebase is **already in progress** (either dir exists)                                                                         | Stop. Don't start a second one. Show `git status` and ask whether they want to continue/abort the existing rebase first.                                                                                                                     |
| Detached HEAD                                                                                                                   | Stop. There's no branch to push. Ask the user what they intended.                                                                                                                                                                            |

## Step 1 — Fetch the latest main

```bash
git fetch origin

UPSTREAM=origin/main
git rev-parse --verify --quiet "$UPSTREAM" >/dev/null \
  || UPSTREAM=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD)
git rev-parse --verify --quiet "$UPSTREAM" >/dev/null \
  || { echo "Cannot resolve an upstream: neither origin/main nor origin/HEAD is set. Ask the user which branch to rebase onto." >&2; exit 1; }
echo "$UPSTREAM"
```

Resolve the upstream to rebase onto once, here. Default to `origin/main` (the usual default); if `origin/main` doesn't resolve, fall back to the remote's real default (`origin/HEAD`) rather than guessing. If neither resolves (`origin/HEAD` isn't always set), the final guard stops with an actionable error instead of leaving `$UPSTREAM` empty and letting a later `git rebase ""` fail confusingly — ask the user which branch to rebase onto. **Every command below reuses this `$UPSTREAM` ref** — since each fenced block runs in its own shell, substitute the value you resolved here when you run them.

## Step 2 — Rebase

```bash
git rebase "$UPSTREAM"
```

Three outcomes:

- **"Current branch … is up to date."** — the branch is already on top of `$UPSTREAM`. There's nothing to replay and nothing new to push. Report that and stop; don't force-push just to no-op.
- **Clean replay, commits moved.** — go straight to Step 4 (review). The branch history was rewritten (new commit SHAs), so a push will now require `--force-with-lease`.
- **Conflicts.** — go to Step 3.

## Step 3 — Resolve conflicts (loop until the rebase finishes)

Rebases apply your commits one at a time, so you may hit several conflict rounds. Each round:

1. See what's conflicted:
   ```bash
   git diff --name-only --diff-filter=U
   ```
2. Resolve each file. Read the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) and understand **both** sides before choosing — during a rebase, `--ours` is the incoming `$UPSTREAM` side and `--theirs` is your branch's commit, which is the reverse of a merge and a classic footgun. When the resolution isn't obvious, show the user the conflicting hunks and ask rather than guessing which side wins.
3. Stage the resolved files:
   ```bash
   git add <files>
   ```
4. Continue (no editor, so keep the existing message):
   ```bash
   GIT_EDITOR=true git rebase --continue
   ```
5. Repeat from step 1 if more conflicts appear.

Escape hatches to offer if things go sideways:

- `git rebase --skip` — drop the current commit being replayed (only if the user confirms that commit is genuinely redundant, e.g. already in `main`).
- `git rebase --abort` — bail out completely and restore the branch to exactly where it was before Step 2. This is always safe; reach for it if the conflicts are more than the user wants to take on right now.

## Step 4 — Pause for review (do NOT push yet)

This is the whole point of the skill: **stop here and show the user the result before publishing it.** Gather the picture and present it:

```bash
git log --oneline "$UPSTREAM"..HEAD      # exactly the commits that will be pushed
git status                               # confirm rebase finished, tree clean, "ahead of origin/<branch> … (use force-push)"
git range-diff @{u}...HEAD 2>/dev/null    # optional: what actually changed vs the pre-rebase branch, if an upstream is set
```

Also recommend running the project's check command now (from its convention docs or package scripts), since conflict resolution is a real code change and should be verified before pushing.

Then present a short summary and **wait for the user's explicit go-ahead**:

- Which commits will be pushed (the `$UPSTREAM..HEAD` list).
- Whether there were conflicts and how they were resolved.
- The result of the check command (if run) — if it failed, say so and do **not** push until it's fixed or the user overrides.
- A plain statement that the next step is a force-push and you're waiting for the OK.

Do not proceed to Step 5 until the user confirms.

## Step 5 — Push

Once the user says go:

```bash
BRANCH=$(git branch --show-current)
git push --force-with-lease --force-if-includes -u origin "$BRANCH"
```

Naming `origin "$BRANCH"` explicitly makes the push work even when the branch has no upstream configured (a bare `git push` fails under `push.default=simple` in that case), and `-u` sets the upstream for next time. The lease is unaffected — `--force-with-lease` still computes it from the branch's remote-tracking ref.

Why this exact command:

- `--force` is rewriting-history-safe **only** if nobody else has pushed to the branch. Plain `--force` would clobber a teammate's commits without warning.
- `--force-with-lease` refuses the push if the remote branch moved since your last fetch — it protects the teammate's commits you didn't know about.
- `--force-if-includes` closes a gap in `--force-with-lease`: it additionally verifies your local ref actually incorporated the latest remote state you fetched, so a background `git fetch` can't quietly make the lease pass when it shouldn't.

If the push is rejected because the lease is stale, **stop** — someone pushed to the branch since Step 1. Don't retry with `--force`. Re-fetch, show the user what landed (`git log HEAD..@{u} --oneline`), and decide together whether to rebase those commits in too.

## When NOT to use this skill

- User wants to **merge** `main` into the branch (no history rewrite, no force-push) → that's a plain `git merge origin/main`, not this skill.
- User wants to rebase onto something other than `main` (another feature branch, a specific SHA) → the flow is similar but confirm the target explicitly; don't assume `main`.
- User wants an **interactive** rebase to squash/reorder their own commits → that's `git rebase -i`, which needs a real editor and isn't what this skill does.
- User just wants to push existing commits with no rebase → that's a normal `git push`; don't force anything.

## Reporting back

Keep it short. Include:

- The upstream rebased onto (the `$UPSTREAM` resolved in Step 1, usually `origin/main`) and whether the branch was already up to date.
- Whether conflicts occurred and, if so, which files and how they were resolved.
- The commit list that will be / was pushed.
- The check command's result, if you ran it.
- For the pause: an explicit "waiting for your OK to force-push." For the push: confirmation it succeeded with `--force-with-lease`, or the exact rejection reason if it didn't.
