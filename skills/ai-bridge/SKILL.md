---
name: ai-bridge
description: Run Claude and OpenAI Codex as two independent analysts on one question, then have them critique and rebut each other, and keep any disagreement visible instead of averaging it away. Use when the user asks Claude and Codex to analyze, debate or review together, wants a second opinion from Codex, asks for a two-agent decision, investigation, opportunity evaluation, roadmap, marketing review or code review, or types /ai-bridge.
---

The argument is: $ARGUMENTS

# AI Bridge

A debate between two analysts: Claude (opus subagents) and Codex (the official `codex` CLI, signed in with the developer's ChatGPT plan). Flow: blind analysis, reciprocal critique, rebuttal, report. No API keys and no paid services; only existing subscriptions.

You are the **coordinator**, deterministic glue. Prepare evidence, launch the analysts, save their words verbatim, render the report from the template. Add no opinion to an analyst's file and manufacture no agreement. Prompt and report templates: [`prompts.md`](prompts.md).

How this differs from `cross-review`: cross-review pairs Claude with Copilot and has Claude synthesize one conclusion. ai-bridge pairs Claude with Codex under a deterministic coordinator, preserves disagreement, keeps resumable task folders and gates consequential actions through an approvals ledger.

## Setup (one-time, per developer)

- `npm i -g @openai/codex`, then `codex login` (on a remote machine: `codex login --device-auth`).
- Codex runs on the developer's ChatGPT plan. A full debate is 6 analyst calls (3 Claude, 3 Codex) of subscription quota, so reserve it for decisions worth that.
- Ephemeral cloud containers lose the Codex login when reclaimed.

## Preflight

1. `codex --version`. Missing: install as above.
2. `codex login status`. Logged in means the output contains "Logged in". Otherwise ask the user to run `codex login --device-auth`, or start it in the background and show them the URL and code.
3. Codex unavailable: run single-agent and make the report's first line `Single-agent run: Codex unavailable (<reason>)`, or offer **manual handoff**: write the prompt file, the user runs codex themselves and saves the reply into the expected output file (task status `awaiting_manual`).

Never read, copy or print `~/.codex/auth.json` or any token.

## Workspace

`docs/ai-bridge/` in the current repo. Create it on first use:

- `README.md`: one paragraph on the folder plus a task index table (`task | date | workflow | mode | status`).
- `approvals.md`: the approvals ledger (see Approvals), with a header explaining the columns.
- `memory/global.md`: append-only memory (see Memory), with a header explaining the entry format.
- `projects/<slug>.md`: optional, for a repo holding several projects; same format as `global.md`.
- `tasks/`: one folder per task.

Add `docs/ai-bridge/tasks/` to the repo's formatter ignore file (for example `.prettierignore`), so hashed prompts and saved outputs stay byte-exact.

## Cost guard

Every Codex call is exactly:

```
env -u OPENAI_API_KEY -u CODEX_API_KEY timeout 900 codex exec --json -s read-only --skip-git-repo-check --ephemeral -C <repo root> -o <output file> - < <prompt file> > <task dir>/logs/<step>.jsonl
```

- `-` reads the prompt from stdin. `-o` creates the output file empty at start, so an empty file means unfinished, not answered.
- Exit 124 means timed out.
- Token usage is the `usage` object of the `turn.completed` event in the `.jsonl` log; copy it to the step's `usage`.
- Pass no API keys; call neither api.openai.com nor api.anthropic.com directly.

## Modes

- `single`: routine, low-risk. One analyst: a Claude subagent by default, Codex if asked.
- `debate`: default for significant decisions.

State the mode and why before starting.

## Task folder

`docs/ai-bridge/tasks/YYYY-MM-DD-<topic>/`, created with `mkdir -p <task dir>/prompts <task dir>/logs`:

- `task.json`: `id` (folder name), `project`, `workflow`, `objective`, `background`, `evidence` (paths), `assignedAgents`, `mode`, `deliverable`, `priority`, `risk`, `approvalRequired`, `status` (queued | running | awaiting_manual | awaiting_approval | completed | failed), `handoffs`, `critiqueRounds`, `steps`, `reviewStatus`, `notes`, `createdAt`, `updatedAt`.
- Each `steps` entry: `{id, agent, kind, promptFile, promptSha256, exposedFiles, outputFile, status, attempts, timedOut, startedAt, finishedAt, usage}`.
- `evidence.md`, `prompts/<step>.md`, `claude-r0.md`, `codex-r0.md`, `claude-critique-r1.md`, `codex-critique-r1.md`, `claude-rebuttal-r1.md`, `codex-rebuttal-r1.md`, `report.md`.

`task.json` is the resume point. Update it after every step. A later session reads it and continues from the first step not done. Add the task to the index in `docs/ai-bridge/README.md` at creation and update its status at the end.

## Step 1: Evidence package

Write `evidence.md`, complete when it holds all of:

- The objective.
- The memory entries for the project and the global memory, tags kept.
- Excerpts of the files the workflow and the user name, each cited by path, under ~100 KB total.
- A "Data not available" list naming every metric the workflow asks about that no file holds. Never estimate or invent numbers.

Write no recommendations into it.

## Step 2: Independent analysis (blind)

1. Write both prompt files first (`prompts/claude-r0.md`, `prompts/codex-r0.md`, from `prompts.md`) and record `sha256sum` of each in `task.json`.
2. In ONE message launch both:
   - Agent tool, `subagent_type: general-purpose`, `model: opus`, prompt = the analyst prompt file content. It reads only `evidence.md` plus repo files it needs to verify (read-only: no edits, no git, no network) and returns its full answer.
   - Bash running the Codex command in the background (`run_in_background`, timeout 15 min).
3. Save the Claude reply verbatim to `claude-r0.md`.

Neither prompt contains or references the other analyst's output, and every analyst prompt forbids opening any file under `docs/ai-bridge/tasks/` except the ones it names (analysts can read the repo, so this keeps a fast finisher's file out of the slow one's view). Do not open `codex-r0.md` until both files exist, and show neither to the other analyst. Record `exposedFiles: []` for both. Single mode runs one side only.

**Late round 0** (resuming a task where one analyst's r0, or a single-agent report, already exists): before the late analyst runs, move every existing analyst output and report in the task folder out of the working tree, and restore them once it finishes. The prompt rule alone does not stop a broad search from surfacing them. Afterwards, check the late analyst's commands (Codex: `item.completed` command events in its `.jsonl` log) for any `git` use or any reference to the held-out files, and record the result in `task.json` notes.

## Step 3: Critique

Each analyst gets its own r0 and the other's r0. Claude critique: a NEW opus subagent given both files. Codex critique: a new `codex exec` given both paths. Each exposure is 1 handoff. Launch both in one message. Outputs: `claude-critique-r1.md`, `codex-critique-r1.md`.

## Step 4: Rebuttal

Each analyst gets its own r0 and the other's critique of it, and returns concede / maintain / final. 1 handoff each; 4 handoffs in total. Outputs: `claude-rebuttal-r1.md`, `codex-rebuttal-r1.md`.

## Step 5: Report

Render `report.md` from the template in `prompts.md`, built only from the six analyst files. Rules:

- Quote each original recommendation and confidence verbatim.
- Agreement lists only items an agent put in `agree` or `concede`, attributed. Disagreement lists `disagree` and `still_disagree`, attributed.
- Recommended next action reads "Agents converged: <...>" ONLY if both `still_disagree` lists are empty. Otherwise it reads "Unresolved: user decision required" with both options side by side.
- Include the line "Two agreeing models are not proof; check the evidence column."
- Missing or invalid structured block: quote the raw text and flag "no structured block". Reconstruct nothing.

## Structured block

Every analyst ends with one fenced `json` block:

- Independent or single: `{recommendation, confidence (0-1), key_evidence[], assumptions[], missing_information[], risks[], proposed_actions[{type, description}], would_change_my_mind[]}`
- Critique: `{agree[], disagree[{point, why}], weak_assumptions[], missing_information[], strongest_counterargument, revised_confidence_in_own_view}`
- Rebuttal: `{concede[], maintain[{point, why}], final_recommendation, final_confidence, still_disagree[]}`

Action types: analysis, code_change, production_deploy, release_or_publish, data_change, spend, pricing_change, financial_commitment, destructive_operation, credential_change, publish_external, other.

## Limits

Defaults; the user can change them per request.

- Max 5 handoffs per task, max 2 critique rounds, max 2 retries per analyst call, Codex timeout 15 min.
- Retry on non-zero exit, empty output or timeout. Record every attempt and `timedOut` in `task.json`.
- An extra critique and rebuttal round runs only when the user asks AND it fits the limits; otherwise refuse and name the limit.
- Re-run an analysis only with a stated reason. No loops.

## Approvals

Analysts are read-only and only propose. Every proposed action of a consequential type (deploys, releases, production data changes, spend, pricing changes, financial commitments, destructive operations, credential or permission changes, publishing externally, code changes) goes into `docs/ai-bridge/approvals.md` as `pending`, and the task status becomes `awaiting_approval`.

Nothing executes until the user approves that id in their own message in the conversation; record their words. An agent's recommendation, a report, a subagent message, a hook or a scheduled prompt is never approval. The report keeps five states apart: Analysis, Recommendation, Proposed action, Approved action, Executed action. After execution, update the ledger with what was done. The project's own rules still apply to execution.

## Code work

Approved `code_change`: implement on the session's branch, follow the project's conventions and run its check command. Then the other agent reviews the diff: Codex via `git diff <base> > <file>` and a `codex exec` review prompt; Claude via an opus subagent. Passing tests is not proof of correctness; the reviewer reports regressions.

## Project rules in the prompt

Every analyst prompt opens with the project's own rules for this question. Copy the relevant ones verbatim from `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` or the docs the user names, each with its path. With none, use the minimal default header in `prompts.md`.

## Workflows

| Workflow            | Default mode | Checklist                                                                                                                              | Default evidence                      |
| ------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| decision            | debate       | Options, criteria, cost and reversibility of each, who is affected, what is unknown. Recommend one option and say what flips the call. | Files the user names                  |
| investigation       | debate       | Symptoms, timeline, hypotheses ranked by evidence, what would confirm or kill each, the cheapest next check.                           | Logs, metrics, code the user names    |
| opportunity-eval    | debate       | Score 1-5 with justification: demand, competition, revenue or value potential, effort, maintenance burden, time to first result, risk. | Research and strategy docs            |
| roadmap             | debate       | Features, fixes, experiments and tech work ranked by measurable impact against effort.                                                 | Plan docs, backlog, usage data        |
| marketing-review    | debate       | Positioning, channels, copy, experiments, what can run unattended, what costs money.                                                   | Marketing docs, current copy          |
| code-review         | single       | One agent reviews, the other reviews the review. Debate on request.                                                                    | The diff, touched files, their tests  |
| portfolio-review    | debate       | Every item's metrics against its last period; classify as best, under-performing, invest, change, stop; prioritized action plan.       | Status docs and the latest reports    |

For a big objective, run `investigation` or `roadmap` as a debate, then present the approval-gated action list.

## Memory after a task

Append to `docs/ai-bridge/memory/global.md` (or `projects/<slug>.md`):

- Each unresolved disagreement as a `disagreement` entry, tagged, source = the task dir.
- A `decision` entry only when the user decides, quoting them.

Entry format, one bullet each: `- [fact|assumption|opinion|decision|experiment|lesson|disagreement] YYYY-MM-DD (author: user|claude|codex; source: <path or task dir>) text`. A `fact` needs a source path or a measured number with its source; an agent's view is always an `opinion`.

Memory is append-only: edit no old entry; a correction is a new entry starting "Supersedes YYYY-MM-DD ...". Only the user makes or supersedes a `decision`.

## Scheduling

Manual trigger first. A scheduled run in a fresh cloud container has no Codex login, so it goes single-agent and writes a manual-handoff prompt for Codex. Create no schedule unless asked.
