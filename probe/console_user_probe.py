#!/usr/bin/python3
"""Unattended probe: can a GitHub-hosted Mac be given a real console session
whose logged-in user is the temporary administrator, through macOS's own
Fast User Switching and its login window?

    /usr/bin/python3 probe/console_user_probe.py

It answers that one question and tests nothing else: no remote desktop is
started, PIKY is not installed, Gatekeeper is not touched, nobody connects.

What it does to the (disposable) machine, each one listed in RESULT.md:
  - switches Fast User Switching on with the preference macOS reads for it
  - shows the Users menu in the menu bar
  - marks the first-login tour as seen for the temporary account
  - starts its own driver inside a login session macOS has already created,
    with the public commands `launchctl bsexec` (the login window) and
    `launchctl asuser` (the new desktop)

What it never does: call a private Apple API, write to a TCC database, change
SIP or Gatekeeper, set up auto-login, restart, or reset a password. The
temporary password is read from the session's private file, handed to the
driver on standard input, typed only at macOS's own login window, and never
written to a log, a screenshot or a result. Standard library only.
"""
import datetime
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(os.environ.get("QA_OUT", os.path.join(ROOT, "evidence")))
TOOLS = os.path.abspath(os.environ.get("QA_TOOLS", os.path.join(ROOT, "build")))
QA_HERE = os.path.join(TOOLS, "qa")
# Where another account can read the driver and leave its screenshots.
SHARED = "/Users/Shared/PIKY-QA-probe"
QA_SHARED = SHARED + "/qa"
STATE = os.path.join(os.environ.get("RUNNER_TEMP") or "/nonexistent", "piky-interactive")
CREDENTIALS = os.path.join(STATE, "credentials")
SINK = os.path.join(STATE, "sink.txt")
ADMIN = "pikyqa"
ADMIN_FULL_NAME = "PIKY QA Admin"
# A harmless word typed first, to see where this job's keys go before the password follows.
CANARY = "qaprobe"
LINE = "The quick brown fox jumps over 26 lazy dogs"
TEXTEDIT = "com.apple.TextEdit"
CONTROL_CENTER = "com.apple.controlcenter"
LOGINWINDOW = "/loginwindow.app/Contents/MacOS/loginwindow"

PASS, FAIL, NOTRUN = "PASS", "FAIL", "NOT RUN"

S = {"secret": "", "shots": 0, "dumps": 0, "records": 0, "no_shots": "", "login_pid": 0, "login_ui": 0, "uid": 0,
     "initial_owner": "", "runner_name": "", "route": "", "chose": "", "delivery": "", "stopped_at": ""}
R = {"admin": NOTRUN, "trigger": NOTRUN, "login_window": NOTRUN, "password": NOTRUN, "console_after": "(not reached)",
     "record_after": "(not reached)", "finder": "(not reached)", "dock": "(not reached)", "textedit": NOTRUN, "still": NOTRUN,
     "check_a": False, "check_b": False, "check_c": False, "check_d": False, "check_e": False, "check_f": False}
DETAIL = {}
CHANGES = []
NOTES = []


# ---------------------------------------------------------------- plumbing

def now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log(message):
    text = str(message)
    if S["secret"]:
        text = text.replace(S["secret"], "[the temporary password]")
    line = "%s  %s" % (now_iso(), text)
    print(line, flush=True)
    try:
        with open(os.path.join(OUT, "run.log"), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def path(relative):
    target = os.path.join(OUT, relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


def save_text(relative, text):
    if S["secret"]:
        text = text.replace(S["secret"], "[the temporary password]")
    with open(path(relative), "w", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") or not text else text + "\n")
    return relative


def run(command, timeout=40, input_text=None, quiet=False, secret=False):
    """Runs a command to its end. Returns (status, stdout, stderr); never raises.
    `secret` keeps the command line out of the log. Standard input is never logged."""
    shown = "(not shown)" if secret else " ".join(str(part) for part in command)
    try:
        done = subprocess.run([str(part) for part in command], input=input_text, capture_output=True, text=True,
                              timeout=timeout, errors="replace")
        code, out, err = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as expired:
        out = expired.stdout if isinstance(expired.stdout, str) else (expired.stdout or b"").decode("utf-8", "replace")
        code, err = 124, "timed out after %s s" % timeout
    except OSError as problem:
        code, out, err = 127, "", str(problem)
    if not quiet:
        log("$ %s -> %s%s" % (shown[:300], code, (" | " + err.strip()[:200]) if code != 0 and err.strip() else ""))
    return code, out, err


def wrap(context, command):
    """The same command, started inside one of three login sessions:
    here        this job's own (the runner's)
    login       the login window's, as root
    user        the temporary administrator's desktop, as that user
    user-root   that desktop, as root
    `launchctl bsexec` and `asuser` only place a program in a session that
    macOS has already created. They create none."""
    command = [str(part) for part in command]
    if context == "here":
        return command
    if context == "login":
        return ["/usr/bin/sudo", "-n", "/bin/launchctl", "bsexec", str(S["login_pid"])] + command
    if context == "user":
        return ["/usr/bin/sudo", "-n", "/bin/launchctl", "asuser", str(S["uid"]), "/usr/bin/sudo", "-n", "-u", ADMIN, "-H"] + command
    if context == "user-root":
        return ["/usr/bin/sudo", "-n", "/bin/launchctl", "asuser", str(S["uid"])] + command
    raise ValueError(context)


def driver(context):
    return QA_HERE if context == "here" else QA_SHARED


def qa(context, *arguments, **options):
    """One call of the driver in a session. Returns its JSON object, with "_code".
    Text it read back is never logged: it could be something typed in the wrong place."""
    arguments = [str(argument) for argument in arguments]
    # Posting an event answers at once or not at all; reading a window may take longer.
    limit = options.get("timeout", 12 if arguments[0] in ("type", "key", "click", "move", "release") else 25)
    code, out, err = run(wrap(context, [driver(context)] + arguments), timeout=limit, input_text=options.get("input_text"), quiet=True)
    lines = [line for line in out.strip().splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else {}
    except ValueError:
        data = {"ok": False, "error": "unreadable answer"}
    if not isinstance(data, dict):
        data = {"ok": False, "error": "unexpected answer"}
    if code != 0 and "error" not in data and err.strip():
        data["error"] = err.strip()[:300]
    data.setdefault("ok", code == 0)
    data["_code"] = code
    if not options.get("quiet"):
        brief = dict((key, value) for key, value in data.items() if key not in ("elements", "tree", "windows", "applications", "text"))
        if isinstance(brief.get("element"), dict):
            brief["element"] = dict((key, value) for key, value in brief["element"].items() if key != "value")
        if "elements" in data:
            brief["elements"] = len(data["elements"])
        shown = "(not shown)" if options.get("secret") else " ".join(arguments)[:200]
        log("qa[%s] %s -> %s" % (context, shown, json.dumps(brief, ensure_ascii=False)[:400]))
    return data


def elements(context, app, *selector):
    data = qa(context, "ax", "find", *(list(app) + list(selector) + ["--all"]), quiet=True)
    return data.get("elements") or []


def find_when_ready(context, app, selector, seconds):
    """`ax find` answers at once when an application is not running yet, whatever
    its --timeout: ask again until the element is there or the time is up."""
    end = time.time() + seconds
    while True:
        rows = [row for row in elements(context, app, *selector) if usable(row.get("frame"))]
        if rows or time.time() >= end:
            return rows
        time.sleep(1.0)


def usable(frame):
    return bool(frame) and len(frame) == 4 and frame[2] >= 4 and frame[3] >= 4 and -2 <= frame[0] < 6000 and -2 <= frame[1] < 6000


def center(frame):
    return frame[0] + frame[2] / 2.0, frame[1] + frame[3] / 2.0


def click_at(context, frame, label):
    x, y = center(frame)
    data = qa(context, "click", "%.1f" % x, "%.1f" % y, quiet=True)
    log("click[%s] %s at %.0f,%.0f -> %s" % (context, label, x, y, "done" if data.get("ok") else data.get("error", "failed")))
    return bool(data.get("ok"))


def outline(context, label, app, depth=24, maximum=1500, values=False):
    """What Accessibility says a window holds: roles, names and positions.
    Not the contents of a field, unless `values` is asked for (a system
    dialog's wording; a password field's contents are never read at all)."""
    S["dumps"] += 1
    name = "ax/%02d-%s.txt" % (S["dumps"], label)
    command = [driver(context), "ax", "tree"] + list(app) + ["--depth", str(depth), "--max", str(maximum), "--text"] + ([] if values else ["--no-value"])
    code, out, err = run(wrap(context, command), timeout=40, quiet=True)
    save_text(name, out if out.strip() else "(no Accessibility answer: %s)" % (err.strip()[:200] or "status %s" % code))
    log("outline[%s] %s -> %s (%d lines)" % (context, label, name, len(out.splitlines())))
    return out


def shot(context, label):
    """A screenshot taken from inside a session. None is taken between typing
    the password and a completed login: nothing typed could then be in one."""
    if S["no_shots"]:
        log("no screenshot (%s): %s" % (label, S["no_shots"]))
        return ""
    S["shots"] += 1
    name = "shots/%02d-%s.png" % (S["shots"], label)
    target = path(name)
    if context == "here":
        code, _, err = run(["/usr/sbin/screencapture", "-x", "-C", "-m", "-t", "png", target], timeout=25, quiet=True)
    else:
        staged = "%s/shots/%02d.png" % (SHARED, S["shots"])
        code, _, err = run(wrap(context, ["/usr/sbin/screencapture", "-x", "-m", "-t", "png", staged]), timeout=25, quiet=True)
        if code == 0 and os.path.exists(staged):
            try:
                shutil.copyfile(staged, target)
            except OSError as problem:
                code, err = 1, str(problem)
    good = code == 0 and os.path.exists(target) and os.path.getsize(target) > 2000
    if not good and os.path.exists(target):
        os.remove(target)
    log("shot[%s] %s -> %s" % (context, label, name if good else "none (%s)" % (err.strip()[:160] or "status %s" % code)))
    return name if good else ""


def is_picture(name):
    """Is a screenshot a picture of something, or one flat colour?"""
    if not name:
        return False, "no screenshot"
    data = qa("here", "image", "contrast", path(name), quiet=True)
    if not data.get("ok"):
        return False, data.get("error", "unreadable")
    share = data.get("fillShare", 1)
    return share < 0.985, "most common shade covers %.1f%% of it" % (share * 100)


def wait_for(test, timeout, interval=0.5):
    end = time.time() + timeout
    while True:
        value = test()
        if value:
            return value
        if time.time() >= end:
            return value
        time.sleep(interval)


# ---------------------------------------------------------------- what macOS reports

def console_owner():
    return run(["/usr/bin/stat", "-f", "%Su", "/dev/console"], quiet=True)[1].strip()


def parse_console_record(text):
    record = {"name": "", "uid": "", "sessions": []}
    session = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.endswith(": <dictionary> {") and line.split(" ", 1)[0].isdigit():
            session = {}
            record["sessions"].append(session)
            continue
        if line == "}":
            session = None
            continue
        if " : " not in line:
            continue
        key, value = line.split(" : ", 1)
        if session is not None:
            session[key.strip()] = value.strip()
        elif key.strip() == "Name":
            record["name"] = value.strip()
        elif key.strip() == "UID":
            record["uid"] = value.strip()
    return record


def console_record(label):
    """State:/Users/ConsoleUser: the record behind macOS's console-user call."""
    code, out, _ = run(["/usr/sbin/scutil"], input_text="show State:/Users/ConsoleUser\n", quiet=True, timeout=15)
    S["records"] += 1
    save_text("console/%02d-%s.txt" % (S["records"], label), "/dev/console owner: %s\n\n%s" % (console_owner(), out))
    return parse_console_record(out)


def describe_record(record):
    parts = []
    for session in record["sessions"]:
        parts.append("%s (on console: %s, login done: %s)" % (session.get("kCGSSessionUserNameKey", "?"),
                                                              session.get("kCGSSessionOnConsoleKey", "?"),
                                                              session.get("kCGSessionLoginDoneKey", "?")))
    return "Name = %s; sessions: %s" % (record["name"] or "(none)", "; ".join(parts) or "(none)")


def record_says(record, user):
    """Is `user` the console user, with a session on the console whose login is complete?"""
    if record["name"] != user:
        return False
    return any(session.get("kCGSSessionUserNameKey") == user and session.get("kCGSSessionOnConsoleKey") == "TRUE"
               and session.get("kCGSessionLoginDoneKey") == "TRUE" for session in record["sessions"])


def note_console(label):
    owner = console_owner()
    record = console_record(label)
    log("console[%s]: /dev/console owner = %s; %s" % (label, owner, describe_record(record)))
    return owner, record


def processes():
    rows = []
    for line in run(["/bin/ps", "-axo", "pid=,user=,comm="], quiet=True)[1].splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append((int(parts[0]), parts[1], parts[2]))
    return rows


def owners(suffix):
    return [(pid, user) for pid, user, comm in processes() if comm.endswith(suffix)]


def owner_of(pid):
    return run(["/bin/ps", "-o", "user=", "-p", str(pid)], quiet=True)[1].strip()


# ---------------------------------------------------------------- the sink

def sink_read():
    """The TextEdit document left in front in this job's own session. Only its
    length and whether it is the canary are returned: never its text."""
    data = qa("here", "ax", "value", "--bundle", TEXTEDIT, "--role", "AXTextArea", quiet=True, timeout=15)
    if data.get("_code") != 0 or not data.get("found"):
        return {"answered": False, "length": -1, "canary": False}
    text = data.get("text", "")
    return {"answered": True, "length": int(data.get("length", len(text))), "canary": CANARY in text}


def sink_focus():
    areas = [item for item in elements("here", ["--bundle", TEXTEDIT], "--role", "AXTextArea") if usable(item.get("frame"))]
    if not areas:
        return False
    return click_at("here", areas[0]["frame"], "the sink document")


def sink_open():
    """Whatever this job types while its own session is still the one in front
    lands here, where it can be seen and cleared, not in some other window."""
    with open(SINK, "w", encoding="utf-8"):
        pass
    run(["/usr/bin/open", "-a", "TextEdit", SINK])
    if not find_when_ready("here", ["--bundle", TEXTEDIT], ["--role", "AXTextArea"], 45) or not sink_focus():
        NOTES.append("The sink document could not be opened in the runner's own session, so where this job's keys go could not be checked.")
        return False
    time.sleep(0.6)
    qa("here", "type", CANARY, quiet=True)
    time.sleep(0.8)
    typed = sink_read()
    qa("here", "key", "0", "--mods", "cmd", quiet=True)
    qa("here", "key", "51", quiet=True)
    time.sleep(0.5)
    cleared = sink_read()
    good = typed["answered"] and typed["canary"]
    log("sink self-test: typed and read back %s, cleared %s" % (typed["canary"], cleared["length"] == 0))
    if not good:
        NOTES.append("The sink self-test failed before any switch: the word typed was not read back from the document.")
    elif cleared["length"] != 0:
        # Whoever asks later must compare with what the document holds then, not expect it empty.
        NOTES.append("The watching document kept the self-test's word (Command-A, Delete did not empty it).")
    return good


def sink_close():
    run(["/usr/bin/killall", "TextEdit"], quiet=True)
    try:
        os.remove(SINK)
    except OSError:
        pass


# ---------------------------------------------------------------- stages

def stage_baseline():
    version = run(["/usr/bin/sw_vers", "-productVersion"], quiet=True)[1].strip()
    build = run(["/usr/bin/sw_vers", "-buildVersion"], quiet=True)[1].strip()
    S["version"], S["build"] = version, build
    S["image"] = ("%s %s" % (os.environ.get("ImageOS", ""), os.environ.get("ImageVersion", ""))).strip()
    S["runner_name"] = run(["/usr/bin/id", "-F"], quiet=True)[1].strip()
    owner, record = note_console("initial")
    S["initial_owner"] = owner
    S["initial_record"] = describe_record(record)
    S["runner_loginwindow"] = [pid for pid, user in owners(LOGINWINDOW)]
    probe = qa("here", "probe")
    facts = [
        "macOS %s (%s), image %s" % (version, build, S["image"] or "?"),
        "csrutil: %s" % run(["/usr/bin/csrutil", "status"], quiet=True)[1].strip(),
        "spctl: %s" % run(["/usr/sbin/spctl", "--status"], quiet=True)[1].strip(),
        "/dev/console owner: %s" % owner,
        "console record: %s" % S["initial_record"],
        "runner's full name: %s" % S["runner_name"],
        "MultipleSessionEnabled (Fast User Switching): %s" % read_default("/Library/Preferences/.GlobalPreferences", "MultipleSessionEnabled"),
        "login window shows name and password fields (SHOWFULLNAME): %s" % read_default("/Library/Preferences/com.apple.loginwindow", "SHOWFULLNAME"),
        "automatic login is set for: %s" % read_default("/Library/Preferences/com.apple.loginwindow", "autoLoginUser"),
        "a program started by this job may: read other apps %s, post input %s, capture the screen %s" % (
            probe.get("accessibilityTrusted"), probe.get("postEvents"), probe.get("screenCapture")),
        "loginwindow, Finder and Dock processes: %s" % ", ".join(
            "%s pid %d (%s)" % (comm.rsplit("/", 1)[-1], pid, user) for pid, user, comm in processes()
            if comm.endswith(LOGINWINDOW) or comm.endswith("/Finder.app/Contents/MacOS/Finder") or comm.endswith("/Dock.app/Contents/MacOS/Dock")),
    ]
    save_text("os/machine.txt", "\n".join(facts))
    for fact in facts:
        log(fact)
    return owner == "runner"


def read_default(domain, key):
    code, out, _ = run(["/usr/bin/defaults", "read", domain, key], quiet=True)
    return out.strip() if code == 0 else "not set"


def stage_admin():
    exists = run(["/usr/bin/id", ADMIN], quiet=True)[0] == 0
    admin = run(["/usr/sbin/dseditgroup", "-o", "checkmember", "-m", ADMIN, "admin"], quiet=True)[0] == 0
    accepted = run(["/usr/bin/dscl", "/Local/Default", "-authonly", ADMIN, S["secret"]], quiet=True, secret=True)[0] == 0
    R["admin"] = PASS if exists and admin and accepted else FAIL
    DETAIL["admin"] = "account exists: %s; in the admin group: %s; macOS accepts its password (authonly): %s" % (exists, admin, accepted)
    log("temporary administrator: %s" % DETAIL["admin"])
    return R["admin"] == PASS


def stage_prepare():
    # Fast User Switching: macOS 26's loginwindow treats a missing preference as "off".
    before = read_default("/Library/Preferences/.GlobalPreferences", "MultipleSessionEnabled")
    if before != "1":
        run(["/usr/bin/sudo", "-n", "/usr/bin/defaults", "write", "/Library/Preferences/.GlobalPreferences", "MultipleSessionEnabled", "-bool", "true"])
        after = read_default("/Library/Preferences/.GlobalPreferences", "MultipleSessionEnabled")
        CHANGES.append("Fast User Switching was off on the image (MultipleSessionEnabled: %s). It was switched on with that preference, "
                       "the documented one macOS reads for it (now: %s)." % (before, after))
    else:
        NOTES.append("Fast User Switching was already on (MultipleSessionEnabled = 1).")
    # The first-login tour (Apple Account, Siri, Screen Time, appearance): marked as seen, so nothing is signed in to or chosen.
    seen = dict((key, True) for key in (
        "DidSeeAccessibility", "DidSeeActivationLock", "DidSeeAppearanceSetup", "DidSeeApplePaySetup", "DidSeeAppStore",
        "DidSeeAvatarSetup", "DidSeeCloudSetup", "DidSeeiCloudLoginForStorageServices", "DidSeeIntelligence", "DidSeeLockdownMode",
        "DidSeePrivacy", "DidSeeScreenTime", "DidSeeSiriSetup", "DidSeeSyncSetup", "DidSeeSyncSetup2", "DidSeeTermsOfAddress",
        "DidSeeTouchIDSetup", "DidSeeTrueTone", "DidSeeTrueTonePrivacy", "SkipFirstLoginOptimization"))
    for key in ("LastSeenCloudProductVersion", "LastSeenSiriProductVersion", "LastSeenDiagnosticsProductVersion", "LastPreLoginTasksPerformedVersion"):
        seen[key] = S["version"]
    for key in ("LastSeenBuddyBuildVersion", "LastPreLoginTasksPerformedBuild"):
        seen[key] = S["build"]
    seen["LastPrivacyBundleVersion"] = "2"
    seen["GestureMovieSeen"] = "none"
    home = "/Users/" + ADMIN
    if run(["/usr/bin/sudo", "-n", "/bin/test", "-d", home], quiet=True)[0] != 0:
        run(["/usr/bin/sudo", "-n", "/usr/sbin/createhomedir", "-c", "-u", ADMIN], timeout=90)
    with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as handle:
        plistlib.dump(seen, handle)
        staged = handle.name
    run(["/usr/bin/sudo", "-n", "-u", ADMIN, "/bin/mkdir", "-p", home + "/Library/Preferences"], quiet=True)
    placed = run(["/usr/bin/sudo", "-n", "/usr/bin/install", "-o", ADMIN, "-g", "staff", "-m", "600", staged,
                  home + "/Library/Preferences/com.apple.SetupAssistant.plist"])[0] == 0
    os.remove(staged)
    CHANGES.append("The first-login tour of the temporary account was marked as seen before its first login (%s), so that no "
                   "Apple Account, Siri or analytics screen has to be answered." % ("written" if placed else "could NOT be written"))


def menu_items():
    data = qa("here", "ax", "tree", "--bundle", CONTROL_CENTER, "--depth", "4", "--max", "1500", "--no-value", quiet=True, timeout=25)
    found = []

    def walk(node):
        if node.get("role") == "AXMenuBarItem":
            found.append(node)
        for child in node.get("children") or []:
            walk(child)
    walk(data.get("tree") or {})
    return found


def signature(item):
    return "%s|%s|%s" % (item.get("identifier", ""), item.get("description", ""), item.get("title", ""))


def users_item(items, before):
    for item in items:
        if item.get("identifier") == "com.apple.menuextra.user":
            return item
    for item in items:
        words = " ".join(str(item.get(key, "")) for key in ("identifier", "description", "title", "help")).lower()
        if "user" in words:
            return item
    known = set(signature(item) for item in before)
    fresh = [item for item in items if signature(item) not in known]
    return fresh[0] if len(fresh) == 1 else None


def watch_switch(seconds):
    """After a click that should switch user: did the console leave the runner
    (the login window has it), or did macOS ask for the password where we are?"""
    end = time.time() + seconds
    while time.time() < end:
        if console_owner() != S["initial_owner"]:
            return "login-window"
        focused = qa("here", "ax", "focused", quiet=True, timeout=8)
        if focused.get("found") and focused.get("secure"):
            return "panel"
        time.sleep(0.5)
    return ""


def route_users_menu():
    """Control Center's Users menu in the menu bar: click it, click the other user."""
    before = menu_items()
    log("Control Center menu-bar items before: %s" % ", ".join(signature(item) for item in before))
    item = users_item(before, before)
    if not item:
        run(["/usr/bin/defaults", "write", CONTROL_CENTER, "NSStatusItem Visible UserSwitcher", "-bool", "true"], quiet=True)
        for value in ("2", "18", "6"):
            run(["/usr/bin/defaults", "-currentHost", "write", CONTROL_CENTER, "UserSwitcher", "-int", value])
            run(["/usr/bin/killall", "ControlCenter"], quiet=True)
            time.sleep(2.0)
            wait_for(lambda: len(menu_items()) > 0, 15, 1.0)
            time.sleep(1.5)
            items = menu_items()
            item = users_item(items, before)
            log("after UserSwitcher = %s: %d menu-bar items; Users menu %s" % (value, len(items), "shown" if item else "not shown"))
            if item:
                CHANGES.append("The Users menu was shown in the menu bar with Control Center's own preference (UserSwitcher = %s), "
                               "the setting System Settings > Control Center > Fast User Switching makes." % value)
                break
    if not item or not usable(item.get("frame")):
        DETAIL["users_menu"] = "the Users menu could not be shown in the menu bar"
        outline("here", "control-center-no-users-menu", ["--bundle", CONTROL_CENTER], depth=6, maximum=400)
        return ""
    log("Users menu item: %s at %s" % (signature(item), item.get("frame")))
    shot("here", "before-users-menu")
    for attempt, wanted in enumerate((ADMIN_FULL_NAME, "Login Window")):
        items = menu_items()
        item = users_item(items, before) or item
        click_at("here", item["frame"], "the Users menu")
        time.sleep(1.6)
        shot("here", "users-menu-open-%d" % (attempt + 1))
        outline("here", "users-menu-open-%d" % (attempt + 1), ["--bundle", CONTROL_CENTER], depth=30, maximum=900)
        rows = [row for row in elements("here", ["--bundle", CONTROL_CENTER], "--contains", wanted) if usable(row.get("frame"))]
        if not rows and wanted == ADMIN_FULL_NAME:
            rows = [row for row in elements("here", ["--bundle", CONTROL_CENTER], "--contains", ADMIN) if usable(row.get("frame"))]
        if not rows:
            log("the open Users menu has no entry \"%s\"" % wanted)
            qa("here", "key", "53", quiet=True)
            time.sleep(0.6)
            continue
        rows.sort(key=lambda row: 0 if "AXPress" in (row.get("actions") or []) else 1)
        click_at("here", rows[0]["frame"], "\"%s\" in the Users menu" % wanted)
        outcome = watch_switch(20)
        if outcome:
            S["chose"] = "user" if wanted == ADMIN_FULL_NAME else "list"
            DETAIL["users_menu"] = "clicked the Users menu in the menu bar, then \"%s\"" % (ADMIN_FULL_NAME if wanted == ADMIN_FULL_NAME else "Login Window…")
            return outcome
        log("clicking \"%s\" did not switch within 20 seconds" % wanted)
        outline("here", "after-users-menu-click-%d" % (attempt + 1), ["--bundle", CONTROL_CENTER], depth=30, maximum=900)
        shot("here", "after-users-menu-click-%d" % (attempt + 1))
        qa("here", "key", "53", quiet=True)
        time.sleep(0.6)
    DETAIL["users_menu"] = "the Users menu was shown and clicked, but choosing a user or \"Login Window…\" switched nothing"
    return ""


def route_lock_screen():
    """Lock Screen (Control-Command-Q, or the Apple menu), then its Switch User button."""
    sink_focus()
    qa("here", "key", "12", "--mods", "ctrl,cmd")
    qa("here", "release", quiet=True)
    locked = wait_for(lambda: qa("here", "probe", quiet=True, timeout=10).get("screenLocked"), 8, 1.0)
    if not locked:
        pressed = qa("here", "ax", "press", "--bundle", TEXTEDIT, "--role", "AXMenuItem", "--title", "Lock Screen", timeout=15)
        log("Control-Command-Q did not lock the screen; Apple menu > Lock Screen pressed: %s" % pressed.get("ok"))
        locked = wait_for(lambda: qa("here", "probe", quiet=True, timeout=10).get("screenLocked"), 8, 1.0)
    if not locked:
        DETAIL["lock_screen"] = "the screen did not lock"
        return ""
    time.sleep(1.5)
    qa("here", "move", "960", "620", quiet=True)
    time.sleep(1.0)
    shot("here", "lock-screen")
    targets = [["--pid", str(pid)] for pid in S["runner_loginwindow"]]
    for target in targets:
        outline("here", "lock-screen-loginwindow", target, depth=30, maximum=900)
        buttons = [row for row in elements("here", target, "--contains", "Switch User") if usable(row.get("frame"))]
        if not buttons:
            continue
        click_at("here", buttons[0]["frame"], "Switch User on the lock screen")
        outcome = watch_switch(10)
        if not outcome:
            pressed = qa("here", "ax", "press", *(target + ["--contains", "Switch User"]), timeout=15)
            log("the click did not switch; Accessibility press of Switch User: %s" % pressed.get("ok"))
            outcome = watch_switch(15)
        if outcome:
            S["chose"] = "list"
            DETAIL["lock_screen"] = "locked the screen, then clicked Switch User on the lock screen"
            return outcome
        DETAIL["lock_screen"] = "the lock screen showed Switch User, but clicking it switched nothing"
        return ""
    DETAIL["lock_screen"] = "the screen locked, but no Switch User button could be found on the lock screen"
    return ""


def stage_trigger():
    """Fast User Switching, by the two ways a person has: the Users menu, then the lock screen."""
    outcome = route_users_menu()
    S["route"] = "the Users menu in the menu bar" if outcome else ""
    if not outcome:
        log("Users menu route: %s" % DETAIL.get("users_menu", "no result"))
        outcome = route_lock_screen()
        S["route"] = "Lock Screen > Switch User" if outcome else ""
        if not outcome:
            log("lock screen route: %s" % DETAIL.get("lock_screen", "no result"))
    tried = "; ".join(text for text in (DETAIL.get("users_menu"), DETAIL.get("lock_screen")) if text)
    R["trigger"] = PASS if outcome else FAIL
    DETAIL["trigger"] = tried
    return outcome


def login_pid():
    rows = [pid for pid, user in owners(LOGINWINDOW) if user == "root"]
    if not rows:
        rows = [pid for pid, user in owners(LOGINWINDOW) if pid not in S["runner_loginwindow"]]
    return max(rows) if rows else 0


def stage_login_window(outcome):
    owner, record = note_console("after-switch")
    if outcome == "panel":
        # macOS asked for the other user's password without leaving the runner's desktop.
        R["login_window"] = PASS
        DETAIL["login_window"] = "macOS asked for the password in a panel on the runner's own desktop (/dev/console owner still %s)" % owner
        return True
    S["login_pid"] = login_pid()
    reached = owner != S["initial_owner"]
    R["login_window"] = PASS if reached else FAIL
    DETAIL["login_window"] = "/dev/console owner became %s; console record: %s; the login window's process: %s" % (
        owner, describe_record(record), ("pid %d" % S["login_pid"]) if S["login_pid"] else "not found")
    return reached


def login_ui():
    """The process whose windows are the login window: loginwindow, or whichever has the keyboard there."""
    return ["--pid", str(S["login_ui"] or S["login_pid"])]


def login_fields():
    target = login_ui()
    secure = [row for row in elements("login", target, "--subrole", "AXSecureTextField") if usable(row.get("frame"))]
    names = [row for row in elements("login", target, "--role", "AXTextField")
             if row.get("subrole") != "AXSecureTextField" and usable(row.get("frame")) and row.get("enabled", True)]
    return secure, names


def changed_pixels(first, second, frame):
    if not first or not second or not usable(frame):
        return None
    rect = "%d,%d,%d,%d" % (frame[0] - 12, frame[1] - 8, frame[2] + 24, frame[3] + 16)
    data = qa("here", "image", "diff", path(first), path(second), "--rect", rect, quiet=True)
    return data.get("changed") if data.get("ok") else None


def logged_in(seconds):
    return bool(wait_for(lambda: console_owner() == ADMIN, seconds, 0.5))


def type_password(context):
    """The password, from this process's memory to the driver's standard input, then Return."""
    S["no_shots"] = "the password has been typed and the login has not completed"
    typed = qa(context, "type", "--stdin", input_text=S["secret"] + "\n", secret=True)
    time.sleep(0.4)
    qa(context, "key", "36", quiet=True)
    return bool(typed.get("ok"))


def stage_password_in_panel():
    """The password panel is on the runner's own desktop: the driver types as it always has."""
    type_password("here")
    if logged_in(60):
        S["delivery"] = "keys posted by the job, into macOS's password panel on the runner's desktop"
        return True
    return False


def stage_password_at_login_window():
    eyes = hands = False
    secure, names = [], []
    if S["login_pid"]:
        inside = qa("login", "probe", timeout=20)
        hands = inside.get("_code") == 0
        eyes = hands and bool(inside.get("accessibilityTrusted"))
        NOTES.append("The driver started inside the login window's session (launchctl bsexec): %s." % (
            "runs; may read the login window %s, post input %s, capture the screen %s; session on console: %s" % (
                inside.get("accessibilityTrusted"), inside.get("postEvents"), inside.get("screenCapture"), inside.get("sessionOnConsole"))
            if inside.get("_code") == 0 else "did not run (%s)" % str(inside.get("error", "no answer"))[:160]))
    if eyes:
        shot("login", "login-window")
        outline("login", "login-window", login_ui(), depth=30, maximum=900)
        secure, names = login_fields()
        tiles = [row for row in elements("login", login_ui(), "--contains", ADMIN_FULL_NAME) if usable(row.get("frame"))]
        if not secure and not names and not tiles:
            focused = qa("login", "ax", "focused", timeout=15)
            if focused.get("found") and focused.get("pid") and focused.get("pid") != S["login_pid"]:
                S["login_ui"] = int(focused["pid"])
                NOTES.append("The login window's controls belong to \"%s\" (pid %s), not to loginwindow itself." % (focused.get("application", "?"), focused["pid"]))
                outline("login", "login-window-controls", login_ui(), depth=30, maximum=900)
                secure, names = login_fields()
                tiles = [row for row in elements("login", login_ui(), "--contains", ADMIN_FULL_NAME) if usable(row.get("frame"))]
        log("login window: %d password field(s), %d name field(s), %d element(s) naming %s" % (len(secure), len(names), len(tiles), ADMIN_FULL_NAME))
        if tiles and (not secure or S["chose"] != "user"):
            click_at("login", tiles[0]["frame"], "%s at the login window" % ADMIN_FULL_NAME)
            time.sleep(2.5)
            shot("login", "login-window-user-chosen")
            outline("login", "login-window-user-chosen", login_ui(), depth=30, maximum=900)
            secure, names = login_fields()
    field = secure[0]["frame"] if secure else None

    # 1. Keys posted by the job from where it is, as the harness always has.
    posted = "not tried"
    sink = sink_read()
    if not sink["answered"] or sink["length"] != 0:
        posted = "not tried: the sink document did not answer, so a stray password could not have been seen"
    else:
        first = shot("login", "before-canary") if eyes else ""
        answered = qa("here", "type", CANARY, quiet=True).get("_code") == 0
        time.sleep(1.2)
        sink = sink_read() if answered else {"answered": False, "length": -1, "canary": False}
        second = shot("login", "after-canary") if eyes else ""
        arrived = changed_pixels(first, second, field)
        for _ in range(len(CANARY) + 3):
            if not answered or qa("here", "key", "51", quiet=True).get("_code") != 0:
                break
        time.sleep(0.4)
        log("canary posted by the job: characters in the runner's own document: %s; pixels changed in the login window's password field: %s" % (
            sink["length"] if sink["answered"] else "no answer", arrived))
        if not answered:
            posted = "FAIL: the driver could no longer post keys from the runner's own session once that session had left the screen"
        elif not sink["answered"]:
            posted = "not tried: the sink document stopped answering after the switch"
        elif sink["length"] > 0:
            posted = "FAIL: the keys stayed in the runner's own session (they arrived in its TextEdit document, not at the login window)"
        elif arrived is not None and arrived < 120:
            posted = "FAIL: the keys arrived nowhere (not in the runner's document, and the login window's password field did not change)"
        elif eyes and names and S["chose"] != "user":
            posted = "not tried: the login window asks for a name too, which only the driver inside its session can fill in"
        else:
            type_password("here")
            if logged_in(45):
                S["delivery"] = "keys posted by the job from the runner's own session, as the harness always has"
                posted = "PASS"
            else:
                after = sink_read()
                if after["answered"] and after["length"] > 0:
                    posted = "FAIL: the keys went into the runner's own session"
                else:
                    posted = "FAIL: macOS did not log %s in" % ADMIN
    DETAIL["posted_by_job"] = posted
    log("password by keys posted from the job's own session: %s" % posted)
    sink_close()
    if console_owner() == ADMIN:
        return True

    # 2. The same driver, started inside the login window's own session.
    inside_result = "not tried: the driver could not be started inside the login window's session"
    if hands:
        if eyes:
            secure, names = login_fields()
            if names and S["chose"] != "user":
                click_at("login", names[0]["frame"], "the name field")
                qa("login", "key", "0", "--mods", "cmd", quiet=True)
                qa("login", "type", ADMIN, quiet=True)
                qa("login", "key", "48", quiet=True)
                time.sleep(0.4)
            elif secure:
                click_at("login", secure[0]["frame"], "the password field")
                time.sleep(0.3)
                qa("login", "key", "0", "--mods", "cmd", quiet=True)
                qa("login", "key", "51", quiet=True)
        type_password("login")
        if logged_in(90):
            S["delivery"] = "the same driver started inside the login window's session with `sudo launchctl bsexec` (a public command)"
            inside_result = "PASS"
        else:
            outline("login", "login-window-after-password", login_ui(), depth=30, maximum=900)
            inside_result = "FAIL: macOS did not log %s in" % ADMIN
    DETAIL["posted_inside"] = inside_result
    log("password by the driver inside the login window's session: %s" % inside_result)
    return console_owner() == ADMIN


def setup_screens(context):
    """If macOS still shows a first-login screen: the least that reaches the
    desktop. Nothing is signed in to; sharing analytics is left off."""
    pressed = []
    for turn in range(14):
        apps = qa(context, "apps", quiet=True).get("applications") or []
        tour = [app for app in apps if app.get("bundle") == "com.apple.SetupAssistant" or app.get("name") == "Setup Assistant"]
        if not tour:
            break
        target = ["--pid", str(tour[0]["pid"])]
        shot(context, "first-login-screen-%d" % (turn + 1))
        outline(context, "first-login-screen-%d" % (turn + 1), target, depth=30, maximum=900)
        for box in elements(context, target, "--role", "AXCheckBox"):
            words = " ".join(str(box.get(key, "")) for key in ("title", "description")).lower()
            if box.get("value") == "1" and ("analytics" in words or "share" in words) and usable(box.get("frame")):
                click_at(context, box["frame"], "an analytics checkbox (off)")
        for label in ("Set Up Later", "Not Now", "Skip", "Don’t Use", "Don't Use", "Later", "Continue Without", "Agree", "Continue", "Get Started", "Done", "OK"):
            buttons = [row for row in elements(context, target, "--role", "AXButton", "--title", label)
                       if usable(row.get("frame")) and row.get("enabled", True)]
            if buttons:
                click_at(context, buttons[0]["frame"], "\"%s\" on a first-login screen" % label)
                pressed.append(label)
                break
        else:
            NOTES.append("A first-login screen had no button this probe knows; it was left as it is.")
            break
        time.sleep(2.5)
    if pressed:
        NOTES.append("First-login screens were still shown; buttons pressed, in order: %s. Nothing was signed in to." % ", ".join(pressed))
    return pressed


def stage_session():
    S["no_shots"] = ""
    S["uid"] = int(run(["/usr/bin/id", "-u", ADMIN], quiet=True)[1].strip() or 0)
    owner, record = note_console("after-login")
    R["console_after"] = owner
    R["record_after"] = describe_record(record)
    R["check_a"] = owner == ADMIN
    R["check_b"] = record_says(record, ADMIN)
    run(["/usr/bin/sudo", "-n", "/bin/chmod", "1777", SHARED + "/shots"], quiet=True)

    def desktop_up():
        return any(user == ADMIN for _, user in owners("/Finder.app/Contents/MacOS/Finder")) and \
               any(user == ADMIN for _, user in owners("/Dock.app/Contents/MacOS/Dock"))
    up = wait_for(desktop_up, 150, 2.0)
    log("Finder and Dock of %s running: %s" % (ADMIN, bool(up)))
    time.sleep(4.0)
    inside = qa("user", "probe", timeout=25)
    context = "user"
    if inside.get("_code") != 0 or not inside.get("accessibilityTrusted"):
        as_root = qa("user-root", "probe", timeout=25)
        NOTES.append("Started as %s inside its session the driver %s; started there as root it %s." % (
            ADMIN, "did not run" if inside.get("_code") != 0 else "may not read other apps",
            "did not run" if as_root.get("_code") != 0 else "may read other apps %s" % as_root.get("accessibilityTrusted")))
        if as_root.get("_code") == 0 and as_root.get("accessibilityTrusted"):
            context, inside = "user-root", as_root
    S["session_context"] = context
    DETAIL["inside"] = ("a program started by the job inside that session (%s) is in the session of \"%s\", on the console: %s; "
                        "it may read other apps %s, post input %s, capture the screen %s") % (
        "as " + ADMIN if context == "user" else "as root", inside.get("sessionUser", "?"), inside.get("sessionOnConsole"),
        inside.get("accessibilityTrusted"), inside.get("postEvents"), inside.get("screenCapture"))
    log(DETAIL["inside"])
    setup_screens(context)

    # C and D: the Finder and Dock of the session that is on the console.
    apps = qa(context, "apps", quiet=True).get("applications") or []
    for key, bundle, suffix in (("finder", "com.apple.finder", "/Finder.app/Contents/MacOS/Finder"), ("dock", "com.apple.dock", "/Dock.app/Contents/MacOS/Dock")):
        pids = [app.get("pid") for app in apps if app.get("bundle") == bundle]
        if pids:
            user = owner_of(pids[0])
            R[key] = "%s (pid %s, the one in the session on the console)" % (user, pids[0])
        else:
            mine = [pid for pid, user in owners(suffix) if user == ADMIN]
            user = ADMIN if mine else ""
            R[key] = "%s (pid %s; the session's own list of apps did not answer)" % (ADMIN, mine[0]) if mine else "none running as %s" % ADMIN
        # That user has one desktop, and macOS reports it as the one on the console (check B).
        R["check_c" if key == "finder" else "check_d"] = user == ADMIN and R["check_b"]
    others = ["%s pid %d (%s)" % (comm.rsplit("/", 1)[-1], pid, user) for pid, user, comm in processes()
              if (comm.endswith("/Finder.app/Contents/MacOS/Finder") or comm.endswith("/Dock.app/Contents/MacOS/Dock")) and user != ADMIN]
    if others:
        NOTES.append("The runner's own Finder and Dock keep running in its session, off the console: %s." % ", ".join(others))

    # E: capture the desktop, focus TextEdit, type a line, read it back.
    desktop = shot(context, "desktop-of-%s" % ADMIN)
    pictured, why = is_picture(desktop)
    # A process macOS does not let capture the screen still gets a picture: the wallpaper, without the windows.
    may_capture = bool(inside.get("screenCapture"))
    document = SHARED + "/probe-line.txt"
    run(["/usr/bin/sudo", "-n", "-u", ADMIN, "/usr/bin/touch", document], quiet=True)
    run(wrap("user", ["/usr/bin/open", "-a", "TextEdit", document]))
    found = qa(context, "ax", "find", "--bundle", TEXTEDIT, "--role", "AXTextArea", "--timeout", "30", quiet=True, timeout=45)
    areas = [row for row in (found.get("elements") or []) if usable(row.get("frame"))]
    typed = read = focused_ok = False
    if areas:
        click_at(context, areas[0]["frame"], "the TextEdit document on %s's desktop" % ADMIN)
        time.sleep(0.8)
        focused = qa(context, "ax", "focused", quiet=True)
        focused_ok = bool(focused.get("found")) and (focused.get("element") or {}).get("role") == "AXTextArea"
        typed = bool(qa(context, "type", LINE).get("ok"))
        time.sleep(1.0)
        value = qa(context, "ax", "value", "--bundle", TEXTEDIT, "--role", "AXTextArea", quiet=True)
        read = bool(value.get("found")) and value.get("text", "").strip() == LINE
        shot(context, "textedit-line-typed")
    else:
        front = (qa(context, "probe", quiet=True).get("frontmost") or {}).get("pid")
        if front:
            outline(context, "no-textedit-document-frontmost-app", ["--pid", str(front)], depth=12, maximum=400)
        shot(context, "no-textedit-document")
    # The line can only be read back from a document that had the keyboard.
    R["check_e"] = bool(pictured and may_capture and typed and read)
    R["textedit"] = PASS if R["check_e"] else FAIL
    DETAIL["textedit"] = ("screenshot of the desktop: %s (%s); macOS lets that process capture windows: %s; TextEdit's document focused: %s; "
                          "line typed: %s; the same line read back: %s") % (
        "a picture" if pictured else "not a picture", why, may_capture, focused_ok, typed, read)
    log("interaction: %s" % DETAIL["textedit"])

    # F: still the console user.
    owner, record = note_console("after-interaction")
    R["check_f"] = owner == ADMIN and record_says(record, ADMIN)
    R["still"] = PASS if R["check_f"] else FAIL
    DETAIL["still"] = "/dev/console owner: %s; console record: %s" % (owner, describe_record(record))


# ---------------------------------------------------------------- the result

def conclusion(problem=""):
    if problem:
        return "NO CONCLUSION: the probe itself failed before it could measure this."
    if all(R[key] for key in ("check_a", "check_b", "check_c", "check_d", "check_e", "check_f")):
        return "A. KNOWN PIKYQA CONSOLE SESSION PROVEN\n   -> interactive Tahoe session is worth preparing."
    lines = "B. GITHUB HOSTED RUNNER LIMITATION\n   -> stop trying to validate login-password-gated Open Anyway this way."
    if R["trigger"] == FAIL or R["login_window"] == FAIL:
        lines += "\n\nGITHUB HOSTED RUNNER LIMITATION:\nCANNOT ESTABLISH KNOWN-USER CONSOLE SESSION"
    return lines


def write_result(problem=""):
    run_url = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"), os.environ.get("GITHUB_REPOSITORY", ""),
                                         os.environ.get("GITHUB_RUN_ID", ""))
    rows = [
        ("1. Run", "%s (id %s)" % (run_url, os.environ.get("GITHUB_RUN_ID", "?"))),
        ("2. macOS", "%s (%s), image %s, standard runner %s" % (S.get("version", "?"), S.get("build", "?"), S.get("image", "?"), os.environ.get("QA_RUNNER_LABEL", "?"))),
        ("3. Initial console user", "%s (console record: %s)" % (S.get("initial_owner", "?"), S.get("initial_record", "?"))),
        ("4. Temporary admin creation", "%s (%s)" % (R["admin"], DETAIL.get("admin", ""))),
        ("5. Fast User Switching UI trigger", "%s (%s)" % (R["trigger"], "by %s; %s" % (S["route"], DETAIL.get("trigger", "")) if S["route"] else DETAIL.get("trigger", "not reached"))),
        ("6. Login window reached", "%s (%s)" % (R["login_window"], DETAIL.get("login_window", "not reached"))),
        ("7. Login password accepted", "%s (%s)" % (R["password"], "; ".join(part for part in (
            "typed by: %s" % S["delivery"] if S["delivery"] else "",
            "keys posted from the job's own session: %s" % DETAIL["posted_by_job"] if "posted_by_job" in DETAIL else "",
            "driver inside the login window's session: %s" % DETAIL["posted_inside"] if "posted_inside" in DETAIL else "") if part) or "not reached")),
        ("8. /dev/console after login", R["console_after"]),
        ("9. ConsoleUser record after login", R["record_after"]),
        ("10. Finder owner", R["finder"]),
        ("11. Dock owner", R["dock"]),
        ("12. TextEdit headed input/readback", "%s (%s)" % (R["textedit"], DETAIL.get("textedit", "not reached"))),
        ("13. Console user still %s afterward" % ADMIN, "%s (%s)" % (R["still"], DETAIL.get("still", "not reached"))),
        ("14. Teardown", "see the run's last step"),
    ]
    checks = [("A", "check_a", "stat -f %%Su /dev/console returns exactly %s" % ADMIN),
              ("B", "check_b", "State:/Users/ConsoleUser reports %s, on the console, login complete" % ADMIN),
              ("C", "check_c", "the Finder of the visible desktop runs as %s" % ADMIN),
              ("D", "check_d", "the Dock of the visible desktop runs as %s" % ADMIN),
              ("E", "check_e", "a process started inside that session captured the desktop, focused TextEdit, typed a line and read it back"),
              ("F", "check_f", "the console user was still %s after that" % ADMIN)]
    text = ["# Console-user probe", ""]
    if problem:
        text += ["**The probe did not run to its end (a fault in the probe itself): %s**" % problem, ""]
    text += ["| | |", "| --- | --- |"]
    text += ["| %s | %s |" % (name, str(value).replace("|", "/").replace("\n", " ")) for name, value in rows]
    text += ["", "## The six checks", "", "| | | |", "| --- | --- | --- |"]
    text += ["| %s | %s | %s |" % (letter, "yes" if R[key] else "NO", words) for letter, key, words in checks]
    if DETAIL.get("inside"):
        text += ["", DETAIL["inside"][0].upper() + DETAIL["inside"][1:] + "."]
    text += ["", "## Conclusion", "", "```", conclusion(problem), "```"]
    if S["stopped_at"]:
        text += ["", "Stopped at: %s." % S["stopped_at"]]
    text += ["", "## What the probe changed on this machine", ""]
    text += ["- %s" % line for line in CHANGES] or ["- Nothing."]
    text += ["- The temporary administrator `%s` was created, and is deleted in the run's last step." % ADMIN,
             "- Never: a private Apple API, a TCC database, SIP, Gatekeeper, auto-login, a restart, a password reset."]
    if NOTES:
        text += ["", "## Also seen", ""] + ["- %s" % line for line in NOTES]
    save_text("RESULT.md", "\n".join(text))
    public = dict((key, value) for key, value in S.items() if key != "secret")
    save_text("results.json", json.dumps({"results": R, "detail": DETAIL, "state": public, "changes": CHANGES, "notes": NOTES,
                                          "conclusion": conclusion(problem), "problem": problem}, indent=2, ensure_ascii=False))
    print("\n".join(text), flush=True)


def scrub():
    """The last lock: no text file that leaves this machine may hold the password."""
    if not S["secret"]:
        return
    for folder, _, files in os.walk(OUT):
        for name in files:
            if name.endswith(".png"):
                continue
            target = os.path.join(folder, name)
            try:
                with open(target, "rb") as handle:
                    held = S["secret"].encode("utf-8") in handle.read()
            except OSError:
                continue
            if held:
                os.remove(target)
                print("::warning::A file of the evidence held the temporary password and was removed: %s" % name, flush=True)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" \
            or run(["/usr/bin/id", "-un"], quiet=True)[1].strip() != "runner":
        print("This probe switches the user at the screen of the machine it runs on. It only runs on a GitHub-hosted runner.", file=sys.stderr)
        return 2
    os.makedirs(OUT, exist_ok=True)
    try:
        with open(CREDENTIALS, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("ADMIN_PASSWORD="):
                    S["secret"] = line.split("=", 1)[1].strip()
    except OSError:
        pass
    if len(S["secret"]) < 8:
        print("This run has no temporary administrator password.", file=sys.stderr)
        return 2
    problem = ""
    try:
        if not stage_baseline():
            S["stopped_at"] = "the console user was not the runner to begin with"
        elif not stage_admin():
            S["stopped_at"] = "the temporary administrator"
        else:
            stage_prepare()
            sink_open()
            outcome = stage_trigger()
            if not outcome:
                S["stopped_at"] = "Fast User Switching could not be triggered from the job with macOS's own UI"
            elif not stage_login_window(outcome):
                S["stopped_at"] = "the login window was not reached"
            else:
                done = stage_password_in_panel() if outcome == "panel" else stage_password_at_login_window()
                R["password"] = PASS if done else FAIL
                if not done:
                    owner, record = note_console("after-password")
                    R["console_after"], R["record_after"] = owner, describe_record(record)
                    S["stopped_at"] = "the login window did not accept the password typed by the job"
                else:
                    stage_session()
                    if not (R["check_a"] and R["check_b"]):
                        S["stopped_at"] = "a login happened but macOS does not report %s as the console user" % ADMIN
                    elif not (R["check_c"] and R["check_d"] and R["check_e"]):
                        S["stopped_at"] = "a %s desktop exists but the job could not work in it" % ADMIN
                    elif not R["check_f"]:
                        S["stopped_at"] = "%s did not stay the console user" % ADMIN
    except Exception:  # noqa: BLE001  (whatever went wrong, the result is still written)
        problem = traceback.format_exc().strip().splitlines()[-1][:300]
        log("the probe itself failed:\n%s" % traceback.format_exc())
    finally:
        sink_close()
        write_result(problem)
        scrub()
    return 3 if problem else 0


if __name__ == "__main__":
    sys.exit(main())
