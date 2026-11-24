---
name: branch-review
description: Review the current branch before pushing, sized to the risk of the change — a quick /simplify + /code-review --fix pass for most diffs, a six-angle parallel deep review for large or sensitive ones (always confirmed first, with a token-cost warning), and a hand-off to /cross-review when a second model's view matters. Use whenever the user types `/branch-review`, `/branch-review --deep`, or asks to "review before I push", "get my branch ready to push", "do I need a deep review", or "deep review this branch". Pass a PR number to deep review someone else's PR read-only. Not for acting on review comments already left on a PR (use review-pr-comments).
---

The argument is: $ARGUMENTS

# Branch review

Decide how much AI review the branch needs, run it, and hand back a branch that is ready to push. Never push, never post to GitHub or an issue tracker.

**Arguments.** No argument: review the current branch. `--deep`: skip the triage question and run the deep review (still confirm the cost once). A PR number: run deep mode read-only against that PR (see `deep.md`), and skip the light pass and the edits, since the code is not yours to change.

**Model split (keeps token spend down).** The session running this skill is the advisor: it triages, reads the results, decides and writes the hand-back, so run it on the strongest model you have (`/model`). Work that fans out into sub-agents runs on a cheaper Sonnet-class model: set `model: "sonnet"` when you spawn them, and tell `/simplify` and `/code-review` to launch their agents on `sonnet` (best effort, since those skills choose their own agent settings). If the user asks for the most thorough review, skip the downgrade and let sub-agents inherit.

## Step 1: Verify state

- Run `git branch --show-current` and `pwd`. If the branch is the default branch, stop and ask which branch they meant.
- Run `git status --porcelain`. If any **tracked** file is modified or staged, stop and ask the user to commit or stash first, so the AI's edits can be told apart from theirs. Untracked files are fine, but never stage or edit them.
- Base is `origin/<default branch>` (detect with `git rev-parse --abbrev-ref origin/HEAD`, falling back to `main`). Substitute the resolved value into each command, since every fenced command runs in its own shell. Scope for every step below is `BASE...HEAD`.
- Read the project's convention docs at the repo root (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`) if present. They define the check command and the rules the review should enforce.

## Step 2: Triage (no model call)

Run `git diff --stat BASE...HEAD` and `git diff --name-only BASE...HEAD`, then pick a tier:

- **Skip** — every file is plain documentation (`docs/`, `README.md` and similar), infrastructure-as-code, or a lockfile that changed without a matching manifest change. Markdown that steers agents or tooling is **not** plain documentation: `AGENTS.md`, `CLAUDE.md`, anything under `.claude/` and `.github/` is at least **Light**. Infrastructure that touches secrets, identity or access, networking or state backends is **Deep recommended**. When files qualify for different tiers, the highest tier wins. Skip means no AI passes, not no verification: go straight to Step 5.
- **Deep recommended** — any of: more than ~800 changed lines or ~40 files (a cost heuristic); touches authentication or session code, API route handlers, middleware or proxies, database access or migrations, infrastructure, or anything handling user input or secrets. Infer the matching paths from the repo layout; treat this as a starting list and use judgment.
- **Light** — everything else.

Also note new logic files with no matching test, and anything the convention docs prohibit that is cheap to spot (for example newly added comments where the docs ask for none). Report the tier and the one-line reasons in two or three lines.

## Step 3: Light pass

Always run this for Light and Deep-recommended branches. Deep adds to it, never replaces it.

1. Run `/simplify`, scoped explicitly to the branch diff `BASE...HEAD` (its default is only uncommitted changes or the last commit). Tell it to launch its review agents on `sonnet`.
2. Run `/code-review medium --fix`, scoped to the working tree against the merge base (`git diff $(git merge-base BASE HEAD)`), so it sees the branch's commits and the uncommitted edits `/simplify` just made. Tell it to launch its agents on `sonnet` and to treat every rule in the convention docs as a checklist.
3. Do not add tests or expand scope yourself. If a bug was fixed without a regression test, list it for the author.

## Step 4: Deep review (Deep recommended, or `--deep`)

Never start a deep review or `/cross-review` without asking. Use AskUserQuestion with a clear cost warning: deep mode fans out up to six parallel reviewers that each read the whole diff, so it uses several times the tokens of the light pass. Options:

- **Deep review now** — Claude only, six angles in parallel (correctness, security, tests, performance, maintainability, project conventions). Read `deep.md` in this skill's folder and follow it. It reviews the working tree against the merge base, so it also sees the light pass's edits.
- **Cross-review instead** — `/cross-review` (needs the GitHub Copilot CLI). A second, non-Anthropic model checks Claude. Best for a risky design or a security-sensitive change, where model diversity matters more than breadth. Tell it to skip its offer to post findings to the PR: this workflow never posts.
- **Skip both** and push with the light pass only.
- **Stop here.**

Default recommendation follows the triage reasons. If the user declines, say what the triage was worried about so they can decide with that in mind.

## Step 5: Verify the edits

Run the project's full check command (named in its convention docs or package scripts) once after the last edit, whether or not the AI edited anything. If that is too slow for a tiny change, say so and let the user decide whether to run a lighter subset; never choose the shortcut for them. If the AI's edits broke something, fix or revert those edits, not the author's code. Do not report the branch as ready until the checks actually passed.

## Step 6: Hand back

Show `git diff --stat` of the AI's edits and a short summary:

- the triage tier and why
- what `/simplify` and `/code-review` changed, and what they flagged but left alone
- the deep or cross-review result, or that it was skipped
- anything the author must still do (missing regression tests, or an end-to-end test where the project requires one)

Leave the edits uncommitted and ask whether to commit them as a separate commit named `ai-review: simplify and fixes`, so they are easy to review or revert. Do not push.
