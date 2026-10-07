#!/bin/bash
# One interactive QA session on a disposable GitHub-hosted Mac: a person
# connects with RustDesk and tests PIKY by hand.
#
#   bash interactive/session.sh <step>
#
#   kit               the QA kit on the Desktop (fixtures, page, TestReceiver, Results)
#   credentials       two random passwords for this session, masked, kept in a private file
#   admin-create      a temporary administrator, for macOS's own password prompts
#   rustdesk-install  RustDesk, one pinned release, checked against its SHA-256
#   rustdesk-start    start it, give it the session password, read its ID
#   session-note      the session's details, encrypted for the repository owner
#   keep-alive        wait until the time is up or the person ends the session
#   collect           privacy-safe evidence into ./evidence
#   teardown          stop RustDesk, delete the administrator and every credential
#
# What it never does: write to a TCC database, change SIP or Gatekeeper,
# remove a quarantine attribute, print a password, or touch the runner's own
# account. Nothing here traces its commands (no `set -x`).
set -euo pipefail

QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QA_STEP="${1:?Usage: session.sh <step>}"
QA_ADMIN=pikyqa
QA_KIT="$HOME/Desktop/PIKY-QA"
QA_END_FILE="$QA_KIT/END SESSION - delete this file.txt"
QA_STATE="${RUNNER_TEMP:?RUNNER_TEMP is not set}/piky-interactive"
QA_CREDENTIALS="$QA_STATE/credentials"
QA_EVIDENCE="${GITHUB_WORKSPACE:-$QA_ROOT}/evidence"
QA_TOOLS="${QA_TOOLS:-$QA_ROOT/build}"

# One release, by its checksum (github.com/rustdesk/rustdesk, AGPL-3.0).
RUSTDESK_VERSION=1.5.0
RUSTDESK_SHA256=3929b0a4321e7d0f561a317059798be882d65decc59681eb77061f8efe56fbf4
RUSTDESK_APP=/Applications/RustDesk.app
RUSTDESK_BIN="$RUSTDESK_APP/Contents/MacOS/RustDesk"

say() { printf '%s\n' "$*"; }
fail() { printf '::error::%s\n' "$*"; exit 1; }

# Everything that changes the machine runs only on GitHub's disposable runner.
runner_only() {
  if [ "${GITHUB_ACTIONS:-}" != true ] || [ "${RUNNER_ENVIRONMENT:-}" != github-hosted ] || [ "$(id -un)" != runner ]; then
    echo "This step changes the machine it runs on. It only runs on a GitHub-hosted runner." >&2
    exit 2
  fi
}

# The session's passwords: read from the private file, never from the environment.
load_credentials() {
  [ -f "$QA_CREDENTIALS" ] || fail "This session has no credentials file."
  ADMIN_PASSWORD="$(sed -n 's/^ADMIN_PASSWORD=//p' "$QA_CREDENTIALS")"
  RUSTDESK_PASSWORD="$(sed -n 's/^RUSTDESK_PASSWORD=//p' "$QA_CREDENTIALS")"
  RUSTDESK_ID="$(sed -n 's/^RUSTDESK_ID=//p' "$QA_CREDENTIALS")"
}

# Four groups of five, from letters and digits that cannot be mistaken for one
# another: about 99 bits, and possible to type into a password box by hand.
new_password() {
  /usr/bin/python3 -c 'import secrets; a = "abcdefghjkmnpqrstuvwxyz23456789"; print("-".join("".join(secrets.choice(a) for _ in range(5)) for _ in range(4)))'
}

# with_limit <seconds> <command…>: the command's own status, or 137 if it had to be stopped.
with_limit() {
  local seconds="$1"; shift
  "$@" &
  local pid=$!
  ( sleep "$seconds"; kill -9 "$pid" 2>/dev/null ) >/dev/null 2>&1 &
  local watchdog=$!
  local status=0
  wait "$pid" 2>/dev/null || status=$?
  kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  return "$status"
}

case "$QA_STEP" in

kit)
  runner_only
  mkdir -p "$QA_KIT/Results"
  ditto "$QA_TOOLS/TestReceiver.app" "$QA_KIT/TestReceiver.app"
  cp -R "$QA_ROOT/TestFiles" "$QA_KIT/Files"
  cp -R "$QA_ROOT/TestPage" "$QA_KIT/Page"
  rm -f "$QA_KIT/Files/generate.py" "$QA_KIT/Page/build.py"
  cp "$QA_ROOT/interactive/READ-ME-FIRST.txt" "$QA_KIT/READ ME FIRST.txt"
  cp "$QA_ROOT/interactive/QA-CHECKLIST.txt" "$QA_KIT/Results/QA-CHECKLIST.txt"
  # shellcheck source=/dev/null
  . "$QA_ROOT/release.env"
  # A double-click opens the public download in Safari: a browser download, quarantine and all.
  cat > "$QA_KIT/Download PIKY (opens Safari).webloc" <<WEBLOC
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>URL</key><string>$PIKY_DMG_URL</string></dict></plist>
WEBLOC
  printf 'Delete this file (move it to the Trash) when you are done.\nThe session then ends, the evidence is collected and GitHub destroys this Mac.\n' > "$QA_END_FILE"
  # Screenshots taken on this Mac (Shift-Command-3 or 4) land in Results.
  defaults write com.apple.screencapture location "$QA_KIT/Results"
  killall SystemUIServer >/dev/null 2>&1 || true
  say "The QA kit is on the Desktop: $(find "$QA_KIT" -maxdepth 1 -mindepth 1 | wc -l | tr -d ' ') items. PIKY itself is not installed."
  ;;

credentials)
  mkdir -p "$QA_STATE"
  chmod 700 "$QA_STATE"
  ADMIN_PASSWORD="$(new_password)"
  echo "::add-mask::$ADMIN_PASSWORD"
  RUSTDESK_PASSWORD="$(new_password)"
  echo "::add-mask::$RUSTDESK_PASSWORD"
  ( umask 077; printf 'ADMIN_PASSWORD=%s\nRUSTDESK_PASSWORD=%s\n' "$ADMIN_PASSWORD" "$RUSTDESK_PASSWORD" > "$QA_CREDENTIALS" )
  say "Two session passwords were made and masked. They are in a file only this job's user can read, and nowhere else."
  ;;

admin-create)
  runner_only
  load_credentials
  if id "$QA_ADMIN" >/dev/null 2>&1; then fail "An account named $QA_ADMIN already exists on this machine."; fi
  # Apple's tool for adding a user. Its output is discarded: nothing it says is needed.
  sudo -n /usr/sbin/sysadminctl -addUser "$QA_ADMIN" -fullName "PIKY QA Admin" -password "$ADMIN_PASSWORD" -admin >/dev/null 2>&1 || true
  if ! id "$QA_ADMIN" >/dev/null 2>&1; then
    # The same account, record by record.
    QA_UID=$(( $(dscl . -list /Users UniqueID | awk '{print $2}' | sort -n | tail -1) + 1 ))
    sudo -n dscl . -create "/Users/$QA_ADMIN"
    sudo -n dscl . -create "/Users/$QA_ADMIN" UserShell /bin/zsh
    sudo -n dscl . -create "/Users/$QA_ADMIN" RealName "PIKY QA Admin"
    sudo -n dscl . -create "/Users/$QA_ADMIN" UniqueID "$QA_UID"
    sudo -n dscl . -create "/Users/$QA_ADMIN" PrimaryGroupID 20
    sudo -n dscl . -create "/Users/$QA_ADMIN" NFSHomeDirectory "/Users/$QA_ADMIN"
    sudo -n dscl . -passwd "/Users/$QA_ADMIN" "$ADMIN_PASSWORD" >/dev/null 2>&1 || true
    sudo -n dseditgroup -o edit -a "$QA_ADMIN" -t user admin >/dev/null 2>&1 || true
  fi
  id "$QA_ADMIN" >/dev/null 2>&1 || fail "The temporary administrator could not be created. Without it nobody can answer macOS's password prompts, so the session is not opened."
  dseditgroup -o checkmember -m "$QA_ADMIN" admin >/dev/null 2>&1 || fail "The temporary account is not an administrator. The session is not opened."
  # Does macOS accept this name and password? (The same question its prompt will ask.)
  if dscl /Local/Default -authonly "$QA_ADMIN" "$ADMIN_PASSWORD" >/dev/null 2>&1; then
    say "Temporary administrator \"$QA_ADMIN\" exists, is in the admin group, and macOS accepts its name and password."
  else
    fail "macOS does not accept the temporary administrator's password. The session is not opened."
  fi
  # Which rule guards the settings a tester will change (read only, for the record).
  {
    for QA_RIGHT in system.preferences.security system.preferences com.apple.security.assessment.update system.privilege.admin; do
      echo "== $QA_RIGHT"
      security authorizationdb read "$QA_RIGHT" 2>/dev/null | plutil -p - 2>/dev/null | grep -E '"(class|group|rule|shared|authenticate-user|allow-root|session-owner)"' || echo "(not readable)"
    done
  } > "$QA_STATE/authorization-rules.txt" 2>&1 || true
  ;;

rustdesk-install)
  runner_only
  mkdir -p "$QA_STATE"
  QA_DMG="$QA_STATE/rustdesk.dmg"
  curl -fsSL --connect-timeout 20 --max-time 600 --retry 3 --retry-delay 5 -o "$QA_DMG" \
    "https://github.com/rustdesk/rustdesk/releases/download/$RUSTDESK_VERSION/rustdesk-$RUSTDESK_VERSION-aarch64.dmg"
  QA_ACTUAL="$(shasum -a 256 "$QA_DMG" | cut -d' ' -f1)"
  [ "$QA_ACTUAL" = "$RUSTDESK_SHA256" ] || fail "The RustDesk download is not the pinned release (SHA-256 $QA_ACTUAL). Nothing was installed."
  QA_MOUNT="$(mktemp -d "$QA_STATE/rustdesk-volume.XXXXXX")"
  hdiutil attach "$QA_DMG" -nobrowse -readonly -noautoopen -mountpoint "$QA_MOUNT" -quiet
  ditto "$QA_MOUNT/RustDesk.app" "$RUSTDESK_APP"
  hdiutil detach "$QA_MOUNT" -quiet || true
  rm -f "$QA_DMG"
  codesign --verify --strict --deep "$RUSTDESK_APP" || fail "RustDesk's signature does not verify. It was not started."
  say "RustDesk $RUSTDESK_VERSION installed (SHA-256 as pinned; signed by: $(codesign -dvv "$RUSTDESK_APP" 2>&1 | sed -n 's/^Authority=//p' | head -1))."
  ;;

rustdesk-start)
  runner_only
  load_credentials
  # Started by this job, not through LaunchServices: macOS then counts it as
  # part of GitHub's runner agent, which the image already allows to see the
  # screen and post input. No permission is granted or edited here.
  nohup "$RUSTDESK_BIN" >/dev/null 2>&1 &
  QA_WAITED=0
  until pgrep -x RustDesk >/dev/null 2>&1; do
    QA_WAITED=$((QA_WAITED + 1)); [ "$QA_WAITED" -lt 40 ] || fail "RustDesk did not start."
    sleep 1
  done
  sleep 6
  RUSTDESK_ID=''
  QA_WAITED=0
  while [ "${#RUSTDESK_ID}" -lt 6 ]; do
    RUSTDESK_ID="$("$RUSTDESK_BIN" --get-id 2>/dev/null | tr -dc '0-9' || true)"
    QA_WAITED=$((QA_WAITED + 1)); [ "$QA_WAITED" -lt 30 ] || fail "RustDesk did not report an ID within a minute (no connection to its rendezvous server?)."
    [ "${#RUSTDESK_ID}" -ge 6 ] || sleep 2
  done
  echo "::add-mask::$RUSTDESK_ID"
  # The session password, set through RustDesk's own command. Its answer is
  # checked, not printed.
  QA_ANSWER="$(sudo -n "$RUSTDESK_BIN" --password "$RUSTDESK_PASSWORD" 2>&1 || true)"
  case "$QA_ANSWER" in
    *Done*) ;;
    *) fail "RustDesk did not accept the session password, so nobody could connect. The session is not opened." ;;
  esac
  # Only that password opens a session: no one-time password, no click-to-accept.
  sudo -n "$RUSTDESK_BIN" --option verification-method use-permanent-password >/dev/null 2>&1 || true
  sudo -n "$RUSTDESK_BIN" --option approve-mode password >/dev/null 2>&1 || true
  ( umask 077; printf 'RUSTDESK_ID=%s\n' "$RUSTDESK_ID" >> "$QA_CREDENTIALS" )
  pgrep -x RustDesk >/dev/null 2>&1 || fail "RustDesk stopped after it was configured."
  say "RustDesk is running, has an ID (masked) and accepts only the session password."
  # What a job-started program may do on this runner: the same answer RustDesk gets.
  if [ -x "$QA_TOOLS/qa" ]; then
    "$QA_TOOLS/qa" probe | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print("A program started by this job may: read other apps (Accessibility) %s, post keyboard and pointer input %s, capture the screen %s." % (d.get("accessibilityTrusted"), d.get("postEvents"), d.get("screenCapture")))' || true
  fi
  ;;

session-note)
  load_credentials
  : "${QA_SESSION_PASSPHRASE:?The QA_SESSION_PASSPHRASE secret is not set}"
  QA_OUT="${GITHUB_WORKSPACE:?}/session-artifact"
  mkdir -p "$QA_OUT"
  QA_PLAIN="$QA_STATE/session.txt"
  ( umask 077
    cat > "$QA_PLAIN" <<NOTE
PIKY interactive QA session
Run:      ${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}
macOS:    $(sw_vers -productVersion) ($(sw_vers -buildVersion)), runner label ${QA_RUNNER_LABEL:-?}
Open for: ${QA_SESSION_MINUTES:-?} minutes from $(date -u '+%Y-%m-%d %H:%M UTC')

Connect with RustDesk (rustdesk.com, version $RUSTDESK_VERSION or newer):
  ID:        $RUSTDESK_ID
  Password:  $RUSTDESK_PASSWORD

When macOS asks for an administrator (Open Anyway, Accessibility, Screen Recording),
replace the name it shows with this one:
  User name: $QA_ADMIN
  Password:  $ADMIN_PASSWORD

Both passwords exist only for this session. The Mac is destroyed when it ends.
NOTE
  )
  # AES-256, key stretched from the owner's passphrase. Only ciphertext leaves this machine.
  /usr/bin/openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -salt -in "$QA_PLAIN" -out "$QA_OUT/session.txt.enc" -pass env:QA_SESSION_PASSPHRASE
  rm -f "$QA_PLAIN"
  cat > "$QA_OUT/HOW-TO-OPEN.txt" <<'HOWTO'
session.txt.enc holds this session's RustDesk ID and passwords, encrypted.
Only the passphrase stored as the repository secret QA_SESSION_PASSPHRASE opens it.

In Terminal, in the folder with the file:

    /usr/bin/openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -in session.txt.enc

Type the passphrase when asked. The details are printed; they are saved nowhere.
HOWTO
  say "The session's details are encrypted for the repository owner ($(stat -f %z "$QA_OUT/session.txt.enc") bytes of ciphertext). Nothing readable is uploaded."
  ;;

keep-alive)
  runner_only
  QA_MINUTES="${QA_SESSION_MINUTES:?}"
  QA_END=$(( $(date +%s) + QA_MINUTES * 60 ))
  QA_TOLD=0
  say "The session is open for $QA_MINUTES minutes, or until its END SESSION file on the Desktop is deleted."
  while [ "$(date +%s)" -lt "$QA_END" ] && [ -e "$QA_END_FILE" ]; do
    if ! pgrep -x RustDesk >/dev/null 2>&1; then
      say "RustDesk was not running: started again."
      nohup "$RUSTDESK_BIN" >/dev/null 2>&1 &
    fi
    QA_NOW="$(date +%s)"
    if [ $((QA_NOW - QA_TOLD)) -ge 300 ]; then
      QA_TOLD="$QA_NOW"
      say "$(date -u '+%H:%M UTC'): open, $(( (QA_END - QA_NOW) / 60 )) minutes left."
    fi
    sleep 10
  done
  if [ -e "$QA_END_FILE" ]; then say "The time is up."; else say "The tester ended the session."; fi
  ;;

collect)
  runner_only
  mkdir -p "$QA_EVIDENCE/os" "$QA_EVIDENCE/gatekeeper" "$QA_EVIDENCE/receiver" "$QA_EVIDENCE/logs" "$QA_EVIDENCE/results"
  {
    sw_vers; uname -m
    echo "== csrutil status (read only)"; csrutil status 2>&1 || true
    echo "== spctl --status"; spctl --status 2>&1 || true
    echo "== runner"; echo "ImageOS=${ImageOS:-} ImageVersion=${ImageVersion:-} label=${QA_RUNNER_LABEL:-} environment=${RUNNER_ENVIRONMENT:-}"
  } > "$QA_EVIDENCE/os/machine.txt" 2>&1
  [ -f "$QA_STATE/authorization-rules.txt" ] && cp "$QA_STATE/authorization-rules.txt" "$QA_EVIDENCE/os/authorization-rules.txt"
  # What the tester saved: notes and screenshots. No applications, disk images or archives.
  if [ -d "$QA_KIT/Results" ]; then
    find "$QA_KIT/Results" -type f -size -40000k \
      ! -name '*.dmg' ! -name '*.pkg' ! -name '*.zip' ! -name '*.app' ! -name '*.mov' ! -name '*.mp4' ! -name '.DS_Store' \
      -exec cp {} "$QA_EVIDENCE/results/" \; 2>/dev/null || true
  fi
  # What TestReceiver was handed (QA fixtures only).
  cp "$HOME/Library/Logs/PIKY QA TestReceiver/received.jsonl" "$QA_EVIDENCE/receiver/" 2>/dev/null || true
  # PIKY's own content-free records.
  [ -d "$HOME/Library/Application Support/PIKY/Diagnostics" ] && cp -R "$HOME/Library/Application Support/PIKY/Diagnostics" "$QA_EVIDENCE/piky-diagnostics" 2>/dev/null
  {
    for QA_FILE in "$HOME/Downloads"/PIKY-*.dmg; do
      [ -f "$QA_FILE" ] || continue
      echo "== $(basename "$QA_FILE"): $(stat -f %z "$QA_FILE") bytes, SHA-256 $(shasum -a 256 "$QA_FILE" | cut -d' ' -f1)"
      echo "quarantine: $(xattr -p com.apple.quarantine "$QA_FILE" 2>/dev/null || echo absent)"
    done
    if [ -d /Applications/PIKY.app ]; then
      echo "== /Applications/PIKY.app"
      echo "quarantine: $(xattr -p com.apple.quarantine /Applications/PIKY.app 2>/dev/null || echo absent)"
      echo "version: $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' /Applications/PIKY.app/Contents/Info.plist 2>/dev/null) ($(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' /Applications/PIKY.app/Contents/Info.plist 2>/dev/null))"
      spctl --assess --type execute -vv /Applications/PIKY.app 2>&1 || true
      echo "PIKY processes: $(pgrep -f '^/Applications/PIKY.app/Contents/MacOS/PIKY$' | tr '\n' ' ')"
    else
      echo "PIKY is not in /Applications."
    fi
  } > "$QA_EVIDENCE/gatekeeper/installed.txt" 2>&1 || true
  QA_WINDOW="$(( ${QA_SESSION_MINUTES:-60} + 30 ))m"
  with_limit 240 /usr/bin/log show --last "$QA_WINDOW" --style compact --predicate 'process == "PIKY" OR subsystem BEGINSWITH "app.getpiky"' > "$QA_EVIDENCE/logs/piky.log" 2>/dev/null || true
  with_limit 240 /usr/bin/log show --last "$QA_WINDOW" --style compact \
    --predicate '(process == "syspolicyd" OR process == "tccd" OR process == "amfid" OR process == "CoreServicesUIAgent" OR process == "ReportCrash") AND (eventMessage CONTAINS[c] "piky")' \
    > "$QA_EVIDENCE/logs/system.log" 2>/dev/null || true
  mkdir -p "$QA_EVIDENCE/logs/crash-reports"
  find "$HOME/Library/Logs/DiagnosticReports" /Library/Logs/DiagnosticReports -maxdepth 1 -type f \( -name 'PIKY*' -o -name 'TestReceiver*' \) -exec cp {} "$QA_EVIDENCE/logs/crash-reports/" \; 2>/dev/null || true
  # The last lock: no file that leaves this machine may hold a credential of this session.
  if [ -f "$QA_CREDENTIALS" ]; then
    load_credentials
    for QA_SECRET in "$ADMIN_PASSWORD" "$RUSTDESK_PASSWORD" "${QA_SESSION_PASSPHRASE:-}"; do
      [ -n "$QA_SECRET" ] || continue
      LC_ALL=C grep -rlF -- "$QA_SECRET" "$QA_EVIDENCE" 2>/dev/null | while IFS= read -r QA_FILE; do
        rm -f "$QA_FILE"
        echo "::warning::A file of the evidence held a session credential and was removed: $(basename "$QA_FILE")"
      done
    done
  fi
  say "Evidence: $(find "$QA_EVIDENCE" -type f | wc -l | tr -d ' ') files, $(du -sh "$QA_EVIDENCE" | cut -f1)."
  ;;

teardown)
  runner_only
  pkill -x RustDesk >/dev/null 2>&1 || true
  sudo -n pkill -x RustDesk >/dev/null 2>&1 || true
  rm -rf "$RUSTDESK_APP" "$HOME/Library/Preferences/com.carriez.RustDesk" "$HOME/Library/Application Support/RustDesk" "$HOME/Library/Logs/RustDesk"
  if id "$QA_ADMIN" >/dev/null 2>&1; then
    sudo -n /usr/sbin/sysadminctl -deleteUser "$QA_ADMIN" >/dev/null 2>&1 || sudo -n dscl . -delete "/Users/$QA_ADMIN" >/dev/null 2>&1 || true
    sudo -n rm -rf "/Users/$QA_ADMIN"
  fi
  rm -rf "$QA_STATE" "${GITHUB_WORKSPACE:?}/session-artifact"
  pkill -f '/Applications/PIKY.app/Contents/MacOS/PIKY' >/dev/null 2>&1 || true
  rm -rf /Applications/PIKY.app "$HOME/Library/Application Support/PIKY"
  say "RustDesk stopped and removed: $(pgrep -x RustDesk >/dev/null 2>&1 && echo NO || echo yes). Temporary administrator deleted: $(id "$QA_ADMIN" >/dev/null 2>&1 && echo NO || echo yes). Session credentials deleted: $([ -e "$QA_STATE" ] && echo NO || echo yes)."
  ;;

*)
  echo "Unknown step: $QA_STEP" >&2
  exit 2
  ;;
esac
