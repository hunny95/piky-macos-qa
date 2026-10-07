#!/bin/bash
# Before the evidence folder is uploaded from a PUBLIC repository: nothing in
# it may look like a credential. A file that does is removed and the step
# fails, so a mistake is loud and nothing leaks.
#
#   bash harness/check-evidence.sh <evidence folder>
#
# The run never handles a real secret: the one-run account password exists
# only in the run's memory and the machine is destroyed. This is the second
# lock, not the first.
set -uo pipefail
QA_OUT="${1:?Usage: check-evidence.sh <evidence folder>}"
[ -d "$QA_OUT" ] || { echo "No evidence folder at $QA_OUT."; exit 0; }
# Token shapes: GitHub, Tailscale, AWS, private keys, and this job's own token.
QA_SHAPES='gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|tskey-[a-z]+-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abpr]-[A-Za-z0-9-]{10,}'
QA_FOUND=0
while IFS= read -r -d '' QA_FILE; do
  if LC_ALL=C grep -aEq -- "$QA_SHAPES" "$QA_FILE"; then
    echo "::error::$(basename "$QA_FILE") holds something shaped like a credential. It was removed from the evidence."
    rm -f "$QA_FILE"
    QA_FOUND=1
  fi
done < <(find "$QA_OUT" -type f ! -name '*.png' -print0)
# Nothing the app under test, or anyone's files, should be in here.
QA_STRAY="$(find "$QA_OUT" -type f \( -name '*.app' -o -name '*.dmg' -o -name '*.p12' -o -name '*.pem' -o -name '*.key' -o -name '*.mov' -o -name '*.mp4' \) | head -5)"
if [ -n "$QA_STRAY" ]; then
  echo "::error::The evidence holds files that do not belong in it:"; echo "$QA_STRAY"
  find "$QA_OUT" -type f \( -name '*.app' -o -name '*.dmg' -o -name '*.p12' -o -name '*.pem' -o -name '*.key' -o -name '*.mov' -o -name '*.mp4' \) -delete
  QA_FOUND=1
fi
echo "Evidence: $(find "$QA_OUT" -type f | wc -l | tr -d ' ') files, $(du -sh "$QA_OUT" | cut -f1)."
[ "$QA_FOUND" = 0 ] && echo "Nothing shaped like a credential." || exit 1
