---
name: critic-loop
description: Take a piece of work from "works" to "exceeds expectations" with a critic-and-builder loop. A strong-model critic uses or reads the real thing, scores it against the best in its class, and writes ranked must-fixes; cheaper builder agents fix them in separate, non-overlapping work packages; the critic re-scores; repeat until nothing scores below the target or the user says ship. Works on an app, a feature, a page, a document, a résumé or a profile. Use when the user asks to "make this exceptional", "run the critic loop", "score and improve this", or "get this to an 8 out of 10 everywhere".
---

The argument is: $ARGUMENTS

# Critic loop

One target per run. Never start a second target until the user has seen the first result.

## 0. Frame the target

Agree with the user, in a few lines:

- **What is being improved** and where it lives (a running app, a branch, a file, a live page).
- **Who it is for** and what that reader or user must get from it.
- **What "best in class" means:** two or three named benchmarks or a short description.
- **The target score** (default 8 out of 10 on every section) and the round cap (default 3).
- **Hard rules** the work must never break: facts that may not be invented, numbers that need approval, names that must not appear, actions that need a yes (publishing, spending, deleting).

Write these into a short `goals.md` in a scratch folder. Every agent reads it first.

## 1. Gather evidence

Collect what the critic needs, in the scratch folder: the current version, the source facts, the benchmarks, and any usage or feedback data. Capture nothing static that the critic could check live: if the target can be used (an app, a page), the critic uses it.

## 2. Critic round (strongest model)

Spawn one critic agent on the strongest model available. Brief it with the scratch folder and ask for, as its reply (not a file, so you control what lands on disk):

1. **Scores 0–10** per section, compared against the benchmarks, with one line of reasoning each.
2. **Problems actually seen,** with the evidence (a screenshot, a quote, a reproduction).
3. **Ranked must-fixes:** the exact change, the benefit, effort (S/M/L), risk, and which files or sections it touches.
4. **Rule breaks and overclaims:** anything in the current version that violates `goals.md`.
5. **Questions only the user can answer:** approvals, facts to confirm, decisions.
6. **Work packages:** the must-fixes split into two or three packages that touch **disjoint** files or sections.

Tell the critic: every proposed claim must trace to the evidence; where a number would help but is not approved, list it as a question instead of inventing it; and no web searches containing private details.

## 3. Show the user before building

Present the scores, the top must-fixes and the open questions. Get answers to anything that blocks the build, and an OK for anything in the hard-rules list. Do not start building around an unanswered decision.

## 4. Builder round (cheaper models)

- For code, commit a stub for any interface two packages share, then give each package its own branch or worktree so builders cannot collide.
- Spawn one builder per package on a mid-tier model, with: the critique sections it owns, the files it must not touch, the project's conventions, "tests first" where there are tests, and the check command it must pass.
- Mechanical work (copy edits, asset resizing, metadata) can go to the cheapest model.
- Merge packages only after each passes its checks, and only with the user's go-ahead.

For a small text target (a résumé, a profile), the session can write the revision itself instead of spawning builders.

## 5. Re-score

Send the critic the revised version and the user's decisions, and ask for the same score table (previous round next to this one), anything still below target with an exact replacement, and any new rule breaks. Apply what passes the rules, answer what needs the user, and repeat, up to the round cap.

## 6. Gate, then ship

Before anything goes out:

- Every section meets the target, or the user has accepted the gap.
- Every claim traces to the evidence, and every number was approved.
- The user has seen the final version, and has said go for anything outward-facing.

Then ship it the way this target ships (merge, publish, submit) and verify the live result by reading it back.

## 7. Stop and report

Show the before and after scores, what changed, what was deliberately left, and what still needs the user. Do not schedule wake-ups to wait on anything; report and stop.

## Lessons

- A critic that **uses** the thing finds what screenshots hide: a headline feature that never returns results looks fine in a static capture.
- A metric can lie. Check that an event or number is really produced before reading meaning into a zero.
- Split work by files, not by topic, or parallel builders overwrite each other.
- The critic's job is the reader's view. The builder's job is the fix. Keep them in different agents so the critic never grades its own work.
