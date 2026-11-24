---
name: ticket-to-pr
description: Take one ticket from intake to a push-ready branch through a fixed line of stations with human gates. It reads the ticket, judges whether it is groomed enough, grills scope right after reading, then plans, builds, proves, picks the right review depth, and hands back a branch and a drafted PR body. Works with any tracker Claude can read (Jira, Linear, GitHub Issues, or a pasted ticket). Use whenever the user types `/ticket-to-pr <KEY>`, or says "work this ticket", "take <KEY> end to end", or "pick up <KEY>". Not for reviewing someone else's PR, sweeping a backlog, or a one-off review of an existing branch (use branch-review).
---

The argument is: $ARGUMENTS

# Ticket to PR

Run one ticket through the stations below in order. Each station has an exit condition; do not start the next station until it is met. Three stations are human gates: stop and wait for the user there.

The tracker is **read-only** for this skill. Never post, comment, edit, create, link or transition anything in it. Never push, open a PR or merge without the user's go-ahead at Gate 3.

Before Station 1, read the project's convention docs (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`). They supply everything this skill leaves generic: the check command, test runners, branch naming, PR title rules, and the coding rules the build must follow. Where they say nothing, follow the codebase's dominant patterns.

Keep a running **ticket brief** in chat. Every station adds to it, and later stations read it instead of asking again:

```
## <KEY> brief
Readiness: groomed | partially groomed | not groomed (+ failing checks)
In scope:
Out of scope:
Assumptions (unconfirmed):
Open questions for the product owner:
Acceptance checks (testable):
Review tier:
```

## Heartbeat

Anything that may take more than about a minute (the check command, end-to-end runs, seeding, builds, review skills, subagents) gets a heartbeat:

- **Start.** One line: what is running, why, and a rough expected time.
- **Run it in the background** so the session stays responsive, and watch the output instead of blocking on it.
- **Beat.** About every 3 minutes, one line with the current stage and the latest concrete signal (test count, build step, last log line).
- **Stuck.** Slow is not hung. Call something stuck only on a concrete signal (an error, a dead process, a port that is not listening), say what you saw, and ask before killing or retrying it.
- **Finish.** One line with the result and what happens next.

## Station 1: Read

1. Run `git branch --show-current` and `pwd`.
2. Fetch the ticket with whatever tracker integration is available (an MCP server or CLI). If none is connected, ask the user to paste the ticket. Read **all** of it: description, acceptance criteria (often in custom fields), comments, linked issues, the parent epic and attachments. Look at mockups and screenshots; they often decide scope.
3. Read the project's domain docs and any architecture decision records that touch the area.
4. Search for prior work before designing anything:
   - `git log --all --oneline --grep=<KEY>`
   - `gh pr list --state all --search <KEY>`
   - sibling worktrees (`git worktree list`) and recently shipped features with similar names
5. Check the ticket's premise against the code. If it describes current behavior, confirm the code really behaves that way. A backwards premise changes the whole ticket.

Exit: you can say in two sentences what the ticket wants and what already exists.

## Station 2: Readiness triage

Score the ticket against this checklist. Each item is pass or fail with a one-line reason.

- **Outcome.** An observable result is stated (what a user sees or can do afterwards).
- **Acceptance criteria.** Present and testable, not "should work well".
- **Design.** UI work has a mockup or screenshot.
- **Who and where.** The user roles and the environments affected are clear.
- **Dependencies.** Any upstream or third-party system is named, with what happens when it is down or returns nothing.
- **Existing data.** It says whether already-saved content may change on deploy. The default is that it must not.
- **No duplicate.** No open or merged PR already covers it, and no sibling ticket overlaps.
- **Premise holds.** The Station 1 premise check passed.
- **Size.** It fits one PR. If not, propose a split.

Verdict: **groomed** if every item passes; **partially groomed** if 1–3 items fail, or Outcome or Acceptance criteria fails; **not groomed** if more fail than that, or the premise is wrong. Report the verdict and the failing items, then go straight to Station 3. A groomed ticket still gets its scope challenged.

## Station 3: Scope grill

Interview the user about scope, using the failing readiness items and the open scope edges as the agenda.

- **Scope comes first.** Open with in-or-out questions before any how questions: what this explicitly does not include (name the tempting adjacent work), which roles and environments, change to something existing or new, live dependency or stub and what the user sees when it fails, whether existing data can look different after deploy, and whether an end-to-end test is needed and which one happy path it proves.
- Ask one question at a time, each with your recommended answer.
- If the codebase can answer a question, explore it instead of asking.
- Write each resolved answer into the brief as you go.
- Anything only the product owner or a designer can answer goes into Open questions, unless the user answers it now.
- Stop when every in-or-out edge is resolved or parked, not when the questions run out.

## Gate 1: Scope sign-off (human)

Show the full brief, then ask:

- **Proceed** — build against the brief, with the assumptions listed as unconfirmed.
- **Park** — stop here; the user takes the open questions to the product owner.
- **Split** — the ticket is too big; propose which part this branch builds.

If the user proceeds on a ticket that is not groomed, the brief becomes the grooming. Build to the brief, not the ticket text, and list every assumption in the PR body later.

## Station 4: Plan

Draft a short implementation plan in chat: the files to touch, any schema or data migration, new API routes and pages, and the tests to write (the failing test first for bugs, unit edge cases, and the single end-to-end happy path). Name any project skills the build will use.

## Gate 2: Plan sign-off (human)

Get the user's OK on the plan before writing code. Scope was settled at Gate 1, so this only checks the approach.

## Station 5: Build

- Work on a branch named per the project's convention (default `<KEY>-short-slug`), in a separate worktree if another session holds this checkout. Check that any ports you start servers on are free.
- For a bug, write the test that reproduces it first and watch it fail.
- Follow the convention docs' coding rules.
- Stub upstream and third-party responses with fixtures. Handle the error, empty and unavailable states in code, and keep them visually distinct.
- Keep to the brief. Anything outside scope goes into a follow-ups list, not the diff.

## Station 6: Prove

- The project's check command must actually pass. Show the result. Do not claim done before it does.
- Run the end-to-end happy path. If a failure is a known local-only flake, say so and let CI decide instead of retrying in a loop.
- For UI changes, run `/visual-review` or take screenshots. For changes that touch saved data, show before and after for an existing record to confirm nothing moved.
- Tick off each acceptance check in the brief with how it was proved.

## Station 7: Review triage

Commit the build first (`/branch-review` refuses to run with modified tracked files). Then choose the review steps from the diff and the brief, report each with a one-line reason, and run them in this order:

| Step               | Run when                                                                                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/security-review` | The diff touches API routes, auth or session code, middleware, database access or migrations, sanitizers, file upload, secrets, or renders user-supplied content. |
| `/branch-review`   | Always. It runs the light pass and decides whether a deep review is worth offering.                                                                              |
| `/cross-review`    | A design trade-off was argued at Gate 1 or 2, a security-sensitive change would benefit from a different model's view, or the user asked for a second opinion.    |

- `/security-review` runs first, without asking, against `origin/<default>...HEAD`. Fix the real findings before running `/branch-review`.
- When `/branch-review` asks about a deep review versus cross-review, pass along any cross-review trigger from the table so the choice is made once. Never run either without the user's confirmation.
- Treat findings with judgment: fix real issues, and reject suggestions that conflict with a recorded decision, saying why.
- If any review step edited code, run the check command again.

## Gate 3: Ship (human)

Hand back:

- the final brief, with every acceptance check marked proved
- `git diff --stat`
- the review steps that ran and what they changed or flagged
- the follow-ups list and any unconfirmed assumptions
- a drafted PR body: a title in the project's required format (default `<type>: <plain summary> (<KEY>)` with a conventional-commit type), summary, scope and out of scope, assumptions, and how it was tested

Ask whether to commit the review edits as a separate commit, then push and open the PR. Never stage local secret files such as `.env.local`. Never merge.
