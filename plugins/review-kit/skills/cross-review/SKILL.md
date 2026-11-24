---
name: cross-review
description: Ask genuinely DIFFERENT AI models (Claude + GitHub Copilot) the same thing, have them answer INDEPENDENTLY, then CROSS-EXAMINE each other (challenge, vote, adjust), and Claude synthesizes one confidence-graded conclusion. Two modes, auto-detected — review mode for a code change (diff/PR/files), consult mode for anything else (a plan, a design decision, an architecture trade-off, a general question, "which approach is right"). The value is model diversity plus mutual checking — what multiple independent models confirm is high-confidence; what one retracts under scrutiny gets filtered out; where they genuinely disagree is flagged for a human call. Use whenever the user types `/cross-review`, asks for a "cross-model review", "multi-model review", "ask the other models", "what does Copilot think", "get a second opinion from the other models", "have the models check each other", or wants multiple different models to weigh in on a plan/decision/question and reach a conclusion. Copilot is pinned to a non-Anthropic model so the second opinion is genuinely independent. Distinct from `/branch-review --deep` (many CLAUDE sub-agents across review angles) and `/deep-research` (web sources): reach for cross-review specifically when you want DIFFERENT models that audit each other. Pass a PR number or file paths (review), a question or plan (consult), or omit to review the current branch's diff vs the repo's default branch.
---

The argument is: $ARGUMENTS

# Cross-Review (autonomous, multi-model, cross-examined)

`/branch-review --deep` fans out many **Claude** sub-agents — depth from one model. `/cross-review` is the orthogonal axis: ask genuinely **different models** (Claude and GitHub Copilot) the same thing, have them **answer independently and then audit each other**, and report only what survives. An answer two independent models reach is far more trustworthy than any single model's claim; a point one model quietly retracts when challenged was probably wrong; where they genuinely diverge is exactly the judgment call a human should own. That mutual checking is the whole point — don't shortcut it into a single round.

This works on **two kinds of input**:

- **Review mode** — a code change (the current branch's diff, a PR, or specific files). Output: a severity-graded findings report.
- **Consult mode** — anything else: a plan, a design decision, an architecture or library trade-off, a debugging hypothesis, a general question. Output: a synthesized conclusion with consensus, disagreements, and a recommendation.

This runs **autonomously**: once scope/mode is confirmed, drive all rounds without stopping to ask the user, and present only the final synthesized report.

**Cost — set expectations.** This is a deliberate, slow, token-heavy process. Each run makes 2 Copilot calls (Round 1 and Round 2), each taking 30–90s and capped in AI credits (see "Usage caps"). The first run in a checkout also probes for a usable model: up to four small calls, one per candidate, until one answers. The probe runs again only if the cached model stops working. On top of that come Claude's own passes. The Copilot calls come out of the developer's Copilot plan, so don't run this as a habit on every push. It's worth it for security-sensitive, subtle, or high-stakes things — a tricky review, an expensive-to-reverse decision, a plan you want stress-tested by other minds. It's overkill for a typo fix or a quick factual lookup. For broad single-model review depth use `/branch-review --deep`; for web-sourced research use `/deep-research`. If the user wanted something quick, say so and offer the cheaper option before launching.

## Team setup (one-time, per developer)

The external model is a CLI the developer installs and authenticates themselves — it is not bundled with the repo. On macOS (Homebrew):

- **GitHub Copilot CLI**: `brew install --cask copilot-cli` then `copilot login` (sign in with your GitHub account). Verify the binary with `copilot --version`.

(Not on macOS? The Copilot CLI also ships via npm — see the GitHub Copilot CLI docs. The skill only needs the `copilot` binary on `PATH`, however it got there.)

For Copilot to run **autonomously** (no per-call approval prompt), each developer merges this Bash permission rule into the `permissions.allow` array of their **own** `.claude/settings.local.json` (gitignored — they are deliberately NOT committed, because auto-approving an external agent is a personal, high-trust choice each person must make explicitly). The full file shape, if you're creating it from scratch:

```json
{
  "permissions": {
    "allow": [
      "Bash(copilot --allow-all-tools --available-tools=view,grep,glob,report_intent -s -p:*)"
    ]
  }
}
```

Without this rule the skill still works — the Copilot calls just prompt for approval (or, under the auto-mode classifier, may be blocked until the rule exists). The exact flags in the Copilot rule are a read-only whitelist (see "The exact model invocations"); don't loosen them.

To use this skill across many repos (e.g. installed from a personal skills repo), put the same rule in `~/.claude/settings.json` instead — per-repo `.claude/settings.local.json` rules only apply in that repo. Either way, a **human** must add it: the auto-mode classifier blocks Claude from self-granting an autonomous-external-agent rule, even when told "add whatever rule you need".

## Step 0: Pick the mode and detect available models

**Mode** — decide from what the user is actually asking, before doing anything else (this gates which pipeline runs, so get it right before snapshotting anything):

- **Review mode** if the argument is a PR number, file paths, the word "review" / "this branch" / "this PR", or is **empty** (default: review the current branch vs the repo's default branch — backward compatible).
- **Consult mode** if the argument (or the surrounding request) is a question, a plan, a decision, a trade-off, or otherwise prose asking for an opinion/conclusion rather than a code review. When ambiguous, ask the user one short question; never silently run the wrong pipeline.

**Models** — a cross-model run needs Claude plus **Copilot**. Detect Copilot:

```bash
command -v copilot >/dev/null && echo "copilot present"
```

- **Copilot** can't be auth-checked without running it; treat it as available if the binary exists. If the model probe or any Copilot call returns empty or errors, treat Copilot as unavailable (next bullet). The one exception is a call stopped by its usage cap that still returned usable output (see "Usage caps").
- If Copilot is unavailable (only Claude is left), stop and tell the user plainly — a one-model "cross-review" is a contradiction. Point them at the **Team setup** section (`brew install --cask copilot-cli && copilot login`), or offer to run `/branch-review --deep` (review mode) / a plain Claude answer (consult mode) instead. **Never** produce a single-model report labeled "cross-review".
- Be specific about _why_ Copilot is missing so the user knows what to fix: "Copilot isn't installed" (binary absent) vs "Copilot is installed but its call returned nothing — run `copilot login`". Don't collapse these into a generic "unavailable".

**Pin Copilot to a non-Anthropic model.** Copilot's default model can be an Anthropic one (observed: an unpinned call answered as Claude Haiku 4.5), which would make this Claude checking Claude and defeat the purpose. "The exact model invocations" below picks a cheap but full-size non-Anthropic model this account can actually use (or `CROSS_REVIEW_MODEL` if set), and the run stops if there is none.

Record the participating model set with the pinned model (e.g. "Claude + Copilot (gpt-6.1-sol)") — it goes in the report header, and every tally below is relative to _how many models actually examined the thing_.

## The exact model invocations (both modes)

Use these **verbatim** — Claude must call `copilot` **directly** (not via a wrapper script). The read-only safety is enforced by the permission-rule _prefix_ (`copilot --allow-all-tools --available-tools=view,grep,glob,report_intent -s -p:*`), so the flags must appear exactly as written and before the prompt. `--model "$CROSS_MODEL"` goes **after** the prompt argument so the prefix still matches (verified: Copilot parses it there and rejects unknown models). A wrapper script would run the CLI as a child process, bypassing that guarantee — don't.

**Every Bash call is a fresh shell.** Variables and functions do not carry from one call to the next, so nothing below relies on that. Create the workspace first and note the absolute path it prints; wherever a block starts with `WS="<absolute workspace path>"`, put that literal path in. The watchdog helper lives in `$WS/helpers.sh`, which each call sources, and the chosen model is saved to `$WS/cross-model.txt` and read back. Other values computed in one call and needed in a later one (`DEF`, `MB`) are saved the same way under `$WS`, and inline commands that mention `$WS`, `$MB` or `$DEF` follow the same rule: read the value back or substitute the literal.

Create the shared workspace once, in either mode:

```bash
WS="$(git rev-parse --show-toplevel)/.claude/.cross-review/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$WS" && echo "$WS"
```

Make sure `.claude/.cross-review/` is gitignored in the host repo (add it if it isn't). The workspace is per-run scratch — a snapshot of the diff plus every prompt and every model's raw output — so it is never committed, and it grows with each run. Prune old timestamped directories when it gets large.

**Always wrap each call in a hard timeout.** These CLIs can hang indefinitely — the tell is **no output**, not elapsed time (observed: a model run producing nothing at all on a 149-line diff, still silent after 8 min, requiring a manual kill). Duration alone can't separate a hang from a slow-but-working run, which is why `MODEL_TIMEOUT` below is set above the healthy ceiling rather than at it. Don't rely on `timeout`/`gtimeout` — they're absent on stock macOS. Use this portable watchdog, and if the output file is empty after it returns, **stop** per Step 0 (say what failed — never wait forever or fake a verdict):

```bash
WS="<absolute workspace path>"
cat > "$WS/helpers.sh" <<'EOF'
kill_tree() { local p c; for p in "$@"; do for c in $(pgrep -P "$p" 2>/dev/null); do kill_tree "$c"; done; kill -9 "$p" 2>/dev/null; done; }
run_with_timeout() {
  local secs="${@:1:1}"; shift
  "$@" & local cpid=$!
  ( exec >/dev/null 2>&1; sleep "$secs"; kill_tree "$cpid" ) & local wpid=$!
  wait "$cpid" 2>/dev/null; local rc=$?
  kill_tree "$wpid"; return $rc
}
MODEL_TIMEOUT=300   # healthy runs take 30–90s; the headroom still ends a silent hang
EOF
```

**Never write a numbered positional parameter (a dollar sign followed by a digit) anywhere in this file.** Claude Code fills those in with the words of the `/cross-review` arguments when it loads the skill. For example, `/cross-review 744 with …` turned the watchdog's first-argument reference into the literal word `"with"`. The helpers above use `"$@"` and `"${@:1:1}"` for that reason.

**Pick the model once, and remember it.** Every Copilot call spends the developer's Copilot usage (AI credits, or premium requests × the model's multiplier on legacy billing), and per-token prices differ several-fold between models, so the default is the **cheapest full-size** non-Anthropic model. Don't infer price from the name or age: measured on one account, `gpt-5.5` billed at 7.5× and 500/3,000 credits per 1M input/output tokens, while the newer `gpt-6.1-sol` billed at 1.0× and 200/1,000. The `/model` picker in interactive `copilot` shows current prices, and `~/.copilot/session-store.db` (`assistant_usage_events`) records what each call actually cost. The `*-luna` models are far cheaper still but a smaller tier, so they aren't the default. A developer who wants a different model sets `CROSS_REVIEW_MODEL`. Never use a `claude-*` model.

The choice is cached in `.claude/.cross-review/model` (gitignored), so the probe below runs **only** when there is no cached model or the cached one fails a real call. Don't probe on every run: each probe is a full Copilot request. Being listed in `copilot help config` does not mean this account can use a model, which is why a new model is probed with a tiny real call before it's cached.

```bash
WS="<absolute workspace path>"; . "$WS/helpers.sh"
CACHE="$(git rev-parse --show-toplevel)/.claude/.cross-review/model"
CROSS_MODEL="${CROSS_REVIEW_MODEL:-$(cat "$CACHE" 2>/dev/null)}"
case "$CROSS_MODEL" in claude-*) CROSS_MODEL="" ;; esac
if [ -z "$CROSS_MODEL" ]; then
  for m in gpt-6.1-sol gpt-6-sol gpt-5.6-terra grok-4.7 kimi-k3; do
    reply="$(run_with_timeout 60 copilot --allow-all-tools --available-tools=view,grep,glob,report_intent -s -p "Reply with the single word: ok" --model "$m" --reasoning-effort low --context default --max-ai-credits 30 </dev/null 2>&1)"; rc=$?
    reply="$(printf '%s' "$reply" | tr -d '[:space:]')"
    if [ "$rc" -eq 0 ] && printf '%s' "$reply" | grep -qiE '^ok[.!]?$'; then CROSS_MODEL="$m"; break; fi
    echo "skipped $m (exit $rc$([ "$rc" -eq 137 ] && echo ', timed out')): ${reply:0:80}" >&2
  done
  [ -n "$CROSS_MODEL" ] && printf '%s' "$CROSS_MODEL" > "$CACHE"
fi
echo "$CROSS_MODEL" > "$WS/cross-model.txt"; echo "selected: ${CROSS_MODEL:-none}"
```

If `CROSS_MODEL` is empty, treat Copilot as unavailable and stop per Step 0, saying which candidates were skipped and why (not available on this account vs timed out). A healthy probe takes a few seconds and a hung one is cut off at 60s, using the same flags as the real call so the permission rule covers it; list any skipped models in the final verdict. If the cached model's Round-1 call comes back with a model/availability error, delete `.claude/.cross-review/model` and rerun the selection once. Don't retry any further than that. When `copilot help config` lists newer models, re-order the candidate list by actual per-token price, cheapest full-size model first.

The **Copilot** call (whitelisted to read/search tools only — `view,grep,glob,report_intent`, where `report_intent` just declares intent and `view/grep/glob` are read-only, so it physically cannot write files or run shell; `-s` gives response-only output):

```bash
WS="<absolute workspace path>"; . "$WS/helpers.sh"; CROSS_MODEL="$(cat "$WS/cross-model.txt")"
run_with_timeout "$MODEL_TIMEOUT" copilot --allow-all-tools --available-tools=view,grep,glob,report_intent -s -p "$(cat "$WS/<prompt>.txt")" --model "$CROSS_MODEL" --reasoning-effort <EFFORT> --context default --max-ai-credits <CREDIT_CAP> > "$WS/copilot-<round>.txt" 2>&1
```

**Usage caps — always pass these.** Each `view`/`grep` Copilot runs is another billed model turn that re-sends the growing context, so an open-ended "read the surrounding source" can turn into dozens of turns. The caps bound that:

- Round 1: `--reasoning-effort medium --max-ai-credits 150`.
- Round 2: `--reasoning-effort low --max-ai-credits 60`. This round only judges an inline list, so it rarely needs to read anything.
- `--context default` keeps Copilot off the pricier long-context tier.
- If a call stops at the cap, `copilot-<round>.txt` ends early or holds a limit message. Keep the output only if what came back still has the round's format: a numbered findings list or `NONE` in review Round 1, `<n>: <verdict> | …` lines in review Round 2, a recommendation in consult Round 1, or claim verdict lines in consult Round 2. Any finding or claim that has no Copilot verdict counts as not examined by Copilot. Note "Copilot hit its usage cap" in the verdict. If nothing usable came back, treat it as a failed call and stop per Step 0. Don't rerun with a higher cap unless the user asks.

`run_with_timeout` is **synchronous** (it `wait`s on its child), so run the Copilot call as a background Bash command (`run_in_background`) and do Claude's own pass for the same round while it runs, then read the output file when it returns.

Copilot can read files in the repo for context; read its output file once the call returns — always under the watchdog above. Write each prompt to a `$WS/*.txt` file first so it's identical across models and reusable.

---

# Review mode

Use when the input is a code change.

## R-1: Determine scope

Confirm you're in a git repo (`git rev-parse --is-inside-work-tree`); if not, tell the user and stop — do not `git init`.

Detect the repo's default branch once — every `main` below means this value:

```bash
WS="<absolute workspace path>"
DEF="$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||')"; DEF="${DEF:-main}"
echo "$DEF" > "$WS/default-branch.txt"; echo "$DEF"
```

- **No argument**: review the current branch's diff vs `$DEF`. Get the branch (`git rev-parse --abbrev-ref HEAD`); if it's `$DEF`, ask which branch they meant.
- **PR number** (e.g. `412`): `gh pr view <N> --json number,title,headRefName,baseRefName,url` to confirm; if `gh auth status` fails, stop. Diff via `gh pr diff <N>`.
- **File paths**: review just those paths — the diff itself is snapshotted in R-2.

Remember a human-readable `SCOPE_LABEL` for the report.

## R-2: Snapshot the diff

One diff, so every model reviews identical input.

Both local-diff modes below compare against the merge-base, so resolve it once:

```bash
WS="<absolute workspace path>"; DEF="$(cat "$WS/default-branch.txt")"
MB="$(git merge-base "$DEF" HEAD 2>/dev/null || git merge-base "origin/$DEF" HEAD 2>/dev/null)"
[ -n "$MB" ] || { echo "no merge-base with $DEF" >&2; exit 1; }   # tell the user and stop — do not git fetch
echo "$MB" > "$WS/merge-base.txt"
```

- **Branch**: review the **working tree** (committed + uncommitted + untracked) vs the merge-base, so a local pre-commit run reviews what the developer actually has — not just what's committed. Untracked files don't appear in `git diff` until git knows about them, so tag them intent-to-add, diff, then unwind behind a `trap` so the index is restored even if the diff errors or the run is interrupted (non-destructive — HEAD/working-tree/index are never persistently changed):
  ```bash
  WS="<absolute workspace path>"; MB="$(cat "$WS/merge-base.txt")"
  git ls-files --others --exclude-standard -z > "$WS/untracked.0"                    # NUL-delimited so paths with spaces survive
  trap '[ -s "$WS/untracked.0" ] && xargs -0 git reset -q -- < "$WS/untracked.0"' EXIT
  [ -s "$WS/untracked.0" ] && xargs -0 git add -N -- < "$WS/untracked.0"
  git diff "$MB" > "$WS/diff.patch"
  ```
- **PR**: `gh pr diff <N> > "$WS/diff.patch"` (PR mode reads the PR's committed diff via `gh` and never touches the local repo). Copilot's `view`/`grep` still read the **local checkout**, though. If that isn't the PR's head branch, say so in both prompts. Before pooling, check any "file/symbol doesn't exist" finding against the PR head (`gh api repos/<owner>/<repo>/contents/<path>?ref=<headRefName>`). Observed: Copilot flagged a missing import as high severity on a green PR because the file existed only on the PR branch.
- **Files**: `git diff "$MB" -- <paths> > "$WS/diff.patch"` (working tree vs merge-base for just those paths; `git add -N` them first if any are untracked).

**Strip secrets before any model sees the diff.** The external CLIs are separate processes / remote services — treat the diff as leaving Claude's boundary. If any changed path matches `.env*`, `*.pem`, `*.key`, `*credentials*`, `*secret*`, or `id_rsa*`, remove it from `diff.patch` and surface the exclusion in the final report.

If the diff is empty, stop. If it's enormous (>4000 lines), warn the user and ask before proceeding — every model ingests the whole thing twice.

## R-3 — Round 1: Independent review

Each model reviews `diff.patch` **without seeing the others' output**. Write this prompt to `$WS/round1-prompt.txt`:

```
You are reviewing a code change in <one-line project description — name, stack, package manager; derive it from the repo's README/CLAUDE.md>. <DIFF SOURCE> Read surrounding source only where a finding depends on it, and stop reading once you have enough. Scope: <SCOPE_LABEL>.

Report REAL issues only: correctness bugs, security (path traversal, auth/tenant isolation, secrets or internal errors leaking to responses), data-loss/overwrite risks, broken invariants. Read beyond the changed lines to catch blast-radius bugs.

Output ONLY a numbered list. For each finding: `path:line` — severity (high|med|low) — one-sentence why. No style/lint nits, no praise, no summary. If nothing serious, output exactly "NONE".

DIFF:
<paste diff.patch, or omit this section for a large diff>
```

**Inline the diff only when it's small.** The prompt reaches Copilot as one command-line argument, and a large one makes `copilot` fail to start ("argument list too long"; Linux caps one argument at 128KB). Check the size first with `wc -c < "$WS/diff.patch"`:

- **Under 100,000 bytes:** replace `<DIFF SOURCE>` with `The diff is inline below.` and paste `diff.patch` into the DIFF section. This saves Copilot a file read.
- **100,000 bytes or more:** replace `<DIFF SOURCE>` with `Read the diff at <ABS PATH to diff.patch>.` and leave out the DIFF section.

- Run Copilot → `$WS/copilot-r1.txt` in the background while Claude does its own pass.
- Claude performs the **same** review independently → `$WS/claude-r1.txt`. Read surrounding source; don't judge from hunks alone.

Then build `$WS/pooled.md`: a single deduplicated, **renumbered** list of every Round-1 finding from all models, each tagged with which model(s) raised it. Match findings by `path:line` + meaning (models phrase the same bug differently — use judgment, not string equality).

## R-4 — Round 2: Cross-examination

Now each model audits the **pooled** findings — including the others'. Write `$WS/round2-prompt.txt`, embedding the pooled list **inline**:

```
Below is a numbered list of code-review findings about the same change you reviewed (diff at <ABS PATH>). Some are yours, some from other reviewers. For EACH finding, judge it independently. Re-read code only for a finding you can't judge from the diff.

Output one line per finding number, exactly:
<n>: <REAL|FALSE_POSITIVE|UNSURE> | severity=<high|med|low> | <one-sentence reason>

Be skeptical: if a finding misreads the code, doesn't actually reproduce, or is out of scope, say FALSE_POSITIVE. If real but mis-rated, give the severity you'd assign. Judge on impact, not just likelihood. No other output.

FINDINGS:
<paste pooled list>
```

- Run Copilot → `$WS/copilot-r2.txt` in the background.
- Claude cross-examines the same pooled list → `$WS/claude-r2.txt`, applying genuine skepticism to its _own_ Round-1 findings too.

## R-5 — Round 3: Synthesis

Claude (orchestrator) tallies the Round-2 verdicts per finding, **relative to how many models examined it**:

- **Confirmed** — every examining model voted REAL. High confidence.
- **Disputed** — split / UNSURE-heavy. Worth a human look.
- **Rejected** — every examining model voted FALSE_POSITIVE. List briefly with the refuting reason (this is signal: a finding that didn't survive cross-examination).

For severity, reconcile the votes rather than averaging blindly; when models split on likelihood vs impact, let **impact** win (a tenant-isolation breach is serious even if rare).

Present this final report and nothing else — no raw per-model output, no running commentary (R-6 below adds one closing question after it, and that's the only thing that follows):

```
# Cross-review: <SCOPE_LABEL>
Models: <participating set>  ·  2 rounds (independent → cross-examined)

## Confirmed findings  (every examiner agrees it's real)
- `path:line` — **severity** — what it is — _confirmed by Claude + Copilot_

## Disputed  (models disagree — needs a human call)
| `path:line` | desc | Claude | Copilot | note |

## Rejected on cross-examination  (raised in R1, refuted in R2)
- `path:line` — raised by X — refuted because <reason>

## Verdict
1–3 sentences: overall risk, what to fix before merge, plus anything excluded (e.g. secret files stripped from the diff) and any candidate models the picker skipped.
```

## R-6: Offer to post the confirmed findings to the PR

After presenting the report — and **only** when the scope was a PR (or a branch with an open PR you can identify) — ask the user, in one line, whether they want the **confirmed** findings posted to that PR as inline review comments. Ask; don't post unprompted. Findings living only in terminal scrollback are easy to lose, and inline comments put each one on the line it's about where the PR author will actually see it.

If they say yes:

- **Confirmed findings only, one comment each.** Disputed and rejected findings do **not** get inline comments — summarize the disputed ones in the review body so the author knows a split existed and why it wasn't asserted. Never post a rejected finding.
- **One review, not N standalone comments.** POST all comments in a single review with `"event": "COMMENT"` (never `REQUEST_CHANGES` — these are model findings, not a human's verdict on the PR).
- **Post it with `gh api`.** Build the payload as a JSON file (a heredoc'd script in whatever runtime the repo actually requires is the sane way to get multi-paragraph markdown bodies through without quoting pain — check the README's prerequisites rather than assuming: a Bun project often has no `node` binary at all, so it is `bun -e` there and `node -e` in a Node project. Don't reach for `python3`, which a stock Mac doesn't ship.) and post it:
  ```bash
  WS="<absolute workspace path>"
  gh api --method POST repos/<owner>/<repo>/pulls/<N>/reviews --input "$WS/review.json" \
    --jq '{id, state, html_url}'
  ```
  The payload is `{"body": "<review summary>", "event": "COMMENT", "comments": [ … ]}`, where each comment is `{path, line, side, body}` plus `start_line` + `start_side` for a multi-line anchor. `side` is `"RIGHT"` for a line the PR adds or keeps — that covers almost every finding. Use `"LEFT"` only when the finding is about a line the PR _removed_ (a deleted guard, a dropped check) and the hunk is a pure deletion with no RIGHT line to point at; where a nearby RIGHT context line exists, prefer it and say in the body what was removed.
- **Anchors must exist in the PR diff**, or the whole POST 422s. Anything the diff renders is anchorable — the changed lines _and_ the unchanged context lines GitHub shows around them — so for a wholly new file that's every line, and for an edited file it's each hunk plus its context. Only code outside every hunk has no anchor, so for a finding about that, either move the comment to the nearest diff-visible line and say what it's really about, or leave it in the report only. Keep the line numbers in file-line space (not diff-line space); overlapping ranges between two comments are fine.
- **Write each comment so it stands alone.** Lead with `**<severity> — <one-line claim>**` and the cross-model verdict (`cross-review: confirmed by Claude + Copilot`), then the mechanism, then the concrete fix. Cite the sibling file/line that shows the codebase's own precedent when one exists — that's what makes a finding land instead of reading as a model opinion.
- **Label the provenance.** Close the review body with a line saying it came from `/cross-review`, that the comments are model findings rather than a human review, and which ones deserve a human call.
- **Verify it landed.** A 200 on the review POST doesn't prove the comments attached. Check:
  ```bash
  gh api "repos/<owner>/<repo>/pulls/<N>/comments?per_page=100" \
    --jq '.[] | select(.pull_request_review_id==<id>) | "\(.path):\(.start_line // .line)-\(.line)"'
  ```
  Report the review URL and the count you confirmed.

If they say no, stop — the report is the deliverable. Don't offer again.

---

# Consult mode

Use when the input is a plan, a decision, a trade-off, or any question — not a code change. Same three-round shape (independent → cross-examined → synthesized), but the artifact is the question and the deliverable is a reasoned conclusion, not a findings list.

## C-1: Capture the question and context

Write the exact thing being asked to `$WS/question.txt` so every model gets identical input. Make it self-contained:

- State the question / plan / decision precisely. If the user pasted a plan or it lives in the conversation, include its full text.
- If it references repo files, a plan doc, or a GitHub issue, **include absolute paths** (and fetch issue/PR bodies into `$WS/` as files) so Copilot can read the same material read-only. Don't assume they share Claude's conversation context — they don't.
- State what a good answer looks like (a recommendation? a list of risks? a yes/no with reasoning?) so the models' outputs are comparable.

**Strip secrets from any context you pull in.** Consult context can include files too — apply the same rule as review mode: never write `.env*`, `*.pem`, `*.key`, `*credentials*`, `*secret*`, or `id_rsa*` contents into `$WS/` or a prompt. Reference them by description instead and note the exclusion.

Remember a short `TOPIC` label for the report header.

## C-2 — Round 1: Independent answer

Each model answers **without seeing the others**. Write `$WS/round1-prompt.txt`:

```
You are advising on the following (context: <one-line project description from the repo's README/CLAUDE.md>, unless stated otherwise). Read any referenced files for context.

QUESTION / PLAN / DECISION:
<paste question.txt>

Give your honest, independent answer. Be concrete and decisive: state your recommendation, the key reasons, the main risks or trade-offs, and anything you'd want verified before acting. Flag assumptions you're making. If you think the premise is wrong, say so. Be concise — no preamble, no restating the question.
```

- Run Copilot → `$WS/copilot-r1.txt` in the background while Claude answers independently.
- Claude answers the **same** question independently → `$WS/claude-r1.txt`. Treat this as a genuine first-principles answer, not a summary of what you expect the others to say.

Then build `$WS/pooled.md`: each model's answer, clearly labeled, plus a short Claude-authored list of the **distinct claims / recommendations / risks** that came up (so Round 2 can challenge specific points, not just whole essays).

## C-3 — Round 2: Cross-examination

Each model now sees the pooled answers and challenges them. Write `$WS/round2-prompt.txt`, embedding the pooled answers + claim list **inline**:

```
Below are independent answers from several advisors to the same question, plus a list of the distinct claims/recommendations they made. Some are yours. Judge them critically — read referenced files if needed.

For the claim list, output one line per claim number:
<n>: <AGREE|DISAGREE|UNSURE> | <one-sentence reason — name the flaw if you disagree>

Then, in 3-5 sentences: which overall answer is strongest and why, what every answer missed, and your final recommendation now that you've seen the others. Change your mind if they convinced you; hold your ground with a reason if they didn't. No flattery.

ANSWERS AND CLAIMS:
<paste pooled answers + numbered claim list>
```

- Run Copilot → `$WS/copilot-r2.txt` in the background.
- Claude cross-examines the same pooled material → `$WS/claude-r2.txt`, applying the **same skepticism to its own Round-1 answer** as to the others'. Note where the others changed your mind.

## C-4 — Round 3: Synthesis

Claude (orchestrator) reconciles the Round-2 verdicts into one conclusion. Guard against the failure mode: **the synthesis is not "Claude's Round-1 answer with the others as garnish."** Weight by what survived cross-examination — a claim only Claude made and the others disputed is not consensus; a point the others made that changed Claude's mind belongs in the conclusion.

Present **only** this final report:

```
# Cross-consult: <TOPIC>
Models: <participating set>  ·  2 rounds (independent → cross-examined)

## Consensus  (what the models independently agree on — high confidence)
- <point> — _both models_

## Disagreements  (genuine divergence — your call)
| claim | Claude | Copilot | the crux of the disagreement |

## Rejected on cross-examination  (raised in R1, refuted in R2)
- <claim> — raised by X — refuted because <reason>

## Recommendation
The synthesized conclusion (2-5 sentences): what to do, the confidence level, and what to verify before acting. If the models couldn't converge, say so plainly and hand the judgment call to the user rather than papering over it.

## Dissenting view worth keeping
Any minority position that's weak on consensus but worth not losing (omit if none).
```

---

## Notes (both modes)

- **Run quietly.** A one-line "Round 1: Claude + Copilot reviewing…" is fine; don't dump raw per-model output mid-flight. The synthesized report is the deliverable.
- **Honesty over coverage.** If Copilot is unavailable, errors, or returns garbage at any point, stop per Step 0 — never fabricate a model's verdict. A call cut short by its usage cap is kept only under the rule in "Usage caps", and the report says it was capped.
- **Consensus is the product, not Claude's opinion.** In both modes the value is the cross-check: agreement = high confidence, disagreement = flag for a human. Don't collapse it into a single model's view — including Claude's own.
- **The read-only guarantee is structural.** Copilot is whitelisted to `view,grep,glob,report_intent` only (no `bash`/`create`/`edit`/`sql` tools exist in its session). It is gated by permission-rule prefixes — if you change the flags, the calls will start prompting, which is the intended tripwire. Don't "fix" that by widening the rules.
- **The usage caps are deliberate.** `--reasoning-effort`, `--context default`, `--max-ai-credits` and the cheap default model keep a run from draining the developer's Copilot plan. Don't drop them or switch the default to a pricier model. A developer who wants more opts in with `CROSS_REVIEW_MODEL`.
