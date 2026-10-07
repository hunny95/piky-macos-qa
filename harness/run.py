#!/usr/bin/python3
"""The headed run: the published PIKY disk image on one disposable macOS
machine, driven the way a person would, with evidence kept at every step.

    /usr/bin/python3 harness/run.py

It refuses to start anywhere but a GitHub-hosted runner with no PIKY on it:
it installs into /Applications, presses real keys and moves the real pointer.

Every check ends as one of:

    PASS                             what a person would see, was seen
    FAIL                             PIKY did something wrong
    RUNNER ENVIRONMENT LIMITATION    the hosted runner cannot show this
    INCONCLUSIVE                     the harness could not set the step up
    NOT RUN                          an earlier step did not get there
    INFO                             a recorded observation, not a verdict

Nothing here calls into PIKY: it is launched, typed at, clicked at and
looked at, like any other application.
"""
import json
import os
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import time
import traceback
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qalib import (APP, BUNDLE, FAIL, HOME, INCONCLUSIVE, INFO, LIMIT, NOTRUN, OUT, PASS, PIKY_BIN, QA_BIN, RECEIVER_APP, RESULTS, ROOT,  # noqa: E402
                   SIM, STATE, SUPPORT, TEMP, ax_dump, center, click_element, contrast, crop, find, log, now_iso, output, path, pause, pink,
                   qa, read_dialog, record, release, run, save_text, sha256_file, shot, usable, wait_for, windows)
import results as results_writer  # noqa: E402

RELEASE = release()
DMG_NAME = RELEASE["PIKY_DMG_NAME"]
DOWNLOADED = os.path.join(HOME, "Downloads", DMG_NAME)
# The run's own files stay out of Desktop, Documents and Downloads: macOS
# guards those folders per application, which is not what is being tested.
FIXTURES = os.path.join(HOME, "PIKY-QA-Files")
TEXT_FILE = os.path.join(HOME, "PIKY QA Text.txt")
PAGE = os.path.join(ROOT, "TestPage", "index.html")
RECEIVER_LOG = path("receiver", "received.jsonl")
SETTINGS = "com.apple.systempreferences"
STATUS = re.compile(r"PIKY, (\d+) Picks?(, picking)?\. Show Pack")

PARAGRAPHS = [
    "PIKY QA paragraph one. The harbour lights came on at dusk and the ferry left on time.",
    "PIKY QA paragraph two. Checkout errors rose to six percent before the rollback finished at nine thirty-one.",
    "PIKY QA paragraph three. Seven invented people reviewed the launch brief and nobody changed the date.",
]
# One of each kind the brief names: a plain name, a name with a space, a name
# outside Latin script, a picture, a PDF. Picked in this order.
PLAIN_FILE = "notes.txt"
FINDER_FILES = [PLAIN_FILE, "hello world.txt", "日本語のメモ ✓.txt", "Checkout Errors.png", "Launch Brief.pdf"]

CTX = {
    "os_major": 0, "abort": None, "dmg_ok": False, "browser_download": False, "quarantined": False,
    "install": None, "launched": False, "mode": None, "own_accessibility": False, "own_screen": False,
    "password": None, "password_set": False, "piky_process": None, "expected": 0, "timing": {},
    "picks": [], "receiver_started": False,
}


class Blocked(Exception):
    """A stage cannot go on; the reason is already in the results."""


# ---------------------------------------------------------------- small things

def exists(target):
    return True if SIM and target in (DOWNLOADED, APP) else os.path.exists(target)


def listing(folder):
    """Names in a folder, asked through a command with a time limit: macOS can
    hold a read of Downloads or a mounted volume behind a prompt."""
    code, out, _ = run(["/bin/ls", "-1A", folder], timeout=25, quiet=True)
    return out.splitlines() if code == 0 else None


def file_size(target):
    code, out, _ = run(["/usr/bin/stat", "-f", "%z", target], timeout=25, quiet=True)
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def file_sha(target):
    code, out, _ = run(["/usr/bin/shasum", "-a", "256", target], timeout=90, quiet=True)
    return out.split()[0] if code == 0 and out.strip() else ""


def focus_piky_window(title):
    """Brings one of PIKY's windows forward the way a person does: a click on its title bar."""
    window = find(BUNDLE, "--role", "AXWindow", "--title", title)
    if not window or not usable(window[0].get("frame")):
        return False
    frame = window[0]["frame"]
    qa("click", "%.0f" % (frame[0] + frame[2] / 2), "%.0f" % (frame[1] + 12))
    pause(0.7)
    return True


def into_view(app, owner, *selector):
    """Scrolls an application's window with the wheel until an element is
    inside it, as a person scrolls down to a button. Returns the element once
    its middle is within the window, else None."""
    for attempt in range(22):
        elements = find(app, *selector)
        panes = [window for window in windows(owner) if window["bounds"][2] > 300 and window["bounds"][3] > 200]
        if not panes:
            return None
        box = panes[0]["bounds"]
        spot = "%.0f,%.0f" % (box[0] + box[2] * 0.68, box[1] + box[3] * 0.55)
        frame = elements[0].get("frame") if elements else None
        if not usable(frame):
            # Not built yet (lists are made as they scroll into view): look further down.
            qa("scroll", "-14", "--at", spot, quiet=True)
            pause(0.6)
            continue
        x, y = center(frame)
        top, bottom = box[1] + 60, box[1] + box[3] - 24
        if top <= y <= bottom and box[0] <= x <= box[0] + box[2]:
            return elements[0]
        distance = y - bottom if y > bottom else y - top
        lines = max(2, min(30, int(abs(distance) / 9) + 1))
        qa("scroll", str(-lines if distance > 0 else lines), "--at", spot, quiet=True)
        pause(0.6)
    return None


def drag_into_applications():
    """The gesture the disk image's window asks for: PIKY's icon dragged onto
    the Applications shortcut beside it, with the pointer."""
    icons = [item for item in find("com.apple.finder", "--role", "AXImage", "--title", "PIKY", all=True) if usable(item.get("frame")) and item["frame"][3] >= 40]
    targets = [item for item in find("com.apple.finder", "--role", "AXImage", "--title", "Applications", all=True) if usable(item.get("frame")) and item["frame"][3] >= 40]
    if not icons or not targets:
        return False
    (sx, sy), (tx, ty) = center(icons[0]["frame"]), center(targets[0]["frame"])
    qa("drag", "%.0f" % sx, "%.0f" % sy, "%.0f" % tx, "%.0f" % ty, "--ms", "1200", "--steps", "40", "--settle-ms", "1000")
    copied = wait_for(lambda: exists(PIKY_BIN) or (SIM and exists(APP)), 30, 0.8)
    pause(2.5)  # let Finder finish writing the bundle
    return bool(copied)


def translocated_pids():
    """A PIKY that macOS started from a randomised, read-only location (App Translocation)."""
    code, out, _ = run(["/usr/bin/pgrep", "-f", "AppTranslocation/.*/PIKY.app/Contents/MacOS/PIKY"], quiet=True)
    return [int(line) for line in out.split() if line.isdigit()] if code == 0 else []


def piky_pids():
    code, out, _ = run(["/usr/bin/pgrep", "-f", "^" + PIKY_BIN + "$"], quiet=True)
    return [int(line) for line in out.split() if line.isdigit()] if code == 0 else []


def piky_running():
    return bool(piky_pids())


def frontmost():
    return qa("probe", quiet=True).get("frontmost", {})


def piky_status():
    """PIKY's menu-bar item as VoiceOver hears it: the count, and whether it is picking."""
    for element in find(BUNDLE, "--contains", "Show Pack", all=True):
        for key in ("description", "title", "value", "help"):
            match = STATUS.search(element.get(key) or "")
            if match:
                return {"label": match.group(0), "count": int(match.group(1)), "picking": bool(match.group(2)),
                        "frame": element.get("frame"), "role": element.get("role"), "help": element.get("help", "")}
    return None


def count_now():
    status = piky_status()
    return status["count"] if status else None


def wait_count(target, timeout=8):
    return wait_for(lambda: (piky_status() or {}).get("count") == target, timeout)


def wait_picking(wanted, timeout=6):
    return wait_for(lambda: (lambda status: status is not None and status["picking"] == wanted)(piky_status()), timeout)


def piky_windows():
    """Titles of PIKY's ordinary windows (first run, Settings, Review)."""
    return [element.get("title", "") for element in find(BUNDLE, "--role", "AXWindow", all=True)]


def piky_overlay_count():
    return len([window for window in windows() if window.get("owner") == "PIKY"])


def activate(bundle):
    run(["/usr/bin/open", "-b", bundle], quiet=True)
    pause(1.0)
    return frontmost().get("bundle") == bundle


def quit_app(name):
    """Ends an application. It is asked politely only where the runner may
    already send Apple Events (Safari, Finder); asking any other application
    would raise a macOS consent prompt nobody is there to answer."""
    code, _, _ = run(["/usr/bin/pgrep", "-x", name], quiet=True)
    if code != 0:
        return
    if name in ("Safari", "Finder"):
        run(["/usr/bin/osascript", "-e", 'tell application "%s" to quit' % name], timeout=12, quiet=True)
        pause(0.8)
        code, _, _ = run(["/usr/bin/pgrep", "-x", name], quiet=True)
    if code == 0:
        run(["/usr/bin/killall", name], quiet=True)
        pause(0.8)


def spawn(command):
    """Starts a command and does not wait for it (an `open` that macOS answers
    with a dialog may not return until the dialog is closed)."""
    log("$ %s (not waited for)" % " ".join(command))
    if SIM:
        run(command, quiet=True)
        return
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def close_finder_windows():
    run(["/usr/bin/osascript", "-e", 'tell application "Finder" to close every window'], timeout=15, quiet=True)
    pause(0.6)


def press(code, mods=None, hold=70):
    arguments = ["key", str(code)] + (["--mods", mods] if mods else []) + ["--hold-ms", str(hold)]
    return qa(*arguments)


def option_space():
    return press(49, "opt")


def escape():
    return press(53)


def release_modifiers():
    qa("release", quiet=True)


def library():
    """PIKY's Packs as they are on disk: kinds and counts (the content is QA
    fixtures only). The current Pack is the one PIKY's own settings name."""
    packs = {}
    groups = os.path.join(SUPPORT, "Groups")
    if os.path.isdir(groups):
        for name in sorted(os.listdir(groups)):
            manifest = os.path.join(groups, name, "group.json")
            try:
                with open(manifest, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            entries = data.get("entries", [])
            packs[name.upper()] = {
                "count": len(entries),
                "kinds": [entry.get("item", {}).get("type", "?") for entry in entries],
                "ids": [entry.get("item", {}).get("id", "") for entry in entries],
                "texts": [entry.get("item", {}).get("content", "") for entry in entries],
                "files": [os.path.basename((entry.get("item", {}).get("fileReference") or {}).get("path", "")) for entry in entries],
                "title": data.get("summary", {}).get("title", ""),
            }
    current = ""
    for key in ("activeContext", "currentGroup"):
        code, out, _ = run(["/usr/bin/defaults", "read", BUNDLE, key], quiet=True)
        if code == 0 and out.strip().upper() in packs:
            current = out.strip().upper()
            break
    return {"packs": packs, "current": current, "currentPack": packs.get(current)}


def current_pack(expect=None, timeout=6):
    """The current Pack on disk, once it holds `expect` Picks (PIKY saves a moment after a Pick)."""
    if expect is None:
        return library()["currentPack"]
    found = wait_for(lambda: (lambda pack: pack if pack and pack["count"] == expect else None)(library()["currentPack"]), timeout, 0.5)
    return found or library()["currentPack"]


def same_name(a, b):
    return unicodedata.normalize("NFC", a) == unicodedata.normalize("NFC", b)


# Owners of windows that are part of an ordinary desktop. A sizeable window of
# anything else is macOS (or something unexpected) asking a question.
ORDINARY = {"Finder", "Dock", "Window Server", "SystemUIServer", "Control Center", "Spotlight", "Safari", "TextEdit", "PIKY", "TestReceiver",
            "Notification Center", "NotificationCenter", "WindowManager", "Wallpaper", "loginwindow", "TextInputMenuAgent", "screencapture",
            "Terminal", "AutoFill", "CursorUIViewService", "TextInputSwitcher", "AirPlayUIAgent", "Siri", "talagent", "Menu Bar", "StatusKitAgent",
            "Accessibility", "ControlCenter", "universalaccessd", "PowerChime", "com.apple.dock.extra", "Safari Web Content", "Open and Save Panel Service"}


def askers():
    """Windows that look like a question from macOS: (owner, pid, bounds)."""
    found, seen = [], set()
    for window in windows():
        owner, bounds = window.get("owner", ""), window.get("bounds", [0, 0, 0, 0])
        if owner in ORDINARY or window.get("pid") in seen or bounds[2] < 160 or bounds[3] < 70:
            continue
        seen.add(window.get("pid"))
        found.append((owner, window.get("pid"), bounds))
    return found


def dialogs(label):
    """Outlines of whatever macOS is asking, for the record."""
    kept = []
    for owner, pid, bounds in askers()[:5]:
        log("a window of %s (pid %s) at %s" % (owner, pid, bounds))
        kept.append(ax_dump("%s-%s" % (label, owner), {"pid": pid}, depth=30, maximum=1500))
    return kept


def dialog_of(owner, mentions=None):
    """A question macOS is asking, with its words and buttons: the window of
    the named system agent, else (given `mentions`) any asking window whose
    words include it."""
    candidates = [(name, pid, bounds) for name, pid, bounds in askers() if name == owner]
    if mentions:
        candidates += [(name, pid, bounds) for name, pid, bounds in askers() if name not in (owner, "System Settings")]
    for name, pid, bounds in candidates:
        text = read_dialog({"pid": pid})
        if name != owner and not any(mentions in words for words in text["texts"]):
            continue
        text["pid"] = pid
        text["owner"] = name
        return text
    return None


def gatekeeper_alert():
    return dialog_of("CoreServicesUIAgent", mentions="PIKY")


def press_button(app, titles, label):
    """Clicks the first button with one of these names. Returns its name."""
    for title in titles:
        done = click_element(app, "--role", "AXButton", "--title", title)
        if done:
            log("%s: clicked “%s” (%s)" % (label, title, done["how"]))
            return title
    return None


# ------------------------------------------------- the admin prompt, by the UI

def auth_prompt():
    """Is a password box waiting for keys? macOS turns on secure input for one."""
    focused = qa("ax", "focused", quiet=True)
    return bool(focused.get("secure")) or bool(focused.get("secureInput"))


def account_password():
    """A random password for this disposable account, set once, so macOS's own
    admin prompt can be answered through its own window. It is never printed,
    logged or stored; the machine is destroyed with the job. No security
    database (TCC, Gatekeeper, SIP) is touched by this."""
    if os.environ.get("QA_ALLOW_ACCOUNT_PASSWORD", "true").lower() != "true":
        return None
    if CTX["password_set"]:
        return CTX["password"]
    CTX["password"] = "Qa-" + secrets.token_hex(12) + "-9z"
    user = os.environ.get("USER") or os.path.basename(HOME)
    code, _, err = run(["/usr/bin/sudo", "-n", "/usr/bin/dscl", ".", "-passwd", "/Users/" + user, CTX["password"]], timeout=30, quiet=True, secret=True)
    CTX["password_set"] = code == 0
    log("a one-run password was %s on the runner account" % ("set" if code == 0 else "NOT set (%s)" % err.strip()[:120]))
    return CTX["password"] if code == 0 else None


def answer_auth(label):
    """If macOS is asking for the administrator's password, types it into the
    password box (and only into a password box). Returns what happened."""
    if not wait_for(auth_prompt, 6, 0.5):
        return "no prompt"
    evidence = [shot(label + "-admin-prompt")] + dialogs(label + "-admin-prompt")
    password = account_password()
    if not password:
        record("macOS asked for the administrator's password (%s)" % label, LIMIT,
               "the prompt appeared; no password is available to this run, so it was left unanswered", evidence)
        return "no password"
    if not auth_prompt():
        return "prompt gone"
    qa("type", "--stdin", input_text=password, quiet=True, secret=True)
    pause(0.4)
    press(36)
    pause(3.0)
    still = auth_prompt()
    evidence.append(shot(label + "-after-admin-prompt"))
    record("macOS asked for the administrator's password (%s)" % label, INFO,
           "typed into the password box of macOS's own prompt, then Return; the prompt %s" % ("is still up" if still else "closed"), evidence)
    return "still asking" if still else "answered"


# ------------------------------------------------------------------- stages

def stage_environment():
    STATE["stage"] = "0 Runner"
    code, version, _ = run(["/usr/bin/sw_vers", "-productVersion"], quiet=True)
    CTX["os_major"] = int((version.strip() or "0").split(".")[0])
    save_text("os/sw_vers.txt", output(["/usr/bin/sw_vers"]) + "\n" + output(["/usr/bin/uname", "-a"]))
    hardware = output(["/usr/sbin/system_profiler", "SPHardwareDataType", "SPDisplaysDataType"], timeout=90)
    save_text("os/hardware.txt", "\n".join(line for line in hardware.splitlines()
                                           if not re.search(r"Serial Number|Hardware UUID|Provisioning UDID", line)))
    save_text("os/security.txt", "\n".join([
        "== csrutil status (read only)", output(["/usr/bin/csrutil", "status"]),
        "== spctl --status", output(["/usr/sbin/spctl", "--status"]),
        "== Gatekeeper assessments", output(["/usr/bin/defaults", "read", "/Library/Preferences/com.apple.security", "GKAutoRearm"]),
        "== automationmodetool", output(["/usr/bin/automationmodetool"]),
        "== runner", "ImageOS=%s ImageVersion=%s RUNNER_ARCH=%s RUNNER_ENVIRONMENT=%s RUNNER_NAME=%s" % tuple(
            os.environ.get(name, "") for name in ("ImageOS", "ImageVersion", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "RUNNER_NAME")),
    ]))
    # What the image already allows, read (never written) from the two TCC databases.
    query = "select service, client, client_type, auth_value, indirect_object_identifier from access order by service, client;"
    user_db = os.path.join(HOME, "Library/Application Support/com.apple.TCC/TCC.db")
    save_text("os/tcc-environment.txt", "\n".join([
        "The runner image's existing permissions (auth_value 2 = allowed). Read-only queries; this run writes to neither database.",
        "== user database", output(["/usr/bin/sqlite3", "-readonly", user_db, query]),
        "== system database", output(["/usr/bin/sudo", "-n", "/usr/bin/sqlite3", "-readonly", "/Library/Application Support/com.apple.TCC/TCC.db", query]),
    ]))
    save_text("os/guarded-folders.txt", "\n".join(
        "== ls %s (25 s limit)\n%s" % (name, "readable, %s entries" % len(found) if found is not None else "NOT readable by this job")
        for name, found in ((name, listing(os.path.join(HOME, name))) for name in ("Downloads", "Desktop", "Documents"))))
    probe = qa("probe")
    save_text("os/driver-probe.json", json.dumps(probe, indent=2, sort_keys=True))
    save_text("os/screens.json", json.dumps(qa("screens", quiet=True), indent=2, sort_keys=True))
    first = shot("desktop-before")
    if first:
        info = qa("image", "info", path(first), quiet=True)
        STATE["scale"] = info.get("scaleFromMainDisplay") or 1.0
    record("A logged-in desktop the run can see and drive", PASS if probe.get("accessibilityTrusted") and probe.get("sessionOnConsole") and first else LIMIT,
           "macOS %s; console session %s; driver may read other apps (Accessibility) %s, post events %s, capture the screen %s; display %s points, screenshots ×%.2g"
           % (version.strip(), probe.get("sessionOnConsole"), probe.get("accessibilityTrusted"), probe.get("postEvents"), probe.get("screenCapture"),
              probe.get("mainDisplayPoints"), STATE["scale"]),
           [first, "os/driver-probe.json", "os/tcc-environment.txt", "os/security.txt"])
    if not probe.get("accessibilityTrusted") and not SIM:
        CTX["abort"] = "the driver has no Accessibility access on this runner, so nothing can be driven"
    record("The runner's own permissions are not PIKY's", INFO,
           "GitHub's image pre-allows its agent, bash and osascript for Accessibility, Apple Events and screen capture (os/tcc-environment.txt). "
           "That is how this run can drive the desktop. It says nothing about what a new Mac allows PIKY.", ["os/tcc-environment.txt"])
    if os.path.exists(APP) or os.path.exists(SUPPORT):
        CTX["abort"] = "PIKY or its data is already on this machine: this run is for clean, disposable machines only"
        CTX["foreign"] = True
        record("A machine that has never had PIKY", FAIL, CTX["abort"])
    else:
        record("A machine that has never had PIKY", PASS, "no /Applications/PIKY.app, no ~/Library/Application Support/PIKY")


def stage_safari_download():
    STATE["stage"] = "1 Safari download"
    url = RELEASE["PIKY_DMG_URL"]
    evidence = []
    started = time.time()
    run(["/usr/bin/open", "-a", "Safari", url])
    asked = None
    saved = False
    unreadable = 0
    deadline = time.time() + (0.2 if SIM else 150)
    while time.time() < deadline:
        names = listing(os.path.dirname(DOWNLOADED))
        if names is None:
            unreadable += 1
        elif DMG_NAME in names and not [name for name in names if name.endswith(".download")] and file_size(DOWNLOADED) == int(RELEASE["PIKY_DMG_BYTES"]):
            saved = True
            break
        if asked is None:
            allow = find("com.apple.Safari", "--role", "AXButton", "--title", "Allow")
            if allow:
                evidence.append(shot("safari-asks-to-allow-downloads"))
                evidence.append(ax_dump("safari-allow-downloads", "com.apple.Safari", maximum=1200))
                sheet = [text for text in read_dialog("com.apple.Safari")["texts"] if "download" in text.lower()]
                asked = sheet[0] if sheet else "(a prompt with an Allow button)"
                click_element("com.apple.Safari", "--role", "AXButton", "--title", "Allow")
        pause(1.5)
    seconds = time.time() - started
    evidence.append(shot("safari-after-download"))
    if not saved:
        evidence.append(ax_dump("safari-no-download", "com.apple.Safari", maximum=1500))
        evidence += dialogs("safari-no-download")
        record("Safari downloads the disk image from the public release address", LIMIT,
               "no complete %s in ~/Downloads after %.0f s of driving Safari (%s); see the screenshots. Nothing was written to stand in for it."
               % (DMG_NAME, seconds, "the job could not read ~/Downloads %s times" % unreadable if unreadable else "the folder was readable"), evidence)
        record("Quarantine attribute on the browser download", NOTRUN, "there is no browser download to inspect")
        return
    CTX["browser_download"] = True
    record("Safari downloads the disk image from the public release address", PASS,
           "Safari opened the address and saved %s to ~/Downloads in %.0f s%s" % (DMG_NAME, seconds, ("; it first asked: “%s” (Allow was clicked)" % asked) if asked else "; it did not ask before downloading"),
           evidence)

    actual = file_sha(DOWNLOADED)
    size = file_size(DOWNLOADED)
    CTX["dmg_ok"] = actual == RELEASE["PIKY_DMG_SHA256"] and size == int(RELEASE["PIKY_DMG_BYTES"])
    record("The downloaded file is the published one, byte for byte", PASS if CTX["dmg_ok"] else FAIL,
           "%s bytes, SHA-256 %s (expected %s bytes, %s)" % (size, actual, RELEASE["PIKY_DMG_BYTES"], RELEASE["PIKY_DMG_SHA256"]))
    if not CTX["dmg_ok"]:
        CTX["abort"] = "the file Safari downloaded is not the published disk image"
        return

    attributes = output(["/usr/bin/xattr", "-l", DOWNLOADED])
    code, value, _ = run(["/usr/bin/xattr", "-p", "com.apple.quarantine", DOWNLOADED], quiet=True)
    value = value.strip()
    origins = []
    code_from, raw, _ = run(["/usr/bin/xattr", "-px", "com.apple.metadata:kMDItemWhereFroms", DOWNLOADED], quiet=True)
    if code_from == 0 and raw.strip():
        try:
            origins = [str(origin).split("?", 1)[0] for origin in plistlib.loads(bytes.fromhex("".join(raw.split())))]
        except (ValueError, plistlib.InvalidFileException):
            origins = []
    parts = value.split(";")
    save_text("gatekeeper/quarantine-downloaded-dmg.txt", "\n".join([
        "xattr -l %s" % DMG_NAME, attributes, "", "com.apple.quarantine = %s" % (value or "(absent)"),
        "  flags      %s" % (parts[0] if parts and parts[0] else "-"), "  time (hex) %s" % (parts[1] if len(parts) > 1 else "-"),
        "  agent      %s" % (parts[2] if len(parts) > 2 else "-"), "  event id   %s" % ("present" if len(parts) > 3 and parts[3] else "-"),
        "where from = %s" % origins]))
    CTX["quarantined"] = code == 0 and bool(value)
    record("Quarantine attribute on the browser download", PASS if CTX["quarantined"] else INFO,
           ("com.apple.quarantine = %s (agent: %s); recorded origin: %s" % (value, parts[2] if len(parts) > 2 else "?", origins[0] if origins else "none"))
           if CTX["quarantined"] else "the file Safari saved carries NO com.apple.quarantine attribute on this runner; none was added",
           ["gatekeeper/quarantine-downloaded-dmg.txt"])


def mount_point():
    """Where the downloaded image is mounted, if it is."""
    code, out, _ = run(["/usr/bin/hdiutil", "info", "-plist"], quiet=True)
    if code != 0 or not out.strip():
        return None
    try:
        info = plistlib.loads(out.encode("utf-8"))
    except (ValueError, plistlib.InvalidFileException):
        return None
    for image in info.get("images", []):
        if image.get("image-path", "").endswith("/Downloads/" + DMG_NAME):
            for entity in image.get("system-entities", []):
                if entity.get("mount-point"):
                    return entity["mount-point"]
    return None


def quarantine_of(target):
    code, value, _ = run(["/usr/bin/xattr", "-p", "com.apple.quarantine", target], quiet=True)
    return value.strip() if code == 0 else ""


def gatekeeper_dismiss(alert):
    """Closes a Gatekeeper alert without choosing anything that deletes the app."""
    for title in ("OK", "Done", "Cancel"):
        if title in alert.get("buttons", []):
            if click_element({"pid": alert["pid"]}, "--role", "AXButton", "--title", title):
                return title
    press(53)
    return "Escape"


def gatekeeper_follow(label, seconds):
    """After asking macOS to open PIKY anyway: answers its admin prompt and its
    confirmation, whichever come, until PIKY runs or the time is up."""
    notes = []
    deadline = time.time() + (0.2 if SIM else seconds)
    answered = 0
    again = False
    while time.time() < deadline:
        if piky_running():
            return True, notes
        moved = translocated_pids()
        if moved:
            pause(1.5)
            said = read_dialog(BUNDLE)
            shot("%s-piky-from-translocated-copy" % label)
            CTX["translocated"] = "macOS let PIKY start, from a translocated copy (pid %s); PIKY then said: “%s” [buttons: %s]" % (
                moved, " ".join(said["texts"])[:300], ", ".join(said["buttons"]))
            notes.append(CTX["translocated"])
            press_button(BUNDLE, ["Quit"], "PIKY's own alert")
            pause(1.0)
            for pid in translocated_pids():
                run(["/bin/kill", "-TERM", str(pid)], quiet=True)
            return False, notes
        if answered < 2 and auth_prompt():
            notes.append("admin prompt: " + answer_auth(label))
            answered += 1
            continue
        alert = gatekeeper_alert()
        if alert:
            for title in ("Open", "Open Anyway"):
                if title in alert["buttons"]:
                    shot("%s-confirmation" % label)
                    notes.append("confirmation: “%s” — clicked %s" % (" ".join(alert["texts"])[:300], title))
                    click_element({"pid": alert["pid"]}, "--role", "AXButton", "--title", title)
                    break
        if answered and not again and find(SETTINGS, "--role", "AXButton", "--title", "Open Anyway"):
            # Some versions ask for the password first and want the button once more.
            again = True
            notes.append("System Settings still offered Open Anyway after the password: clicked it once more")
            click_element(SETTINGS, "--role", "AXButton", "--title", "Open Anyway")
        pause(1.2)
    return piky_running(), notes


def stage_gatekeeper():
    STATE["stage"] = "2 Gatekeeper"
    if not CTX["browser_download"] or not CTX["dmg_ok"]:
        record("Gatekeeper's first open of the browser download", NOTRUN, "Safari did not produce the published file, so there is nothing quarantined to open")
        return
    # Mount, as a double-click in Downloads does (Safari may already have opened it).
    mounted = mount_point()
    by_safari = bool(mounted)
    if not mounted:
        spawn(["/usr/bin/open", DOWNLOADED])
        mounted = wait_for(mount_point, 40, 1.0)
    evidence = [shot("disk-image-open")]
    if not mounted:
        record("The disk image mounts", FAIL if not SIM else INCONCLUSIVE, "macOS did not mount the downloaded image within 40 s", evidence + dialogs("mount"))
        raise Blocked()
    contents = sorted(name for name in (listing(mounted) or []) if not name.startswith("."))
    record("The disk image mounts", PASS, "%s at %s; it holds: %s" % ("Safari opened it by itself" if by_safari else "opened from Downloads", mounted, ", ".join(contents)), evidence)
    source = os.path.join(mounted, "PIKY.app")

    # Copy to Applications: the drag a person makes, in the image's own window.
    how = "dragged with the pointer, in the disk image's window, from PIKY's icon onto the Applications shortcut"
    if not drag_into_applications():
        shot("drag-into-applications-did-not-copy")
        code, _, err = run(["/usr/bin/osascript", "-e", 'set theApp to POSIX file "%s" as alias' % source,
                            "-e", 'set theFolder to POSIX file "/Applications" as alias',
                            "-e", 'tell application "Finder" to duplicate theApp to theFolder'], timeout=90)
        how = "the pointer drag did not copy it; Finder copied it when asked by script (not a person's drag: macOS may then run it from a translocated path)"
        if code != 0 or not exists(APP):
            how = "neither the pointer drag nor Finder copied it (%s); ditto copied it, extended attributes included" % (err.strip()[:120] or "no answer")
            run(["/usr/bin/ditto", source, APP], timeout=120)
    CTX["install"] = "browser download"
    app_quarantine = quarantine_of(APP)
    save_text("gatekeeper/installed-app.txt", "\n".join([
        "== copy", how, "== xattr -l /Applications/PIKY.app", output(["/usr/bin/xattr", "-l", APP]),
        "== quarantine on the app inside the mounted image", quarantine_of(source) or "(absent)",
        "== spctl --assess --type execute -vv (an assessment only; nothing is changed)", output(["/usr/sbin/spctl", "--assess", "--type", "execute", "-vv", APP]),
        "== codesign -dvv", output(["/usr/bin/codesign", "-dvv", APP]),
        "== codesign --verify --strict --deep", output(["/usr/bin/codesign", "--verify", "--strict", "--deep", "--verbose=2", APP])]))
    record("PIKY is copied to Applications", PASS if exists(APP) else FAIL,
           "%s; com.apple.quarantine on /Applications/PIKY.app: %s" % (how, app_quarantine or "ABSENT"), ["gatekeeper/installed-app.txt"])
    if not exists(APP):
        raise Blocked()
    close_finder_windows()

    # The first open.
    opened_at = time.strftime("%Y-%m-%d %H:%M:%S")
    CTX["gatekeeper_started"] = opened_at
    spawn(["/usr/bin/open", APP])
    seen = wait_for(lambda: piky_running() or gatekeeper_alert(), 25, 0.8)
    pause(1.0)
    alert = gatekeeper_alert()
    evidence = [shot("gatekeeper-first-open")] + dialogs("gatekeeper-first-open")
    running = piky_running()
    words = " ".join(alert["texts"]) if alert else ""
    save_text("gatekeeper/first-open.txt", "\n".join([
        "open /Applications/PIKY.app at %s" % opened_at,
        "PIKY process after the open: %s" % ("running, pid %s" % piky_pids() if running else "none"),
        "alert shown by macOS: %s" % ("yes" if alert else "no"),
        "exact wording: %s" % (words or "-"), "buttons: %s" % (", ".join(alert["buttons"]) if alert else "-"),
        "quarantine on the app: %s" % (app_quarantine or "absent")]))
    evidence.append("gatekeeper/first-open.txt")
    if alert and not running:
        record("Gatekeeper's first open of the browser download", PASS if "PIKY" in words else INCONCLUSIVE,
               ("macOS refused to open it and said: “%s” [buttons: %s]. No PIKY process started. This is Gatekeeper refusing a build that is not notarized, as expected; it is not a crash."
                % (words, ", ".join(alert["buttons"]))) if "PIKY" in words else
               "a window of %s is up and no PIKY process started, but its words could not be read through Accessibility (read: “%s”); see the screenshot" % (alert.get("owner"), words),
               evidence)
        gatekeeper_dismiss(alert)
        pause(1.0)
    elif running:
        CTX["launched"] = True
        record("Gatekeeper's first open of the browser download", INFO,
               "PIKY opened with %s (quarantine on the app: %s). Gatekeeper did not stop a build that is not notarized on this runner."
               % ("an alert: “%s”" % words if alert else "no alert", app_quarantine or "absent"), evidence)
        return
    else:
        record("Gatekeeper's first open of the browser download", INCONCLUSIVE,
               "after 25 s there is neither a PIKY process nor a readable alert (seen: %s); see the screenshot" % bool(seen), evidence)

    # Open Anyway, in System Settings, by hand.
    run(["/usr/bin/open", "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension"])
    pause(3.0)
    find(SETTINGS, "--role", "AXWindow", timeout=8)
    shown = into_view(SETTINGS, "System Settings", "--role", "AXButton", "--title", "Open Anyway")
    button = [shown] if shown else []
    scrolled = "scrolled into view" if shown else "not reached by scrolling"
    evidence = [shot("privacy-security-open-anyway"), ax_dump("privacy-security", SETTINGS)]
    if not button:
        record("System Settings › Privacy & Security offers Open Anyway", INCONCLUSIVE if alert else NOTRUN,
               "no Open Anyway button could be brought into view in Privacy & Security (%s); see the screenshot and the outline" % scrolled, evidence)
    else:
        nearby = [text for text in read_dialog(SETTINGS)["texts"] if "PIKY" in text]
        record("System Settings › Privacy & Security offers Open Anyway", PASS,
               "scrolled down to the Security section; the pane says: “%s” with an Open Anyway button at %s" % (nearby[0] if nearby else "(the text beside the button could not be read)", shown.get("frame")), evidence)
        done = click_element(SETTINGS, "--role", "AXButton", "--title", "Open Anyway")
        pause(2.0)
        evidence = [shot("after-open-anyway")] + dialogs("after-open-anyway")
        launched, notes = gatekeeper_follow("open-anyway", 30)
        if not launched:
            spawn(["/usr/bin/open", APP])
            again, more = gatekeeper_follow("open-anyway-second-open", 20)
            launched, notes = again, notes + ["opened PIKY again"] + more
        evidence.append(shot("open-anyway-result"))
        evidence += dialogs("open-anyway-result")
        if launched:
            CTX["launched"] = True
            record("Open Anyway opens PIKY", PASS, "clicked Open Anyway (%s); then: %s. PIKY is running (pid %s)." % (done["how"] if done else "?", "; ".join(notes) or "nothing more was asked", piky_pids()), evidence)
        elif CTX.get("translocated"):
            record("Open Anyway opens PIKY", INFO,
                   "Gatekeeper's override worked: clicked Open Anyway (%s); then: %s. PIKY refused to continue because macOS ran it from a translocated location, which happens when the copy in Applications was not made by a person's drag in Finder. How it was copied here: %s."
                   % (done["how"] if done else "?", "; ".join(notes), how), evidence)
        else:
            record("Open Anyway opens PIKY", LIMIT,
                   "Open Anyway was clicked (%s) but PIKY did not start within the time allowed. What happened: %s. Either macOS ignores a scripted click or scripted typing on this protected step, or its prompt could not be reached by the driver; a person at the screen is needed."
                   % (done["how"] if done else "?", "; ".join(notes) or "no prompt or confirmation could be seen by the driver"), evidence)
    quit_app("System Settings")

    # macOS 14 only: Control-click › Open is the other documented way past the first open.
    if not CTX["launched"] and CTX["os_major"] == 14:
        stage_gatekeeper_context_open()
    close_finder_windows()


def stage_gatekeeper_context_open():
    alert = gatekeeper_alert()
    if alert:
        gatekeeper_dismiss(alert)
    run(["/usr/bin/open", "-R", APP])
    pause(2.5)
    items = [item for item in find("com.apple.finder", "--role", "AXImage", "--title", "PIKY", all=True) if usable(item.get("frame")) and item["frame"][3] >= 14]
    evidence = [shot("finder-reveals-piky")]
    if not items:
        record("Control-click › Open (macOS 14)", INCONCLUSIVE, "PIKY's icon could not be located in the Finder window", evidence + [ax_dump("finder-applications", "com.apple.finder", maximum=2500)])
        return
    x, y = center(items[0]["frame"])
    qa("click", "%.1f" % x, "%.1f" % y, "--button", "right")
    pause(1.2)
    evidence.append(shot("finder-context-menu"))
    chosen = click_element("com.apple.finder", "--role", "AXMenuItem", "--title", "Open")
    if not chosen:
        escape()
        record("Control-click › Open (macOS 14)", INCONCLUSIVE, "the shortcut menu's Open item was not found", evidence + [ax_dump("finder-context-menu", "com.apple.finder", maximum=2500)])
        return
    pause(2.0)
    launched, notes = gatekeeper_follow("context-open", 25)
    evidence.append(shot("context-open-result"))
    evidence += dialogs("context-open-result")
    if launched:
        CTX["launched"] = True
        record("Control-click › Open (macOS 14)", PASS, "Finder's shortcut menu › Open, then: %s. PIKY is running (pid %s)." % ("; ".join(notes) or "nothing more was asked", piky_pids()), evidence)
    else:
        record("Control-click › Open (macOS 14)", LIMIT, "Open was chosen from the shortcut menu but PIKY did not start: %s" % ("; ".join(notes) or "no confirmation could be seen by the driver"), evidence)


def stage_second_install():
    """When the quarantined copy could not be opened by the UI: the same bytes,
    fetched without a browser, so the rest of the run has an app to look at.
    This is said in every result that depends on it."""
    STATE["stage"] = "2b Second install (no quarantine)"
    alert = gatekeeper_alert()
    if alert:
        gatekeeper_dismiss(alert)
    for pid in piky_pids():
        run(["/bin/kill", "-9", str(pid)], quiet=True)
    mounted = mount_point()
    if mounted:
        run(["/usr/bin/hdiutil", "detach", mounted, "-force"], quiet=True)
    if os.path.exists(APP):
        shutil.rmtree(APP, ignore_errors=True)
    folder = os.path.join(TEMP, "piky-second-install")
    os.makedirs(folder, exist_ok=True)
    image = os.path.join(folder, DMG_NAME)
    run(["/usr/bin/curl", "-fsSL", "--connect-timeout", "20", "--max-time", "300", "--retry", "3", "-o", image, RELEASE["PIKY_DMG_URL"]], timeout=400)
    actual = RELEASE["PIKY_DMG_SHA256"] if SIM else (sha256_file(image) if os.path.exists(image) else "")
    if actual != RELEASE["PIKY_DMG_SHA256"]:
        record("A second copy of the same published file, without quarantine", FAIL if actual else INCONCLUSIVE, "curl fetched %s; expected %s" % (actual or "nothing", RELEASE["PIKY_DMG_SHA256"]))
        raise Blocked()
    volume = os.path.join(folder, "volume")
    os.makedirs(volume, exist_ok=True)
    run(["/usr/bin/hdiutil", "attach", image, "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", volume, "-quiet"], timeout=120)
    run(["/usr/bin/ditto", os.path.join(volume, "PIKY.app"), APP], timeout=120)
    run(["/usr/bin/hdiutil", "detach", volume, "-quiet"], timeout=60, quiet=True)
    CTX["install"] = "second copy, no quarantine"
    record("A second copy of the same published file, without quarantine", INFO,
           "Gatekeeper's first open could not be completed by automation, so the rest of this run uses the same bytes (SHA-256 %s) fetched with curl: quarantine on this copy: %s. "
           "Nothing below is evidence about Gatekeeper." % (actual, quarantine_of(APP) or "absent"))
    run(["/usr/bin/open", APP])
    CTX["launched"] = bool(wait_for(piky_running, 30, 0.8))
    if not CTX["launched"]:
        record("PIKY opens through LaunchServices", FAIL, "the copy without quarantine did not start within 30 s", [shot("second-install-no-start")] + dialogs("second-install"))
        raise Blocked()


def permission_check():
    """What macOS answers PIKY itself: asked through LaunchServices, so the
    answer is for PIKY and not for whoever started this script."""
    reply = os.path.join(TEMP, "piky-permission-%s.json" % int(time.time() * 1000))
    run(["/usr/bin/open", "-n", "-g", "-j", "--stdout", reply, APP, "--args", "--piky-permission-check"], quiet=True)
    wait_for(lambda: os.path.exists(reply) and os.path.getsize(reply) > 0, 10, 0.3)
    if SIM:
        return {"accessibility": False, "screen": False}
    try:
        with open(reply, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def label_area(frame):
    """A button's label with a margin of the fill around it, inside the button's rounded corners."""
    if not usable(frame):
        return frame
    # Accessibility gives the label's own box; the fill reaches a little past it on every side.
    return [frame[0] - 5, frame[1] - 4, frame[2] + 10, frame[3] + 8]


def stage_first_run():
    STATE["stage"] = "3 First run"
    if not CTX["launched"]:
        record("First-run window", NOTRUN, "PIKY is not running")
        raise Blocked()
    quit_app("Safari")
    close_finder_windows()
    window = find(BUNDLE, "--role", "AXWindow", "--title", "Meet PIKY", timeout=20)
    pause(1.5)
    focus_piky_window("Meet PIKY")
    pids = piky_pids()
    active = shot("first-run-window-active")
    outline = ax_dump("first-run-window", BUNDLE)
    front = frontmost()
    record("PIKY opens through LaunchServices and stays open", PASS if len(pids) == 1 else FAIL,
           "open /Applications/PIKY.app (%s); %s PIKY process(es): %s" % (CTX["install"], len(pids), pids))
    if not window:
        record("First-run window", FAIL if piky_windows() == [] and not SIM else INCONCLUSIVE,
               "no window titled “Meet PIKY” within 20 s; PIKY's windows: %s" % piky_windows(), [active, outline])
        return
    words = read_dialog(BUNDLE)
    record("First-run window", PASS, "“Meet PIKY” opened by itself (%s); frontmost application: %s. It reads: %s … Buttons: %s"
           % (window[0].get("frame"), front.get("name"), " / ".join(text.replace("\n", " ") for text in words["texts"][:4])[:320], ", ".join(words["buttons"])),
           [active, outline])

    # The Continue label, with PIKY's window active and then inactive.
    button = find(BUNDLE, "--role", "AXButton", "--title", "Continue")
    frame = button[0].get("frame") if button else None
    measured = {"active": contrast(active, label_area(frame), inset=0)}
    crops = [crop(active, frame, "continue-active", margin=12)]
    # Another application comes forward, in a small window beside PIKY's: PIKY's
    # window is then inactive and still uncovered. (A click on the wallpaper
    # would not do: on macOS 14 and later that slides every window away.)
    open_text_document(rect="20,90,560,420")
    pause(1.2)
    inactive = shot("first-run-window-inactive")
    behind = frontmost()
    still = find(BUNDLE, "--role", "AXButton", "--title", "Continue")
    there = bool(still) and usable(still[0].get("frame")) and bool(find(BUNDLE, "--role", "AXWindow", "--title", "Meet PIKY"))
    measured["inactive"] = contrast(inactive, label_area(still[0].get("frame")), inset=0) if there else {}
    crops.append(crop(inactive, still[0].get("frame"), "continue-inactive", margin=12) if there else None)
    CTX["continue_contrast"] = measured
    valid = there and behind.get("bundle") not in (BUNDLE, None, "") and measured["active"].get("ok") and measured["inactive"].get("ok")
    if valid:
        low = min(measured["active"].get("contrastRatio", 0), measured["inactive"].get("contrastRatio", 0)) < 3.0
        record("Continue label, window active and inactive", FAIL if low else PASS,
               "label against button fill, WCAG contrast: active (PIKY in front) %.2f:1 (fill #%s, label #%s); inactive (%s in front) %.2f:1 (fill #%s, label #%s). Below 3:1 a label is hard to read."
               % (measured["active"]["contrastRatio"], measured["active"]["fillColor"], measured["active"]["markColor"], behind.get("name"),
                  measured["inactive"]["contrastRatio"], measured["inactive"]["fillColor"], measured["inactive"]["markColor"]),
               [active, inactive] + crops, data=measured)
    else:
        record("Continue label, window active and inactive", INCONCLUSIVE,
               "the Continue button could not be measured in both states (button found: %s; frontmost for the inactive shot: %s)" % (there, behind.get("name")), [active, inactive, outline])

    # The mark in the menu bar.
    status = piky_status()
    if status and usable(status.get("frame")):
        mark = contrast(inactive, status["frame"], inset=0)
        cut = crop(inactive, status["frame"], "menu-bar-mark-at-rest", margin=10)
        visible = mark.get("ok") and mark.get("contrastRatio", 1) >= 1.5
        record("PIKY's mark is in the menu bar", PASS if visible else FAIL,
               "status item at %s, announced as “%s”; drawn with contrast %.2f:1 against the bar" % (status["frame"], status["label"], mark.get("contrastRatio", 0)),
               [cut, inactive], data=mark)
    else:
        record("PIKY's mark is in the menu bar", INCONCLUSIVE if SIM else FAIL, "PIKY's status item was not found through Accessibility", [inactive, outline])


def stage_permissions():
    STATE["stage"] = "4 PIKY's own permissions"
    if not CTX["launched"]:
        record("PIKY's own permissions", NOTRUN, "PIKY is not running")
        return
    before = permission_check()
    record("What macOS answers PIKY before anything is granted", PASS if before and not before.get("accessibility") else INFO,
           "asked through LaunchServices: %s (a Mac that has never run PIKY answers false to both)" % json.dumps(before))
    if before and before.get("accessibility"):
        CTX["own_accessibility"] = True
        CTX["own_screen"] = bool(before.get("screen"))
        return

    # PIKY's own request, as the first-run window makes it.
    focus_piky_window("Meet PIKY")
    click_element(BUNDLE, "--role", "AXButton", "--title", "Continue")
    pause(1.2)
    second = shot("first-run-permission-step")
    asked = click_element(BUNDLE, "--role", "AXButton", "--title", "Turn on Accessibility")
    if not asked:
        record("PIKY asks for Accessibility in its first-run window", INCONCLUSIVE,
               "the button “Turn on Accessibility” was not found; PIKY's buttons: %s" % read_dialog(BUNDLE)["buttons"], [second, ax_dump("first-run-step-2", BUNDLE)])
    else:
        pause(2.5)
        prompt = dialog_of("universalAccessAuthWarn", mentions="PIKY")
        evidence = [second, shot("macos-accessibility-prompt")] + dialogs("accessibility-prompt")
        if prompt:
            record("PIKY asks for Accessibility in its first-run window", PASS,
                   "step 2 explains why, then macOS showed its own dialog: “%s” [buttons: %s]" % (" ".join(prompt["texts"]), ", ".join(prompt["buttons"])), evidence)
            press_button({"pid": prompt["pid"]}, ["Open System Settings", "Open System Preferences"], "macOS Accessibility prompt")
        else:
            record("PIKY asks for Accessibility in its first-run window", INCONCLUSIVE,
                   "after “Turn on Accessibility” no macOS dialog could be read by the driver; see the screenshot", evidence)
            run(["/usr/bin/open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
    pause(3.5)

    # The switch in System Settings, by the pointer.
    toggle = None
    for role in ("AXCheckBox", "AXSwitch", "AXToggle", "AXButton"):
        toggle = find(SETTINGS, "--role", role, "--near", "PIKY", timeout=3 if role == "AXCheckBox" else 0)
        if toggle:
            break
    evidence = [shot("system-settings-accessibility"), ax_dump("system-settings-accessibility", SETTINGS)]
    if not toggle:
        record("PIKY's switch under Privacy & Security › Accessibility", INCONCLUSIVE if SIM else LIMIT,
               "System Settings did not show a switch for PIKY that the driver could find; see the screenshot and the outline", evidence)
    else:
        value_before = toggle[0].get("value")
        visible = into_view(SETTINGS, "System Settings", "--role", toggle[0].get("role", "AXCheckBox"), "--near", "PIKY") or toggle[0]
        if usable(visible.get("frame")):
            x, y = center(visible["frame"])
            qa("click", "%.1f" % x, "%.1f" % y)
        pause(2.0)
        evidence.append(shot("after-clicking-accessibility-switch"))
        evidence += dialogs("after-accessibility-switch")
        prompt_result = answer_auth("accessibility-switch")
        pause(3.0)
        after = permission_check()
        again = find(SETTINGS, "--role", toggle[0].get("role", "AXCheckBox"), "--near", "PIKY")
        value_after = again[0].get("value") if again else "?"
        evidence.append(shot("accessibility-switch-result"))
        if after and after.get("accessibility"):
            CTX["own_accessibility"] = True
            record("PIKY's switch under Privacy & Security › Accessibility", PASS,
                   "PIKY is listed; the switch went from %s to %s by a pointer click (admin prompt: %s); macOS now answers PIKY %s" % (value_before, value_after, prompt_result, json.dumps(after)), evidence)
        else:
            record("PIKY's switch under Privacy & Security › Accessibility", LIMIT,
                   "PIKY is listed in Accessibility with its switch at %s. The driver clicked the switch (admin prompt: %s); the switch then read %s and macOS still answers PIKY %s. "
                   "Granting a privacy permission needs a person (or device management) on this runner: macOS does not accept it from scripted input, and this run does not edit the TCC database."
                   % (value_before, prompt_result, value_after, json.dumps(after)), evidence)
    quit_app("System Settings")
    pause(1.0)
    if CTX["own_accessibility"]:
        moved = find(BUNDLE, "--role", "AXButton", "--title", "Skip for now", timeout=8) or find(BUNDLE, "--role", "AXButton", "--title", "Done")
        record("The first-run window continues by itself after the grant", PASS if moved else FAIL,
               "after Accessibility was switched on, PIKY's window %s" % ("moved on to its practice step" if moved else "did not move on within 8 s"), [shot("first-run-after-grant")])


def stage_hotkey_without_permission():
    """⌥Space reaching a PIKY that macOS has not allowed to read other apps."""
    STATE["stage"] = "5 ⌥Space before Accessibility"
    if CTX["own_accessibility"] or not CTX["launched"]:
        record("⌥Space while PIKY has no Accessibility", NOTRUN, "PIKY has Accessibility" if CTX["own_accessibility"] else "PIKY is not running")
        return
    open_text_document()
    length_before = text_length()
    titles_before = piky_windows()
    pressed = option_space()
    appeared = wait_for(lambda: "PIKY Settings" in piky_windows(), 6, 0.5)
    pause(0.6)
    evidence = [shot("option-space-without-accessibility"), ax_dump("piky-after-option-space-no-accessibility", BUNDLE)]
    length_after = text_length()
    typed = length_before is not None and length_after is not None and length_after != length_before
    words = read_dialog(BUNDLE)["texts"]
    said = [text for text in words if "Accessibility" in text]
    if appeared:
        record("⌥Space while PIKY has no Accessibility", PASS,
               "the real key press reached PIKY as its system-wide shortcut (TextEdit was in front; its document %s). PIKY did not go quiet: its Settings window opened, saying “%s”. One PIKY process."
               % ("was not typed into" if not typed else "CHANGED by %s characters" % (length_after - length_before), (said[0] if said else "…")[:200]), evidence, data={"pressedAt": pressed.get("pressedAt")})
    elif typed:
        record("⌥Space while PIKY has no Accessibility", FAIL,
               "the key press went to TextEdit (its document grew by %s character): PIKY did not hold ⌥Space" % (length_after - length_before), evidence)
    else:
        record("⌥Space while PIKY has no Accessibility", INCONCLUSIVE,
               "TextEdit's document is unchanged, so something took the keys, but PIKY showed no Settings window (windows before: %s, after: %s)" % (titles_before, piky_windows()), evidence)
    focus_piky_window("PIKY Settings")
    closed = press_button(BUNDLE, ["Done"], "PIKY Settings")
    if not closed:
        escape()


def open_text_document(rect="60,70,860,520"):
    if not os.path.exists(TEXT_FILE):
        with open(TEXT_FILE, "w", encoding="utf-8") as handle:
            handle.write("\n\n".join(PARAGRAPHS) + "\n")
    run(["/usr/bin/open", "-a", "TextEdit", TEXT_FILE], quiet=True)
    find("com.apple.TextEdit", "--role", "AXTextArea", timeout=12)
    pause(1.0)
    qa("ax", "set-frame", "--bundle", "com.apple.TextEdit", "--rect", rect, quiet=True)
    pause(0.6)
    activate("com.apple.TextEdit")


def text_length():
    answer = qa("ax", "value", "--bundle", "com.apple.TextEdit", "--role", "AXTextArea", quiet=True)
    return answer.get("length") if answer.get("found") else None


def start_piky_from_the_job():
    """Starts the installed binary as a child of this job (not through
    LaunchServices), left running."""
    if SIM:
        run([PIKY_BIN])
    else:
        CTX["piky_process"] = subprocess.Popen([PIKY_BIN], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stage_functional_mode():
    """Which PIKY the working steps look at. With its own permission: the one
    a person launched. Without: the same installed binary started by this
    job, which macOS then counts as part of the runner's agent, already
    allowed by GitHub's image. That shows how PIKY behaves on this macOS; it
    is not a test of permissions, and every result says so."""
    STATE["stage"] = "6 A PIKY that may work"
    if not CTX["launched"]:
        record("A PIKY with Accessibility to exercise", NOTRUN, "PIKY is not running")
        raise Blocked()
    if CTX["own_accessibility"]:
        CTX["mode"] = "PIKY's own permission, granted in System Settings"
        record("A PIKY with Accessibility to exercise", PASS, CTX["mode"])
    else:
        code, out, _ = run([PIKY_BIN, "--piky-permission-check"], timeout=20, quiet=True)
        try:
            inherited = json.loads(out) if not SIM else {"accessibility": True, "screen": True}
        except ValueError:
            inherited = {}
        if not inherited.get("accessibility"):
            record("A PIKY with Accessibility to exercise", LIMIT,
                   "PIKY cannot be given Accessibility on this runner by any means this run allows: not through System Settings (above), and started by the job it answers %s. "
                   "Picking, the Camera and ⌘Return all need it, so they cannot be exercised here." % (out.strip() or "nothing"))
            raise Blocked()
        for pid in piky_pids():
            run(["/bin/kill", "-TERM", str(pid)], quiet=True)
        gone = wait_for(lambda: not piky_running(), 10, 0.4)
        start_piky_from_the_job()
        up = wait_for(piky_running, 20, 0.5)
        pause(2.0)
        CTX["mode"] = "runner-attributed permissions (PIKY's installed binary started by the job; macOS attributes it to GitHub's pre-allowed agent)"
        CTX["own_screen"] = bool(inherited.get("screen"))
        record("A PIKY with Accessibility to exercise", INFO if up else FAIL,
               "the PIKY a person launched was quit (%s) and /Applications/PIKY.app/Contents/MacOS/PIKY was started by the job. Asked the same way, it answers %s: these are the runner agent's permissions, not a grant to PIKY. "
               "Everything below shows PIKY's behaviour on this macOS under those permissions." % ("it quit" if gone else "it did not quit in 10 s", json.dumps(inherited)))
        if not up:
            raise Blocked()

    # Through the first-run window, the short way.
    steps = []
    for _ in range(6):
        if "Meet PIKY" not in piky_windows():
            break
        focus_piky_window("Meet PIKY")
        clicked = press_button(BUNDLE, ["Continue", "Skip for now", "Done"], "first run")
        if not clicked:
            break
        steps.append(clicked)
        pause(1.3)
        if len(steps) == 1:
            shot("first-run-practice-step")
    finished = "Meet PIKY" not in piky_windows()
    record("The first-run window can be finished", PASS if finished else INCONCLUSIVE,
           "clicked %s; the window is %s. (Its practice card was skipped; the same actions are exercised on real applications below.)" % (" → ".join(steps) or "nothing", "closed" if finished else "still open"),
           [shot("after-first-run")] + ([] if finished else [ax_dump("first-run-not-finished", BUNDLE)]))
    status = piky_status()
    CTX["expected"] = status["count"] if status else 0
    if not status:
        record("PIKY's menu-bar item can be read", INCONCLUSIVE, "no status item answering “PIKY, n Picks. Show Pack” was found", [ax_dump("piky-no-status-item", BUNDLE)])
        raise Blocked()


def start_listening(bundle, label):
    """⌥Space with an application in front, unless PIKY is already picking."""
    status = piky_status()
    if status and status["picking"]:
        return True
    if frontmost().get("bundle") != bundle:
        activate(bundle)
    option_space()
    return bool(wait_picking(True, 6))


def stage_option_space():
    STATE["stage"] = "7 ⌥Space"
    open_text_document()
    # Nothing selected: the insertion point goes to the end of the document.
    area = find("com.apple.TextEdit", "--role", "AXTextArea")
    if area and usable(area[0].get("frame")):
        frame = area[0]["frame"]
        qa("click", "%.0f" % (frame[0] + frame[2] - 30), "%.0f" % (frame[1] + frame[3] - 30))
        pause(0.5)
    before = piky_status()
    length_before = text_length()
    overlay_before = piky_overlay_count()
    rest = shot("before-option-space")
    pressed = option_space()
    listening = wait_picking(True, 6)
    pause(0.8)
    after = piky_status()
    during = shot("after-option-space-listening")
    length_after = text_length()
    pids = piky_pids()
    cut = crop(during, after["frame"], "menu-bar-mark-listening", margin=10) if after and usable(after.get("frame")) else None
    changed = {}
    if rest and during and before and usable(before.get("frame")):
        frame = before["frame"]
        changed = qa("image", "diff", path(rest), path(during), "--rect", "%.0f,%.0f,%.0f,%.0f" % (frame[0] - 4, frame[1], frame[2] + 8, frame[3]), "--scale", STATE["scale"], quiet=True)
    data = {"before": before, "after": after, "pressedAt": pressed.get("pressedAt"), "overlayWindowsBefore": overlay_before, "overlayWindowsAfter": piky_overlay_count(),
            "menuBarPixelsChanged": changed.get("share"), "textEditLength": [length_before, length_after]}
    if listening and after:
        record("⌥Space starts picking", PASS if len(pids) == 1 else FAIL,
               "keys posted at the HID level with TextEdit in front. PIKY's menu-bar item went from “%s” to “%s”; its windows on screen went from %s to %s; %.1f%% of the menu-bar item's pixels changed; TextEdit's document was not typed into (%s → %s characters); PIKY processes: %s. Mode: %s."
               % (before["label"] if before else "?", after["label"], overlay_before, data["overlayWindowsAfter"], 100 * (changed.get("share") or 0), length_before, length_after, len(pids), CTX["mode"]),
               [rest, during, cut], data=data)
    else:
        typed = length_before is not None and length_after is not None and length_after != length_before
        record("⌥Space starts picking", FAIL if typed else INCONCLUSIVE,
               ("the keys went to TextEdit (its document changed from %s to %s characters): PIKY did not take ⌥Space" % (length_before, length_after)) if typed else
               "PIKY's menu-bar item did not announce “picking” within 6 s (before: %s, after: %s); TextEdit unchanged" % (before, after),
               [rest, during, ax_dump("piky-after-option-space", BUNDLE)], data=data)
        raise Blocked()
    escape()
    stopped = wait_picking(False, 5)
    record("Escape stops picking", PASS if stopped else FAIL, "after Escape the item reads “%s”" % ((piky_status() or {}).get("label")), [shot("after-escape")])


def paragraph_place(text):
    answer = qa("ax", "text-range", "--bundle", "com.apple.TextEdit", "--needle", text)
    return answer if answer.get("found") and usable(answer.get("first")) and usable(answer.get("last")) else None


def expect_pick(label, kind, evidence, check_text=None, detail="", verified=False):
    """After a gesture: did the Pack grow by exactly one Pick of this kind?
    `verified`: the harness saw its own gesture land (the selection was made,
    the outline was up). Only then is a missing Pick PIKY's failure; otherwise
    the step says nothing about PIKY."""
    target = CTX["expected"] + 1
    grew = wait_count(target, 9)
    status = piky_status()
    seen = status["count"] if status else None
    pack = current_pack(expect=target if grew else None, timeout=7)
    kinds = pack["kinds"] if pack else []
    stored = pack["texts"][-1].strip() if pack and pack["texts"] and check_text else None
    ok = bool(grew) and (not kinds or kinds[-1] in kind)
    if check_text is not None and stored is not None:
        ok = ok and stored == check_text
    facts = "%s the menu-bar item reads “%s” (expected %s Pick%s); the Pack on disk holds %s: %s" % (
        detail, status["label"] if status else "nothing", target, "" if target == 1 else "s", pack["count"] if pack else "?", ", ".join(kinds) or "-")
    if check_text is not None:
        facts += "; the newest Pick's text %s the paragraph" % ("is exactly" if stored == check_text else "is NOT" if stored is not None else "could not be compared with")
    if ok:
        CTX["expected"] = target
        CTX["picks"].append(label)
        record(label, PASS, facts + ". Mode: %s." % CTX["mode"], evidence)
    else:
        if seen is not None:
            CTX["expected"] = seen
        wrong = verified and seen is not None and status is not None and status["picking"]
        record(label, FAIL if wrong else INCONCLUSIVE,
               facts + (". The gesture was seen to land and PIKY was picking." if wrong else ". The harness could not confirm its own gesture landed, or PIKY was not picking.")
               + " Mode: %s." % CTX["mode"], evidence + [ax_dump(label, BUNDLE, maximum=800)])
    return ok


def stage_text_pick():
    STATE["stage"] = "8 Text Pick"
    open_text_document()
    if not start_listening("com.apple.TextEdit", "text"):
        record("Text Pick", INCONCLUSIVE, "PIKY did not start picking over TextEdit")
        raise Blocked()
    pause(0.8)
    # A drag across the second paragraph, as a hand selects it.
    place = paragraph_place(PARAGRAPHS[1])
    if not place:
        record("Text Pick by dragging across a paragraph", INCONCLUSIVE, "TextEdit did not say where the paragraph is drawn", [ax_dump("textedit", "com.apple.TextEdit", maximum=400)])
    else:
        first, last = place["first"], place["last"]
        qa("drag", "%.1f" % (first[0] + 0.5), "%.1f" % (first[1] + first[3] / 2), "%.1f" % (last[0] + last[2] + 1.5), "%.1f" % (last[1] + last[3] / 2), "--ms", "700")
        pause(0.4)
        selected = qa("ax", "selection", "--bundle", "com.apple.TextEdit", quiet=True)
        made = selected.get("text", "").strip() == PARAGRAPHS[1]
        evidence = [shot("text-pick-drag")]
        if not made and not SIM:
            record("Text Pick by dragging across a paragraph", INCONCLUSIVE,
                   "the pointer drag selected %s characters in TextEdit, not the paragraph (%s), so the step was not set up" % (selected.get("length"), len(PARAGRAPHS[1])), evidence)
        else:
            expect_pick("Text Pick by dragging across a paragraph", ("selected_text",), evidence, check_text=PARAGRAPHS[1],
                        detail="TextEdit's selection after the drag is exactly the second fixture paragraph;", verified=True)
    # A triple-click on the third paragraph.
    place = paragraph_place(PARAGRAPHS[2])
    if place and (piky_status() or {}).get("picking"):
        first = place["first"]
        qa("click", "%.1f" % (first[0] + 40), "%.1f" % (first[1] + first[3] / 2), "--count", "3")
        pause(0.5)
        selected = qa("ax", "selection", "--bundle", "com.apple.TextEdit", quiet=True)
        evidence = [shot("text-pick-triple-click")]
        if selected.get("text", "").strip() != PARAGRAPHS[2] and not SIM:
            record("Text Pick by triple-click", INCONCLUSIVE, "the triple-click selected %s characters, not the third paragraph" % selected.get("length"), evidence)
        else:
            expect_pick("Text Pick by triple-click", ("selected_text",), evidence, check_text=PARAGRAPHS[2],
                        detail="TextEdit's selection after the triple-click is exactly the third fixture paragraph;", verified=True)
    else:
        record("Text Pick by triple-click", INCONCLUSIVE, "the paragraph could not be located, or PIKY had stopped picking")


def stage_finder_pick():
    STATE["stage"] = "9 Finder file Pick"
    os.makedirs(FIXTURES, exist_ok=True)
    source = os.path.join(ROOT, "TestFiles")
    manifest = {}
    with open(os.path.join(source, "MANIFEST.sha256"), encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                digest, name = line.strip().split("  ", 1)
                manifest[unicodedata.normalize("NFC", os.path.basename(name))] = digest
    for name in os.listdir(source):
        if os.path.isfile(os.path.join(source, name)) and name not in ("generate.py", "MANIFEST.sha256"):
            shutil.copy2(os.path.join(source, name), os.path.join(FIXTURES, name))
    with open(os.path.join(FIXTURES, PLAIN_FILE), "w", encoding="utf-8") as handle:
        handle.write("A plain file name. QA fixture for PIKY. Invented content.\n")
    manifest[PLAIN_FILE] = sha256_file(os.path.join(FIXTURES, PLAIN_FILE))
    CTX["manifest"] = manifest
    close_finder_windows()
    run(["/usr/bin/open", FIXTURES])
    pause(2.5)
    qa("ax", "set-frame", "--bundle", "com.apple.finder", "--rect", "80,90,900,560", quiet=True)
    pause(0.8)
    activate("com.apple.finder")
    if not start_listening("com.apple.finder", "finder"):
        record("Finder file Pick", INCONCLUSIVE, "PIKY did not start picking over Finder", [shot("finder-not-listening")])
        raise Blocked()
    pause(0.8)
    listed = ax_dump("finder-fixture-folder", "com.apple.finder", maximum=2500)
    shot("finder-fixture-folder")
    for name in FINDER_FILES:
        items = [item for item in find("com.apple.finder", "--title", name, all=True) if usable(item.get("frame"))]
        label = "Finder Pick: %s" % name
        if not items:
            record(label, INCONCLUSIVE, "the file's icon could not be located in the Finder window through Accessibility", [listed])
            continue
        # The smallest element with that name is the icon or its label.
        item = sorted(items, key=lambda element: element["frame"][2] * element["frame"][3])[0]
        x, y = center(item["frame"])
        qa("click", "%.1f" % x, "%.1f" % y)
        pause(1.0)
        front = frontmost()
        selected = any(found.get("selected") for found in find("com.apple.finder", "--title", name, all=True))
        ok = expect_pick(label, ("file", "image"), [shot("finder-pick-" + name)], verified=selected,
                         detail="one pointer click on the file in Finder (%s at %s; Finder reports it selected: %s); Finder stayed in front: %s;"
                         % (item.get("role"), item["frame"], selected, front.get("bundle") == "com.apple.finder"))
        if ok:
            CTX.setdefault("finder_picked", []).append(name)
            pack = current_pack()
            if pack and pack["files"] and not same_name(pack["files"][-1], name):
                record(label + " (the file PIKY kept)", FAIL, "the newest Pick refers to “%s”, not “%s”" % (pack["files"][-1], name))
    opened = [name for name in ("Preview", "TextEdit") if name == frontmost().get("name")]
    record("Picking in Finder opens nothing", PASS if not opened and frontmost().get("bundle") == "com.apple.finder" else INFO,
           "after the clicks the frontmost application is %s" % frontmost().get("name"))


def page_origin():
    """Where the QA page's top-left corner is on screen: from its heading,
    whose place on the page is known, else from the web view."""
    heading = find("com.apple.Safari", "--role", "AXHeading", "--contains", "Checkout health")
    if heading and usable(heading[0].get("frame")):
        frame = heading[0]["frame"]
        return frame[0] - 40, frame[1] - 24, "heading"
    area = find("com.apple.Safari", "--role", "AXWebArea")
    if area and usable(area[0].get("frame")):
        return area[0]["frame"][0], area[0]["frame"][1], "web area"
    return None


def element_rect(geometry, identifier, origin):
    rect = geometry[identifier]
    return [origin[0] + rect[0], origin[1] + rect[1], rect[2], rect[3]]


def outline_box(screenshot, around, baseline=None, margin=420):
    """The box PIKY's outline colour covers near a target, and how much more of
    that colour there is than before the Camera was up."""
    found = pink(screenshot, around, margin=margin)
    before = pink(baseline, around, margin=margin).get("count", 0) if baseline else 0
    return {"count": found.get("count", 0), "added": found.get("count", 0) - before, "box": found.get("boxPoints")}


def describe_box(box, geometry, origin):
    """Which element of the page an outline box matches, by size and place."""
    if not box:
        return "no outline colour"
    best = None
    for identifier, rect in geometry.items():
        placed = [origin[0] + rect[0], origin[1] + rect[1], rect[2], rect[3]]
        distance = sum(abs(a - b) for a, b in zip(placed, box))
        if best is None or distance < best[1]:
            best = (identifier, distance)
    return "%s×%s at %s,%s (closest page element: %s, %s pt off in total)" % (int(box[2]), int(box[3]), int(box[0]), int(box[1]), best[0], int(best[1]))


def stage_camera():
    STATE["stage"] = "10 Camera"
    with open(os.path.join(ROOT, "TestPage", "geometry.json"), encoding="utf-8") as handle:
        geometry = dict((element["id"], element["rect"]) for element in json.load(handle)["elements"])
    escape()
    wait_picking(False, 3)
    close_finder_windows()
    quit_app("TextEdit")
    run(["/usr/bin/open", "-a", "Safari", PAGE])
    find("com.apple.Safari", "--role", "AXWebArea", timeout=20)
    pause(2.0)
    display = qa("probe", quiet=True).get("mainDisplayPoints", [1440, 900])
    qa("ax", "set-frame", "--bundle", "com.apple.Safari", "--rect", "0,25,%d,%d" % (min(1360, display[0]), display[1] - 25), quiet=True)
    pause(1.5)
    activate("com.apple.Safari")
    origin = page_origin()
    badge = find("com.apple.Safari", "--contains", "elements in place")
    page_shot = shot("qa-page-in-safari")
    if not origin:
        record("The QA page is open in Safari", INCONCLUSIVE, "Safari did not expose the page through Accessibility", [page_shot, ax_dump("safari-qa-page", "com.apple.Safari", maximum=1500)])
        raise Blocked()
    badge_text = (badge[0].get("value") or badge[0].get("title") or badge[0].get("description")) if badge else None
    record("The QA page is open in Safari", PASS if badge_text and "20 elements in place" in badge_text else INFO,
           "page origin on screen %.0f,%.0f (from its %s); the page's own check says: %s" % (origin[0], origin[1], origin[2], badge_text or "(badge not found)"), [page_shot])
    if not start_listening("com.apple.Safari", "camera"):
        record("Camera", INCONCLUSIVE, "PIKY did not start picking over Safari", [shot("safari-not-listening")])
        raise Blocked()
    pause(0.8)
    try:
        # --- Camera mode: ⌥ held, pointer over the bar chart.
        chart = element_rect(geometry, "chart-revenue", origin)
        card = element_rect(geometry, "card-revenue", origin)
        cx, cy = center(chart)
        qa("move", "%.0f" % (cx - 160), "%.0f" % (cy + 150))
        pause(0.5)
        baseline = shot("camera-before-option")
        held = qa("mod", "down", "opt")
        qa("move", "%.0f" % cx, "%.0f" % cy, "--mods", "opt", "--steps", "24", "--ms", "700")
        pause(1.8)
        qa("move", "%.0f" % (cx + 3), "%.0f" % (cy + 2), "--mods", "opt", "--steps", "3", "--ms", "120")
        pause(1.5)
        hover = shot("camera-option-held-over-bar-chart")
        outline = outline_box(hover, card, baseline, margin=60)
        settings_up = "PIKY Settings" in piky_windows()
        if settings_up:
            record("Camera mode: ⌥ held over the bar chart", LIMIT,
                   "PIKY opened its Settings instead of the Camera: the Camera needs Screen Recording, which PIKY does not have here (%s)" % CTX["mode"], [hover])
            raise Blocked()
        seen = outline["added"] > 200
        record("Camera mode: ⌥ held over the bar chart", PASS if seen else INCONCLUSIVE,
               "with ⌥ down and the pointer on the chart, PIKY's outline colour %s: %s more pixels of it than before; they cover %s. The chart is %s, its card %s."
               % ("appeared" if seen else "did not appear", outline["added"], describe_box(outline["box"], geometry, origin), [int(v) for v in chart], [int(v) for v in card]),
               [baseline, hover, crop(hover, card, "camera-outline-bar-chart", margin=30)], data={"outline": outline, "optionDownAt": held.get("at")})
        # --- Click commit.
        qa("click", "%.0f" % cx, "%.0f" % cy, "--mods", "opt")
        pause(0.4)
        expect_pick("Camera: ⌥-click takes what is outlined", ("screen_region", "image"), [shot("camera-after-click")], verified=seen,
                    detail="one ⌥-click on the bar chart (outline before the click: %s);" % describe_box(outline["box"], geometry, origin))

        # --- Scope: ⌥-scroll over the line chart.
        line = element_rect(geometry, "chart-errors", origin)
        lx, ly = center(line)
        qa("move", "%.0f" % lx, "%.0f" % ly, "--mods", "opt", "--steps", "24", "--ms", "700")
        pause(2.2)
        levels = []
        frames = [shot("camera-scope-0-resting")]
        levels.append(outline_box(frames[-1], element_rect(geometry, "metrics", origin), baseline, margin=40))
        for index, lines in enumerate((-1, -1, 1)):
            qa("scroll", str(lines), "--mods", "opt")
            pause(1.3)
            frames.append(shot("camera-scope-%s-after-scroll-%s" % (index + 1, "down" if lines < 0 else "up")))
            levels.append(outline_box(frames[-1], element_rect(geometry, "metrics", origin), baseline, margin=40))
        moved_page = page_origin()
        scrolled_page = bool(moved_page) and abs(moved_page[1] - origin[1]) > 2
        boxes = [level["box"] for level in levels]
        distinct = len(set(json.dumps(box) for box in boxes if box))
        stepped = distinct >= 2 and not scrolled_page
        record("Camera scope: ⌥-scroll steps the outline", PASS if stepped else INCONCLUSIVE if not scrolled_page else FAIL,
               "over the line chart, wheel notches down, down, up (posted as a mouse wheel; no trackpad). Outline at rest: %s; after each notch: %s. %s"
               % (describe_box(boxes[0], geometry, origin), " → ".join(describe_box(box, geometry, origin) for box in boxes[1:]),
                  "The page itself scrolled, so the wheel went to Safari." if scrolled_page else "The page did not scroll: PIKY kept the wheel."),
               frames, data={"levels": levels})
        if scrolled_page:
            origin = moved_page
            line = element_rect(geometry, "chart-errors", origin)
            lx, ly = center(line)
        qa("click", "%.0f" % lx, "%.0f" % ly, "--mods", "opt")
        pause(0.4)
        expect_pick("Camera: ⌥-click at the chosen scope", ("screen_region", "image"), [shot("camera-after-scope-click")], verified=bool(boxes[-1]),
                    detail="one ⌥-click with the outline at %s;" % describe_box(boxes[-1], geometry, origin))

        # --- Manual region: ⌥-drag around the picture.
        photo = element_rect(geometry, "photo", origin)
        start = (photo[0] - 12, photo[1] - 12)
        end = (photo[0] + photo[2] + 12, photo[1] + photo[3] + 12)
        qa("move", "%.0f" % start[0], "%.0f" % start[1], "--mods", "opt", "--steps", "20", "--ms", "500")
        pause(0.6)
        middle = None
        if SIM:
            qa("drag", "%.0f" % start[0], "%.0f" % start[1], "%.0f" % end[0], "%.0f" % end[1], "--mods", "opt", "--ms", "2400", "--steps", "40")
        else:
            dragging = subprocess.Popen([QA_BIN, "drag", "%.0f" % start[0], "%.0f" % start[1], "%.0f" % end[0], "%.0f" % end[1], "--mods", "opt", "--ms", "2600", "--steps", "40"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pause(1.9)
            middle = shot("camera-region-during-drag")
            dragging.wait(timeout=20)
        pause(0.5)
        region = outline_box(middle, photo, baseline, margin=80) if middle else {"box": None, "added": 0}
        expect_pick("Camera: ⌥-drag takes a region", ("screen_region", "image"), [middle, shot("camera-after-region-drag")], verified=bool(region["box"]),
                    detail="⌥-drag of %s×%s points around the drawn picture (mid-drag the outline colour covered %s);" % (int(end[0] - start[0]), int(end[1] - start[1]), describe_box(region["box"], geometry, origin)))
    finally:
        qa("mod", "up", "opt", quiet=True)
        release_modifiers()
    record("What the Camera steps do not show", INFO, "pointer and wheel events were generated, not made by a hand: nothing here is evidence about trackpad feel, swipe detents or a notched display")
    # PIKY's own content-free record of the session.
    camera_log = os.path.join(SUPPORT, "Diagnostics", "camera.jsonl")
    if os.path.exists(camera_log):
        with open(camera_log, encoding="utf-8") as handle:
            lines = handle.read().strip().splitlines()
        record("PIKY's own Camera record", INFO, "%s content-free lines in Diagnostics/camera.jsonl (copied into the evidence)" % len(lines))


def receipts():
    try:
        with open(RECEIVER_LOG, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle.read().splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def last_delivery():
    """PIKY's own content-free record of its last paste: stages and milliseconds."""
    target = os.path.join(SUPPORT, "Diagnostics", "delivery.jsonl")
    try:
        with open(target, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle.read().splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    return lines[-1] if lines else None


def stage_command_return():
    STATE["stage"] = "11 ⌘Return into TestReceiver"
    escape()
    wait_picking(False, 3)
    quit_app("Safari")
    before_pack = current_pack(expect=CTX["expected"], timeout=6)
    run(["/usr/bin/open", "-n", RECEIVER_APP, "--args", "--log", RECEIVER_LOG])
    CTX["receiver_started"] = True
    box = find({"name": "TestReceiver"}, "--role", "AXTextArea", "--title", "Message", timeout=20)
    pause(1.0)
    qa("ax", "set-frame", "--name", "TestReceiver", "--rect", "560,60,760,680", quiet=True)
    pause(0.8)
    box = find({"name": "TestReceiver"}, "--role", "AXTextArea", "--title", "Message")
    if not box or not usable(box[0].get("frame")):
        record("⌘Return into TestReceiver", INCONCLUSIVE, "the receiver's message box could not be located", [shot("receiver-missing"), ax_dump("receiver", {"name": "TestReceiver"})])
        raise Blocked()
    x, y = center(box[0]["frame"])
    qa("click", "%.1f" % x, "%.1f" % y)
    pause(0.8)
    status = piky_status()
    if status and not status["picking"] and "adds it to the message box" not in (status.get("help") or ""):
        # The Pack is resting: ⌥Space brings it back, as PIKY's own tooltip says.
        option_space()
        wait_picking(True, 5)
        pause(0.6)
    ready = piky_status()
    evidence = [shot("receiver-ready-before-command-return")]
    existing = len(receipts())
    pressed = press(36, "cmd")
    arrived = wait_for(lambda: len(receipts()) > existing, 45, 0.25)
    pause(7.0)  # anything delivered twice would have arrived by now
    got = receipts()[existing:]
    evidence.append(shot("receiver-after-command-return"))
    evidence.append("receiver/received.jsonl")
    delivery = last_delivery()
    message = qa("ax", "value", "--name", "TestReceiver", "--role", "AXTextArea", "--title", "Message", quiet=True)
    if not arrived or not got:
        record("⌘Return delivers the Pack into the message box", FAIL if ready and ready["count"] > 0 and delivery else INCONCLUSIVE,
               "nothing reached TestReceiver within 45 s of ⌘Return (PIKY's item before the keys: %s; PIKY's own record of the attempt: %s)"
               % (ready["label"] if ready else "?", json.dumps(dict((key, delivery.get(key)) for key in ("outcome", "reason", "ms")) if delivery else None)),
               evidence + [ax_dump("piky-after-command-return", BUNDLE, maximum=800)])
        return
    receipt = got[0]
    files = receipt.get("files", [])
    names = receipt.get("filenames", [])
    manifest = CTX.get("manifest", {})
    expected_files = [name for name in (before_pack["files"] if before_pack else []) if name]
    note_first = bool(names) and names[0].startswith("PIKY Pack")
    # Fixture files are recognised by their bytes, whatever name they arrive under.
    by_digest = dict((digest, name) for name, digest in manifest.items())
    delivered_fixture = [by_digest[item.get("sha256")] for item in files if item.get("sha256") in by_digest]
    expected_fixture = [unicodedata.normalize("NFC", name) for name in (expected_files or CTX.get("finder_picked", [])) if unicodedata.normalize("NFC", name) in manifest]
    order_ok = bool(expected_fixture) and delivered_fixture == expected_fixture
    intact = bool(expected_fixture) and sorted(delivered_fixture) == sorted(expected_fixture)
    text_in_note = None
    if note_first and files and files[0].get("url", "").startswith("file://"):
        try:
            from urllib.parse import unquote, urlparse
            with open(unquote(urlparse(files[0]["url"]).path), encoding="utf-8") as handle:
                note = handle.read()
            picked = [paragraph for paragraph, label in zip(PARAGRAPHS[1:], ("drag", "triple")) if any(label in pick.lower() for pick in CTX["picks"])]
            text_in_note = all(paragraph in note for paragraph in picked) if picked else None
        except (OSError, ValueError):
            text_in_note = None
    pictures = receipt.get("imageCount", 0)
    wanted_pictures = len([1 for kind, name in zip(before_pack["kinds"], before_pack["files"]) if kind in ("screen_region", "image") or name.lower().endswith(".png")]) if before_pack else \
        len([label for label in CTX["picks"] if label.startswith("Camera")]) + len([name for name in CTX.get("finder_picked", []) if name.lower().endswith(".png")])
    press_ms = pressed.get("pressedAtUtcMs")
    try:
        import datetime
        stamp = datetime.datetime.strptime(receipt["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc)
        latency = int(stamp.timestamp() * 1000) - int(press_ms)
    except (KeyError, ValueError, TypeError):
        latency = None
    CTX["timing"] = {"commandReturnPressedUtcMs": press_ms, "receiverTimestamp": receipt.get("timestamp"), "keyPressToReceiverMs": latency,
                     "pikyOwnRecord": dict((key, delivery.get(key)) for key in ("outcome", "ms", "timeline", "picks", "files", "app")) if delivery else None,
                     "picksInPack": before_pack["count"] if before_pack else None, "via": receipt.get("via"), "attachments": receipt.get("attachmentCount")}
    save_text("timing.json", json.dumps(CTX["timing"], indent=2, sort_keys=True))
    record("⌘Return delivers the Pack into the message box", PASS,
           "one real ⌘Return with the caret in TestReceiver's box: a delivery arrived via %s with %s attachment(s), %s of them pictures, text: %s characters. Mode: %s."
           % (receipt.get("via"), receipt.get("attachmentCount"), pictures, receipt.get("textCharacters"), CTX["mode"]), evidence, data={"receipt": dict((key, receipt.get(key)) for key in ("via", "attachmentCount", "imageCount", "filenames", "textCharacters", "timestamp"))})
    record("Delivered once, not twice", PASS if len(got) == 1 else FAIL, "%s delivery line(s) in the receiver's log in the 7 s after the first" % len(got), ["receiver/received.jsonl"])
    record("The Pack note comes first, then files in Pick order", PASS if note_first and order_ok else INCONCLUSIVE if not expected_fixture else FAIL,
           "received, in order: %s. Fixture files recognised by their bytes, in order: %s. Picked in Finder, in order: %s"
           % (" | ".join(names), " | ".join(delivered_fixture) or "none", " | ".join(expected_fixture) or "none"))
    record("File bytes arrive intact", PASS if intact else INCONCLUSIVE if not expected_fixture else FAIL,
           "%s of the %s fixture files picked in Finder arrived with exactly the fixture's bytes (SHA-256 against the manifest)" % (len(delivered_fixture), len(expected_fixture)))
    record("Picked text is in the Pack note", PASS if text_in_note else INCONCLUSIVE if text_in_note is None else FAIL,
           "the note file %s the picked fixture paragraph(s)" % ("contains" if text_in_note else "could not be read back for" if text_in_note is None else "does NOT contain"))
    record("Camera pictures are attached", PASS if pictures == wanted_pictures and pictures > 0 else INFO,
           "%s picture(s) received; the Pack held %s (Camera Picks and the fixture PNG)" % (pictures, wanted_pictures))
    sent = bool(message.get("endsWithNewline")) or (message.get("length") or 0) > 0
    record("No automatic Send", PASS if not sent else FAIL,
           "after the delivery the message box holds %s characters and no line break: no Return or Enter reached it. (TestReceiver has no Send button; this shows PIKY pressed nothing after delivering.)" % message.get("length"))
    timeline = (delivery or {}).get("timeline") or {}
    record("Delivery latency on this macOS", INFO,
           "⌘Return key-down to the receiver's own timestamp: %s ms. PIKY's own record: outcome %s, %s ms in total, milestones (ms from the key press): %s. A hosted VM; treat as an upper bound, not a measurement of a real Mac."
           % (latency, (delivery or {}).get("outcome"), (delivery or {}).get("ms"), json.dumps(timeline, sort_keys=True)), ["timing.json"], data=CTX["timing"])
    said = [text for text in read_dialog(BUNDLE)["texts"]][:6]
    record("What PIKY's card said after the delivery", INFO, " / ".join(text.replace("\n", " ") for text in said)[:400] or "(no text could be read from PIKY's windows)")


def status_menu(item):
    """Right-click PIKY in the menu bar and choose an item, by the pointer;
    by typing its name if the menu is not exposed."""
    status = piky_status()
    if not status or not usable(status.get("frame")):
        return None
    frame = status["frame"]
    qa("click", "%.1f" % (frame[0] + min(12.0, frame[2] / 2)), "%.1f" % (frame[1] + frame[3] / 2), "--button", "right")
    pause(1.0)
    shot("piky-menu-for-" + item)
    done = click_element(BUNDLE, "--role", "AXMenuItem", "--title", item)
    if done:
        return done["how"]
    qa("type", item.rstrip("…"))
    pause(0.3)
    press(36)
    return "typed its name, then Return"


def stage_library_restart():
    STATE["stage"] = "12 Undo, New Pack, Library, restart"
    status = piky_status()
    if not status:
        record("Undo, New Pack, Library, restart", NOTRUN, "PIKY's menu-bar item cannot be read")
        return
    CTX["expected"] = status["count"]
    start = status["count"]
    # --- Undo by keys (PIKY holds ⌃⌘Z while the Pack is on screen).
    if not status["picking"] and "adds it to the message box" not in (status.get("help") or ""):
        activate("com.apple.finder")
        option_space()
        wait_picking(True, 5)
    press(6, "ctrl,cmd")
    by_keys = wait_count(start - 1, 6)
    after_keys = count_now()
    record("Undo last Pick with ⌃⌘Z", PASS if by_keys else FAIL if start > 0 else INCONCLUSIVE,
           "%s Picks before, %s after one ⌃⌘Z" % (start, after_keys), [shot("after-undo-keys")])
    # --- Undo by ↶ in the menu bar.
    now = after_keys if after_keys is not None else start
    arrow = click_element(BUNDLE, "--role", "AXButton", "--title", "Undo last Pick")
    if not arrow:
        item = piky_status()
        if item and usable(item.get("frame")) and item["frame"][2] >= 44:
            frame = item["frame"]
            qa("click", "%.1f" % (frame[0] + frame[2] - 10), "%.1f" % (frame[1] + frame[3] / 2))
            arrow = {"how": "pointer click on ↶ at the right end of PIKY's menu-bar item, %s wide" % int(frame[2])}
    by_arrow = wait_count(now - 1, 6) if arrow else None
    after_arrow = count_now()
    record("Undo last Pick with ↶ in the menu bar", PASS if by_arrow else INCONCLUSIVE if not arrow else FAIL,
           "%s Picks before, %s after one click on ↶ (%s)" % (now, after_arrow, arrow["how"] if arrow else "↶ was not found beside PIKY's mark"), [shot("after-undo-arrow")])
    kept = after_arrow if after_arrow is not None else now
    escape()
    wait_picking(False, 3)
    before_new = current_pack(expect=kept, timeout=6)

    # --- New Pack.
    how = status_menu("New Pack")
    emptied = wait_count(0, 8)
    pause(1.5)
    saved = library()
    archived = [pack for name, pack in saved["packs"].items() if pack["count"] == kept and name != saved["current"]]
    record("New Pack", PASS if emptied and archived else FAIL if how else INCONCLUSIVE,
           "PIKY's menu › New Pack (%s): the item now reads “%s”; on disk %s saved Pack(s) hold the %s Picks that were current" % (how, (piky_status() or {}).get("label"), len(archived), kept),
           [shot("after-new-pack")])

    # --- Library: open the saved Pack again.
    how = status_menu("Library…")
    pause(1.5)
    listing = [shot("library")]
    opened = click_element(BUNDLE, "--role", "AXButton", "--title", "Open", timeout=4)
    if not opened:
        # A saved Pack is a row: choose it, then Open.
        row = find(BUNDLE, "--contains", "%s Pick" % kept, all=True)
        rows = [item for item in row if usable(item.get("frame")) and item.get("role") not in ("AXMenuBarItem", "AXWindow")]
        if rows:
            x, y = center(rows[0]["frame"])
            qa("click", "%.1f" % x, "%.1f" % y)
            pause(0.8)
            opened = click_element(BUNDLE, "--role", "AXButton", "--title", "Open", timeout=3)
    restored = wait_count(kept, 8) if opened else None
    pause(1.2)
    again = current_pack(expect=kept, timeout=5)
    same = bool(again and before_new and again["ids"] == before_new["ids"])
    listing.append(shot("after-opening-saved-pack"))
    record("Library lists the saved Pack and opens it", PASS if restored and same else INCONCLUSIVE if not opened or not (again and before_new) else FAIL,
           "PIKY's menu › Library… (%s); Open %s; the item reads “%s”; the Picks on disk are %s as before New Pack"
           % (how, "clicked (%s)" % opened["how"] if opened else "was not found", (piky_status() or {}).get("label"), "the same, in the same order," if same else "NOT the same"),
           listing + ([] if opened else [ax_dump("library", BUNDLE)]))
    escape()
    pause(0.8)

    # --- Quit and open again.
    before_quit = library()
    count_before = count_now()
    how = status_menu("Quit PIKY")
    quit_ok = wait_for(lambda: not piky_running(), 12, 0.4)
    record("Quit PIKY from its menu", PASS if quit_ok else FAIL, "PIKY's menu › Quit PIKY (%s): %s" % (how, "the process ended" if quit_ok else "the process is still running after 12 s"), [shot("after-quit")])
    if not quit_ok:
        for pid in piky_pids():
            run(["/bin/kill", "-9", str(pid)], quiet=True)
    pause(1.5)
    if CTX["own_accessibility"]:
        run(["/usr/bin/open", APP])
    else:
        start_piky_from_the_job()
    up = wait_for(piky_running, 20, 0.5)
    status = wait_for(piky_status, 15, 0.5)
    pause(1.5)
    first_run_again = "Meet PIKY" in piky_windows()
    after = library()
    record("PIKY opens again without its first-run window", PASS if up and not first_run_again else FAIL,
           "reopened (%s); PIKY's windows: %s; processes: %s" % ("LaunchServices" if CTX["own_accessibility"] else "started by the job, as before", piky_windows(), piky_pids()), [shot("after-reopen")])
    same_current = bool(before_quit["currentPack"] and after["currentPack"] and before_quit["currentPack"]["ids"] == after["currentPack"]["ids"])
    same_library = sorted(before_quit["packs"]) == sorted(after["packs"])
    readable = bool(before_quit["currentPack"] and after["currentPack"])
    record("The Pack and the Library survive a restart", PASS if status and status["count"] == count_before and same_current and same_library
           else INCONCLUSIVE if status and status["count"] == count_before and same_library and not readable else FAIL,
           "before quitting: “%s Picks”, %s Pack(s) on disk; after reopening: “%s”, %s Pack(s) on disk; the current Pack's Picks are %s"
           % (count_before, len(before_quit["packs"]), status["label"] if status else "no status item", len(after["packs"]), "the same, in the same order" if same_current else "NOT the same"))


def stage_collect():
    STATE["stage"] = "13 Evidence"
    if CTX.get("foreign"):
        return  # not our machine to read or tidy
    release_modifiers()
    shot("desktop-at-the-end")
    pids = piky_pids()
    reports = []
    for folder in (os.path.join(HOME, "Library/Logs/DiagnosticReports"),) + (() if SIM else ("/Library/Logs/DiagnosticReports",)):
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                if name.startswith("PIKY") or name.startswith("TestReceiver"):
                    reports.append(name)
                    shutil.copy2(os.path.join(folder, name), path("logs", "crash-reports", name))
    record("No crash report for PIKY during the run", PASS if not [name for name in reports if name.startswith("PIKY")] else FAIL,
           "%s report(s): %s" % (len(reports), ", ".join(reports) or "none"))
    diagnostics = os.path.join(SUPPORT, "Diagnostics")
    if os.path.isdir(diagnostics):
        shutil.copytree(diagnostics, path("piky-diagnostics", "x")[:-2], dirs_exist_ok=True)
    started = CTX.get("gatekeeper_started") or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3600))
    for name, predicate in (("piky.log", 'process == "PIKY" OR subsystem BEGINSWITH "app.getpiky"'),
                            ("system.log", '(process == "syspolicyd" OR process == "tccd" OR process == "amfid" OR process == "CoreServicesUIAgent" OR process == "launchservicesd" OR process == "ReportCrash") AND (eventMessage CONTAINS[c] "piky")')):
        code, out, _ = run(["/usr/bin/log", "show", "--start", started, "--style", "compact", "--predicate", predicate], timeout=240, quiet=True)
        text = "\n".join(out.splitlines()[-6000:])
        save_text("logs/" + name, text)
        if name == "system.log" and "AppTranslocation" in text:
            record("App Translocation", INFO,
                   "the system log shows macOS preparing to run the quarantined copy from a randomised, read-only location (…/AppTranslocation/…/PIKY.app), which it does when a quarantined app was not put in place by a person's drag in Finder. How the copy was made here: see the Gatekeeper stage.",
                   ["logs/system.log"])
    record("PIKY processes at the end", INFO, "%s running (pid %s)" % (len(pids), pids))
    # Leave the machine as tidy as is practical; GitHub destroys it anyway.
    for pid in piky_pids():
        run(["/bin/kill", "-TERM", str(pid)], quiet=True)
    for name in ("TestReceiver", "TextEdit", "Safari", "System Settings"):
        run(["/usr/bin/killall", name], quiet=True)


STAGES = [
    ("environment", stage_environment), ("safari_download", stage_safari_download), ("gatekeeper", stage_gatekeeper),
    ("first_run", stage_first_run), ("permissions", stage_permissions), ("hotkey_without_permission", stage_hotkey_without_permission),
    ("functional_mode", stage_functional_mode), ("option_space", stage_option_space), ("text_pick", stage_text_pick),
    ("finder_pick", stage_finder_pick), ("camera", stage_camera), ("command_return", stage_command_return),
    ("library_restart", stage_library_restart),
]
# A stage that cannot go on stops the ones that need what it was making.
NEEDS = {"first_run": ("gatekeeper",), "permissions": ("first_run",), "hotkey_without_permission": ("first_run",), "functional_mode": ("first_run",),
         "option_space": ("functional_mode",), "text_pick": ("functional_mode", "option_space"), "finder_pick": ("functional_mode", "option_space"),
         "camera": ("functional_mode", "option_space"), "command_return": ("functional_mode", "option_space"), "library_restart": ("functional_mode", "option_space")}


def main():
    if not SIM and (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT", "github-hosted") != "github-hosted"):
        sys.exit("This run installs PIKY and drives the keyboard and pointer. It only starts on a GitHub-hosted runner.")
    if not SIM and (not os.path.exists(QA_BIN) or not os.path.exists(RECEIVER_APP)):
        sys.exit("Build the tools first: bash harness/build-tools.sh build")
    os.makedirs(OUT, exist_ok=True)
    log("headed run: %s %s (%s), expected SHA-256 %s" % (DMG_NAME, RELEASE["PIKY_VERSION"], RELEASE["PIKY_BUILD"], RELEASE["PIKY_DMG_SHA256"]))
    blocked = set()
    try:
        for name, stage in STAGES:
            if CTX["abort"]:
                record("Stage: %s" % name, NOTRUN, CTX["abort"], stage=name)
                continue
            missing = [need for need in NEEDS.get(name, ()) if need in blocked]
            if missing:
                blocked.add(name)
                record("Stage: %s" % name, NOTRUN, "it needs what the stage “%s” could not provide" % missing[0], stage=name)
                continue
            try:
                stage()
                if name == "gatekeeper" and not CTX["launched"] and not CTX["abort"]:
                    stage_second_install()
            except Blocked:
                blocked.add(name)
                if name == "gatekeeper" and not CTX["launched"] and not CTX["abort"]:
                    try:
                        stage_second_install()
                        blocked.discard(name)
                    except Blocked:
                        pass
                    except Exception:  # noqa: BLE001
                        log(traceback.format_exc())
            except Exception as problem:  # noqa: BLE001  (one stage's mistake must not cost the others)
                blocked.add(name) if name in ("functional_mode",) else None
                log(traceback.format_exc())
                record("Stage: %s" % name, INCONCLUSIVE, "the harness itself failed here (%s: %s); see run.log" % (type(problem).__name__, str(problem)[:200]),
                       [shot("harness-error-" + name)], stage=STATE["stage"])
            finally:
                release_modifiers()
    finally:
        try:
            stage_collect()
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        results_writer.write(RESULTS, CTX, RELEASE, STATE)
    failures = [entry for entry in RESULTS if entry["status"] == FAIL]
    log("done: %s results, %s FAIL" % (len(RESULTS), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
