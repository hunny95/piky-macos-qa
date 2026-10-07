#!/bin/bash
# The console-user probe on a disposable GitHub-hosted Mac: can the temporary
# administrator be the user at the screen, through macOS's own Fast User
# Switching and login window? Nobody connects; no remote desktop is started.
#
#   bash probe/console-user-probe.sh <step>
#
#   prepare    a folder another account can read: the driver, and room for screenshots
#   run        the probe itself (probe/console_user_probe.py)
#   teardown   log the temporary administrator out, delete it and its credentials
#
# The temporary administrator is made by interactive/session.sh
# (admin-credentials, admin-create), with the same password rules.
#
# What it never does: call a private Apple API, write to a TCC database,
# change SIP or Gatekeeper, set up auto-login, restart, reset a password, or
# print one. Nothing here traces its commands (no `set -x`).
set -euo pipefail

QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QA_STEP="${1:?Usage: console-user-probe.sh <step>}"
QA_ADMIN=pikyqa
QA_SHARED=/Users/Shared/PIKY-QA-probe
QA_STATE="${RUNNER_TEMP:?RUNNER_TEMP is not set}/piky-interactive"
QA_EVIDENCE="${GITHUB_WORKSPACE:-$QA_ROOT}/evidence"
QA_TOOLS="${QA_TOOLS:-$QA_ROOT/build}"

say() { printf '%s\n' "$*"; }

# Everything here changes the machine it runs on: GitHub's disposable runner only.
runner_only() {
  if [ "${GITHUB_ACTIONS:-}" != true ] || [ "${RUNNER_ENVIRONMENT:-}" != github-hosted ] || [ "$(id -un)" != runner ]; then
    echo "This step changes the machine it runs on. It only runs on a GitHub-hosted runner." >&2
    exit 2
  fi
}

case "$QA_STEP" in

prepare)
  runner_only
  # The runner's own folders cannot be read by another account. The driver is
  # copied to where one can run it; the copy belongs to root, so only its
  # screenshots and one text file can be added beside it.
  sudo -n mkdir -p "$QA_SHARED/shots"
  sudo -n cp "$QA_TOOLS/qa" "$QA_SHARED/qa"
  sudo -n chmod 755 "$QA_SHARED/qa"
  sudo -n chmod 1777 "$QA_SHARED" "$QA_SHARED/shots"
  say "The driver is also in $QA_SHARED, for the login window's session and the temporary administrator's."
  ;;

run)
  runner_only
  mkdir -p "$QA_EVIDENCE"
  QA_OUT="$QA_EVIDENCE" /usr/bin/python3 "$QA_ROOT/probe/console_user_probe.py"
  ;;

teardown)
  runner_only
  QA_CONSOLE_BEFORE="$(stat -f %Su /dev/console)"
  if id "$QA_ADMIN" >/dev/null 2>&1; then
    QA_UID="$(id -u "$QA_ADMIN")"
    # Log it out if it is logged in, end what it left running, then delete the account.
    sudo -n launchctl bootout "gui/$QA_UID" >/dev/null 2>&1 || true
    sleep 3
    sudo -n pkill -9 -u "$QA_UID" >/dev/null 2>&1 || true
    sleep 1
    sudo -n /usr/sbin/sysadminctl -deleteUser "$QA_ADMIN" >/dev/null 2>&1 || sudo -n dscl . -delete "/Users/$QA_ADMIN" >/dev/null 2>&1 || true
    sudo -n rm -rf "/Users/$QA_ADMIN"
  fi
  sudo -n rm -rf "$QA_SHARED"
  rm -rf "$QA_STATE"
  QA_LINE="Teardown: the console user was $QA_CONSOLE_BEFORE and is now $(stat -f %Su /dev/console). Temporary administrator logged out and deleted: $(id "$QA_ADMIN" >/dev/null 2>&1 && echo NO || echo yes). Its home folder removed: $([ -e "/Users/$QA_ADMIN" ] && echo NO || echo yes). Credential file deleted: $([ -e "$QA_STATE" ] && echo NO || echo yes). No remote desktop, no session note and no PIKY were ever on this machine."
  say "$QA_LINE"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then printf '\n%s\n' "$QA_LINE" >> "$GITHUB_STEP_SUMMARY"; fi
  ;;

*)
  echo "Unknown step: $QA_STEP" >&2
  exit 2
  ;;
esac
