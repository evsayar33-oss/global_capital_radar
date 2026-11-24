#!/usr/bin/env bash
# Only run after creating one local observation commit. No force push, no
# destructive conflict resolution; preserve patch if overlapping edits exist.
set -euo pipefail
recovery="$1"
mkdir -p "$(dirname "$recovery")"
git format-patch -1 --binary --stdout HEAD > "$recovery"
for attempt in 1 2 3; do
  if ! git fetch --no-tags origin main; then sleep "$attempt"; continue; fi
  remote="$(git rev-parse FETCH_HEAD)"
  if git merge-base --is-ancestor HEAD "$remote"; then
    rm -f "$recovery"
    exit 0
  fi
  parent="$(git rev-parse HEAD^)"
  if ! git merge-base --is-ancestor "$parent" "$remote"; then
    echo "::error::Observation parent not an ancestor of remote main; patch retained"
    exit 1
  fi
  overlap="$(comm -12 <(git diff --name-only "$parent" HEAD | LC_ALL=C sort -u) <(git diff --name-only "$parent" "$remote" | LC_ALL=C sort -u))"
  if [[ -n "$overlap" ]]; then
    echo "::error::Concurrent changes overlap generated files; patch retained"
    printf '%s\n' "$overlap"
    exit 1
  fi
  if [[ "$parent" != "$remote" ]]; then
    if ! git rebase --onto "$remote" "$parent" HEAD; then
      git rebase --abort || true
      echo "::error::Observation rebase conflict; patch retained"
      exit 1
    fi
  fi
  if git push origin HEAD:refs/heads/main; then
    rm -f "$recovery"
    exit 0
  fi
  sleep "$attempt"
done
echo "::error::Observation push failed after bounded attempts; patch retained"
exit 1
