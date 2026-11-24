---
name: review-pr-comments
description: Review and address unresolved PR review comments. Pass the PR number as an argument, or omit to auto-detect from the current branch.
---

Review and address unresolved PR review comments. Pass the PR number as an argument, or omit to auto-detect from the current branch.

The argument is: $ARGUMENTS

# Review PR Comments

Review unresolved PR review comments, assess their validity, plan fixes, implement them one by one with commits, push, and resolve the threads on GitHub.

## Step 0: Confirm the working directory

Before running any other commands, verify the current working directory is the project the user is in — not a parent like `_Repositories`. Run `git rev-parse --show-toplevel` and confirm it points at the project root the user invoked this skill from. If the cwd is a parent that contains multiple repos, stop and ask the user which repo to target rather than guessing. All subsequent `gh` and `git` commands must run from inside the project root.

## Step 1: Identify the PR

Determine the PR number. If the user provides one via `$ARGUMENTS`, use it. Otherwise, auto-detect from the current branch:

```bash
gh pr view --json number --jq '.number'
```

Also capture the repo owner, name, and PR node ID:

```bash
gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"'
gh pr view PR_NUMBER --json id --jq '.id'
```

## Step 2: Fetch unresolved review threads

Use this GraphQL query to get all unresolved review threads with their comments:

```bash
gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          startLine
          diffSide
          comments(first: 20) {
            nodes {
              id
              body
              author { login }
              createdAt
            }
          }
        }
      }
    }
  }
}' -f owner='OWNER' -f repo='REPO' -F pr=PR_NUMBER
```

Filter to only **unresolved** threads (`isResolved == false`). Ignore threads that are purely bot overview comments with no actionable feedback (e.g., Copilot summary comments that just say "Copilot reviewed X files").

For each unresolved thread, extract:

- **Thread ID** (the `id` field -- needed later for resolving)
- **File path** (`path`)
- **Line number** (`line`, and `startLine` if it spans multiple lines)
- **Comment body** (the first comment's `body` is the review comment; subsequent comments are replies)
- **Author** (who left the comment)

## Step 2a: Fetch suppressed comments from the review summary

Review threads are not the whole story. Copilot puts some findings in the body
of its review summary instead of raising a thread, below a verdict line like
`### 🔵 Needs a closer look`. The heading varies: a `### Suppressed comments`
section inside the collapsed "Review details" block, or a `Previously missed`
section ("In code that hasn't changed since last review"). Neither appears in
`reviewThreads`, so Step 2 cannot see them and a PR that looks clean can still
have unaddressed findings sitting in plain view on the page. A `**Findings:**
None` line in the summary only counts threads, so don't trust it either.

Read the newest Copilot review body and print from whichever heading appears:

```bash
gh api repos/OWNER/REPO/pulls/PR_NUMBER/reviews --paginate --jq '
  [.[] | select(.user.login | test("copilot"))]
  | sort_by(.submitted_at) | last | .body' \
  | sed 's/<[^>]*>//g' | sed -nE '/(Suppressed comments|Previously missed)/,$p'
```

Only the newest review matters — each one restates the entries still
outstanding, so older bodies are superseded, and a newest review with neither
heading means there is nothing outstanding. Entries look like one of:

```
**app/path/to/file.tsx:232**
* Explanation of the finding.

This issue also appears on line 235 of the same file.
```

```
 Short title of the finding

`app/path/to/file.tsx:232`

Explanation of the finding.

This issue also appears on line 235 of the same file.
```

Take the file path, the line, and the text, and carry them into the same
assessment in Step 3 as thread comments. Two differences to respect:

- **They cannot be resolved.** There is no thread id, so the resolve and reply
  mutations do not apply. Report them in the final summary instead.
- **They go stale.** A suppressed comment is often labelled "Previously
  missed — in code that hasn't changed since the last review", and the same
  entry is repeated in every later review even after the code moved on. Read
  the current file before assessing, and mark an entry that no longer matches
  the code as not valid rather than acting on it.

### The "Changes recommended" open-issues list

Newer Copilot reviews open with a verdict such as `### 🟡 Changes recommended`
and then an `N open issues` list. Each entry is a title linking to
`…/pull/PR_NUMBER#discussion_r<id>`, followed by an `N resolved since last
review` list. An open issue whose comment isn't the first comment of an
unresolved thread from Step 2 has nowhere else to surface, so cross-check the
list against the threads:

```bash
gh api graphql -f query='query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) { pullRequest(number: $pr) {
    reviewThreads(first: 100) { nodes { isResolved
      comments(first: 1) { nodes { databaseId } } } } } } }' \
  -f owner='OWNER' -f repo='REPO' -F pr=PR_NUMBER \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]
        | "\(.comments.nodes[0].databaseId) \(.isResolved)"' > "${TMPDIR:-/tmp}/threads.txt"

gh api repos/OWNER/REPO/pulls/PR_NUMBER/reviews --paginate --jq '
  [.[] | select(.user.login | test("copilot"))]
  | sort_by(.submitted_at) | last | .body' \
  | sed 's/<[^>]*>//g' | sed -nE '/open issues?$/,/resolved since last review|Review effort/p' \
  | grep -oE 'discussion_r[0-9]+' | sed 's/discussion_r//' \
  | while read -r id; do
      echo "$id $(grep "^$id " "${TMPDIR:-/tmp}/threads.txt" | cut -d' ' -f2 || true)"
    done
```

- `<id> false` — an open thread Step 2 already has. Nothing extra to do.
- `<id> true` — Copilot still lists a thread that's resolved. The listing is a
  snapshot taken before the resolve, so it's normally just stale. Recheck it
  only if the code it names has changed since that review's commit.
- `<id>` with nothing after it — no thread at all. Fetch the comment with
  `gh api repos/OWNER/REPO/pulls/comments/<id>`, take its `path`, `line` and
  `body`, and assess it in Step 3 as `Source: open-issue`. Like a suppressed
  comment, it can't be resolved through the thread mutations, so report it in
  Step 6.

If neither Step 2 nor Step 2a turns anything up, tell the user and stop.

## Step 3: Assess each comment

For each comment from Step 2 and Step 2a, read the relevant source code to understand the context. Read the file at the commented path and review the code around the commented lines. Also look at the PR diff for that file to understand what changed:

```bash
gh pr diff PR_NUMBER -- FILE_PATH
```

Then assess whether each comment is **valid** or **not valid**:

- **Valid**: The comment identifies a real issue -- a bug, a missing edge case, a legitimate style/convention violation, a security concern, a performance problem, or a genuinely better approach. Also valid if it suggests adding something that's clearly missing.
- **Not valid**: The comment is a false positive, is based on outdated code, was already addressed in a later commit, is purely subjective preference with no clear benefit, contradicts the project's established conventions, or asks for something that would make the code worse.

For each valid comment, write a brief implementation plan describing what specifically needs to change and where.

## Step 4: Present the plan

Present the assessment as a markdown table. This is the most important step before doing any work -- the user needs to confirm the plan.

Format:

| #   | Comment                | File                  | Author    | Source     | Valid?                                   | Implementation               |
| --- | ---------------------- | --------------------- | --------- | ---------- | ---------------------------------------- | ---------------------------- |
| 1   | Summary of the comment | `path/to/file.ts:L42` | @reviewer | thread     | Yes                                      | Brief description of the fix |
| 2   | Summary of the comment | `path/to/file.ts:L88` | @reviewer | suppressed | No -- already addressed in commit abc123 | N/A                          |

`Source` is `thread` for Step 2 findings, and `suppressed` or `open-issue` for
the two kinds of Step 2a findings, so it is clear which can be resolved on
GitHub at the end and which can only be reported.

After presenting the table, ask the user: **"Does this plan look right? Should I proceed with fixing the valid items, or would you like to adjust anything?"**

Do NOT proceed until the user confirms. They may disagree with your validity assessment or want to change the implementation approach.

## Step 5: Fix and commit each comment

For each comment marked as valid (in the order they appear in the table), make a focused commit:

1. **If the comment reports a bug, write the regression test first.** Add a test that reproduces the bug and run it to watch it fail. Skip this for comments with no behavior to test (naming, docs, style).
2. **Make the code change** as described in the implementation plan, and run the new test to watch it pass.
3. **Prove the test guards the fix.** Temporarily remove only the code change: save it with `git diff -- <changed source files> > "$TMPDIR/fix.patch"` and take it out with `git apply -R "$TMPDIR/fix.patch"`. Run the new test and confirm it fails, then put the fix back with `git apply "$TMPDIR/fix.patch"` and confirm it passes again. (Avoid `git stash` here: the stash is shared across worktrees.) A test that passes without the fix tests nothing: rewrite it until it fails without the fix.
4. **Run any affected tests** to make sure nothing else broke. If checks fail, fix the issue before moving on.
5. **Create a focused commit** for just this change, the fix and its test together. The commit message should reference what review comment it addresses and, for a bug, note that the test was proved to fail without the fix. Example:

   ```
   fix: add null check for user input

   Addresses PR review comment by @reviewer about missing
   validation on the user input field.
   ```

6. **Move to the next valid comment** and repeat until all valid comments are committed.
7. After all commits are done, run the project's full check command — look for a `check` script in `package.json` or the command named in CLAUDE.md/AGENTS.md (e.g. `bun run check`, `npm run check`, `make check`) — to make sure nothing is broken.

Each comment gets its own commit. Do not batch multiple comment fixes into one commit -- this makes it easy for reviewers to verify each fix individually.

## Step 5a: Push all commits once

After all valid comments have been committed, do a single push:

```bash
git push
```

Pushing once at the end avoids triggering multiple CI/review-bot runs for each individual commit.

## Step 5b: Reply and resolve each thread

After pushing, loop through each valid comment **that came from a thread**
(Step 2) and:

1. **Reply to the thread** with a comment indicating the commit that resolved it:
   ```bash
   COMMIT_SHA=$(git log --oneline | grep -m1 "keyword" | awk '{print $1}')
   gh api graphql -f query='
   mutation($threadId: ID!, $body: String!) {
     addPullRequestReviewThreadReply(input: {
       pullRequestReviewThreadId: $threadId,
       body: $body
     }) {
       comment {
         id
       }
     }
   }' -f threadId='THREAD_ID' -f body="Resolved in $COMMIT_SHA"
   ```
2. **Resolve the thread** using the GraphQL mutation:
   ```bash
   gh api graphql -f query='
   mutation($threadId: ID!) {
     resolveReviewThread(input: { threadId: $threadId }) {
       thread {
         id
         isResolved
       }
     }
   }' -f threadId='THREAD_ID'
   ```

## Step 5b: Resolve "not valid" threads as won't fix

After all valid comments are addressed, resolve each **thread** that was marked
as "not valid" in the plan. Suppressed comments have no thread to reply to, so
skip them here and account for them in Step 6. For each one:

1. **Reply to the thread** with a brief explanation prefixed with "Won't fix":
   ```bash
   gh api graphql -f query='
   mutation($threadId: ID!, $body: String!) {
     addPullRequestReviewThreadReply(input: {
       pullRequestReviewThreadId: $threadId,
       body: $body
     }) {
       comment {
         id
       }
     }
   }' -f threadId='THREAD_ID' -f body="Won't fix - <reason>"
   ```
2. **Resolve the thread**:
   ```bash
   gh api graphql -f query='
   mutation($threadId: ID!) {
     resolveReviewThread(input: { threadId: $threadId }) {
       thread {
         id
         isResolved
       }
     }
   }' -f threadId='THREAD_ID'
   ```

The reason should be concise and explain why the comment doesn't apply (e.g., "already addressed in commit abc123", "outdated — code has changed", "intentional placeholder for future feature", "needs infra-level solution, not app code").

## Step 6: Report results

After all valid comments have been addressed, tell the user which threads were
resolved and provide the PR URL so they can verify.

List any suppressed and open-issue comments separately, since nothing on GitHub records that
they were dealt with: say which were fixed (with the commit), which were judged
stale or invalid and why, and that they will keep reappearing in later review
summaries either way. Say plainly that they cannot be resolved through the API
rather than leaving the user to wonder why the PR still shows findings.

## Edge cases

- **Comment with a code suggestion**: GitHub review comments sometimes include ` ```suggestion ` blocks. These are concrete code changes proposed by the reviewer. When valid, apply the suggestion as closely as possible.
- **Multi-line comments**: Some threads reference a range of lines (`startLine` to `line`). Read the full range for context.
- **Outdated comments**: Threads marked `isOutdated` may reference code that has changed since the comment was left. Read the current file state and note if the comment no longer applies.
- **Reply threads**: If a thread has replies (multiple comments), read the full conversation. The original reviewer or the PR author may have already discussed and resolved the concern informally without marking the thread as resolved.
- **A suppressed comment duplicating a thread**: the same finding can appear both ways. Assess it once, fix it once, and resolve the thread — do not raise it twice in the plan.
- **"This issue also appears on line N"**: a suppressed entry often names one line and then points at siblings. Fix every site it names, not just the anchor line.
