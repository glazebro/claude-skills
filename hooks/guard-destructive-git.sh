#!/bin/bash
# PreToolUse guard for Bash: blocks commands that can silently discard or delete
# work (rm -rf, git clean, git checkout --, git restore, git reset --hard).
# Motivated by real incidents: an untracked local database file was deleted, and a
# git index race corrupted a tracked file.
#
# Not a full shell parser — a regex tripwire. It blocks (exit 2) and asks the
# agent to confirm with the user first; it does not try to distinguish a truly
# safe invocation from a dangerous one.

input=$(cat)
command=$(echo "$input" | jq -r '.tool_input.command // empty')

if [ -z "$command" ]; then
  exit 0
fi

pattern='rm[[:space:]]+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*)|git[[:space:]]+clean|git[[:space:]]+checkout[[:space:]]+--|git[[:space:]]+restore|git[[:space:]]+reset[[:space:]]+--hard'

if echo "$command" | grep -qE "$pattern"; then
  echo "Blocked: '$command' matches a destructive file/git pattern (rm -rf, git clean, git checkout --, git restore, git reset --hard). Confirm with the user before running it — check 'git status' first for anything untracked or uncommitted that would be lost." >&2
  exit 2
fi

exit 0
