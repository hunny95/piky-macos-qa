#!/usr/bin/python3
"""An interactive session on the temporary administrator's OWN desktop.

On macOS 26, Gatekeeper's Open Anyway asks for the password of the user who
owns the desktop. So the tester's desktop has to belong to a user whose
password is known: the temporary administrator is made the console user, by
the mechanism the console-user probe proved (run 37695904701), and RustDesk
is started inside that session, never under the runner's own account.

    /usr/bin/python3 interactive/console_session.py <step>

    login     Fast User Switching through the Users menu, then macOS's own
              login window; verified by what macOS reports
    gate      the control gate: TextEdit, type a sentence, read it back from
              the document, change focus with clicks. NO screenshot
    consent   macOS's screen-capture consent for programs this job starts on
              that desktop, answered in macOS's own dialog
    ready     after RustDesk is up: still the console user, RustDesk runs in
              that session, input still arrives, no dialog is in the way

No screenshot, screenshot helper or screen-analysis tool is used before the
control gate has passed: on a new account the first screen capture makes
macOS raise a consent dialog, and in the probe that dialog took the keyboard
from the very test that came after it.

What this never does: call a private Apple API, write to a TCC database,
change SIP or Gatekeeper, remove a quarantine attribute, set up auto-login,
restart, or reset a password. The temporary password is read from the
session's private file, handed to the driver on standard input, and typed
only into macOS's own password fields. Standard library only.
"""
import importlib.util
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_probe():
    """The probe's plumbing and its proven steps (probe/console_user_probe.py), used as a library."""
    spec = importlib.util.spec_from_file_location("console_user_probe", os.path.join(ROOT, "probe", "console_user_probe.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = load_probe()
ADMIN = p.ADMIN
TEXTEDIT = p.TEXTEDIT
STATE_FILE = os.path.join(p.STATE, "console-session.json")
NO_SHOTS = "no screenshot is taken before the control gate has passed"
# The sentence asked for, and a spare without a space in it: on a new account
# macOS's inline predictions and spelling correction are on, they act when
# Space is typed, and they can change what a document ends up holding.
GATE_LINES = ("The quick brown fox jumps over 26 lazy dogs", "quick-brown-fox-jumps-over-26-lazy-dogs")
SECOND_LINE = "-twice"
DOCUMENT = p.SHARED + "/control-gate.txt"
ALLOW_LABELS = ("Allow", "Allow For One Month", "Allow for One Month", "Continue To Allow", "Continue to Allow")
# Windows of these never are a system dialog.
QUIET_OWNERS = ("Dock", "Window Server", "Finder", "TextEdit", "RustDesk", "Wallpaper", "WindowManager", "Spotlight")
ROWS = []


# ---------------------------------------------------------------- plumbing

def remember():
    kept = dict((key, value) for key, value in p.S.items() if key not in ("secret", "no_shots"))
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump({"state": kept, "changes": p.CHANGES}, handle)


def recall():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        return False
    p.S.update(saved.get("state") or {})
    return bool(p.S.get("uid"))


def row(name, value):
    ROWS.append((name, value))
    p.log("%s: %s" % (name, value))


def finish(step, title, good, label=""):
    """The step's result: a file in the evidence, the log, and the run's summary. No secret is in it."""
    text = ["## %s: %s" % (title, "passed" if good else "DID NOT PASS"), ""]
    if label and not good:
        text += ["**%s**" % label, ""]
    text += ["| | |", "| --- | --- |"]
    text += ["| %s | %s |" % (name, str(value).replace("|", "/").replace("\n", " ")) for name, value in ROWS]
    if step == "login" and p.CHANGES:
        text += ["", "Changed on this machine for the switch:", ""] + ["- %s" % line for line in p.CHANGES]
    if p.NOTES:
        text += ["", "Also seen:", ""] + ["- %s" % line for line in p.NOTES]
    body = "\n".join(text) + "\n"
    p.save_text("%s.md" % step.upper(), body)
    print(body, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(body + "\n")
    if not good:
        print("::error::%s" % (label or "%s did not pass" % title), flush=True)
    p.scrub()
    return 0 if good else 1


def admin_uid():
    """The account's number. Right after a first login the directory can be slow to answer."""
    def ask():
        text = p.run(["/usr/bin/id", "-u", ADMIN], quiet=True, timeout=20)[1].strip()
        return int(text) if text.isdigit() else 0
    return int(p.wait_for(ask, 60, 2.0) or 0)


def session(context, seconds=0):
    """What the driver reports from inside a session. It asks nothing about screen capture."""
    def ask():
        data = p.qa(context, "session", quiet=True, timeout=20)
        return data if data.get("_code") == 0 else None
    return p.wait_for(ask, seconds, 2.0) or {}


def frontmost(context):
    return (session(context).get("frontmost") or {}).get("bundle", "")


def console_is_admin(label):
    owner, record = p.note_console(label)
    return owner == ADMIN and p.record_says(record, ADMIN), owner, p.describe_record(record)


def desktop_owners():
    finder = [user for _, user in p.owners("/Finder.app/Contents/MacOS/Finder")]
    dock = [user for _, user in p.owners("/Dock.app/Contents/MacOS/Dock")]
    return ADMIN in finder, ADMIN in dock


def who_has_the_keyboard(context, label):
    """When a key did not arrive: which application holds the keyboard, and what its windows are. No screenshot."""
    focused = p.qa(context, "ax", "focused", quiet=True, timeout=15)
    if not focused.get("found"):
        p.log("%s: Accessibility reports no focused element" % label)
        return ""
    name = "%s (pid %s)" % (focused.get("application") or "?", focused.get("pid"))
    p.log("%s: the keyboard is with %s, in a %s" % (label, name, (focused.get("element") or {}).get("role", "?")))
    if focused.get("pid"):
        p.outline(context, "%s-keyboard-owner" % label, ["--pid", str(focused["pid"])], depth=14, maximum=500)
    return name


def text_areas(context, seconds):
    return p.find_when_ready(context, ["--bundle", TEXTEDIT], ["--role", "AXTextArea"], seconds)


def document_text(context):
    """The TextEdit document's text, read from the application through Accessibility. Never from the screen."""
    value = p.qa(context, "ax", "value", "--bundle", TEXTEDIT, "--role", "AXTextArea", quiet=True, timeout=20)
    return value.get("text", "") if value.get("found") else None


def dock_item(context, title):
    rows = [item for item in p.elements(context, ["--bundle", "com.apple.dock"], "--role", "AXDockItem", "--title", title)
            if p.usable(item.get("frame"))]
    return rows[0] if rows else None


def bring_textedit_forward(context):
    """A click on TextEdit's Dock icon, or on its document if the Dock does not say where the icon is."""
    item = dock_item(context, "TextEdit")
    if item:
        p.click_at(context, item["frame"], "TextEdit in the Dock")
    else:
        areas = text_areas(context, 10)
        if areas:
            p.click_at(context, areas[0]["frame"], "the TextEdit document")
    return bool(p.wait_for(lambda: frontmost(context) == TEXTEDIT, 8, 1.0))


# ---------------------------------------------------------------- login

def type_at_login_window():
    """A harmless word first, to see that this job's keys are not landing in the
    runner's own session; then the password and Return. As in the probe."""
    # In the probe some twenty seconds passed between the switch and the first key: the login window was ready.
    time.sleep(15.0)
    # What the watching document holds now. It need not be empty: what counts is whether it CHANGES.
    # (Run 37743973465 stopped here wrongly: the document still held the word of its own self-test.)
    before = p.sink_read()
    posted = p.qa("here", "type", p.CANARY, quiet=True).get("_code") == 0
    time.sleep(1.2)
    after = p.sink_read() if posted else {"answered": False, "length": -1}
    for _ in range(len(p.CANARY) + 3):
        if not posted or p.qa("here", "key", "51", quiet=True).get("_code") != 0:
            break
    time.sleep(0.4)
    p.log("word typed before the password: characters in the runner's own document before %s, after %s" % (
        before["length"] if before["answered"] else "no answer", after["length"] if after["answered"] else "no answer"))
    if not posted:
        return False, "the driver could not post keys once the runner's session had left the screen"
    if before["answered"] and after["answered"] and after["length"] != before["length"]:
        return False, "the job's keys arrived in the runner's own session, so the password was NOT typed"
    if not (before["answered"] and after["answered"]):
        p.NOTES.append("The document that watches for stray keys in the runner's session did not answer around the switch.")
    for attempt in (1, 2):
        p.type_password("here")
        if p.logged_in(60):
            return True, "typed by keys posted from the job's own session, then Return%s" % (" (second try)" if attempt == 2 else "")
        # Only while the login window still has the screen: never type a password at a desktop.
        if attempt == 2 or p.console_owner() != "root":
            break
        p.log("the login window did not take the first try; clearing its field and typing once more")
        p.qa("here", "key", "0", "--mods", "cmd", quiet=True)
        p.qa("here", "key", "51", quiet=True)
        time.sleep(6.0)
    return False, "macOS did not log %s in" % ADMIN


def step_login():
    p.S["no_shots"] = NO_SHOTS
    p.S["version"] = p.run(["/usr/bin/sw_vers", "-productVersion"], quiet=True)[1].strip()
    p.S["build"] = p.run(["/usr/bin/sw_vers", "-buildVersion"], quiet=True)[1].strip()
    p.S["runner_name"] = p.run(["/usr/bin/id", "-F"], quiet=True)[1].strip()
    owner, record = p.note_console("initial")
    p.S["initial_owner"] = owner
    p.S["runner_loginwindow"] = [pid for pid, _ in p.owners(p.LOGINWINDOW)]
    row("macOS", "%s (%s), image %s %s" % (p.S["version"], p.S["build"], os.environ.get("ImageOS", ""), os.environ.get("ImageVersion", "")))
    row("Console user before", "%s (%s)" % (owner, p.describe_record(record)))
    if owner != "runner":
        return finish("login", "Log in as %s at the screen" % ADMIN, False, "The console user was not the runner to begin with.")
    if not p.stage_admin():
        row("Temporary administrator", "FAIL (%s)" % p.DETAIL.get("admin", ""))
        return finish("login", "Log in as %s at the screen" % ADMIN, False, "The temporary administrator is not usable.")
    row("Temporary administrator", "PASS (%s)" % p.DETAIL.get("admin", ""))
    p.stage_prepare()
    p.sink_open()
    outcome = p.route_users_menu()
    row("Fast User Switching by the Users menu", "PASS (%s)" % p.DETAIL.get("users_menu", "") if outcome else "FAIL (%s)" % p.DETAIL.get("users_menu", "no result"))
    if not outcome:
        p.sink_close()
        return finish("login", "Log in as %s at the screen" % ADMIN, False,
                      "GITHUB HOSTED RUNNER LIMITATION: CANNOT ESTABLISH KNOWN-USER CONSOLE SESSION (the Users menu did not switch user)")
    reached = p.stage_login_window(outcome)
    row("Login window reached", "%s (%s)" % ("PASS" if reached else "FAIL", p.DETAIL.get("login_window", "")))
    if not reached:
        p.sink_close()
        return finish("login", "Log in as %s at the screen" % ADMIN, False, "The login window was not reached.")
    if outcome == "panel":
        done, how = p.stage_password_in_panel(), "typed into macOS's password panel on the runner's desktop"
    else:
        done, how = type_at_login_window()
    p.sink_close()
    row("Login password accepted", "%s (%s)" % ("PASS" if done else "FAIL", how))
    if not done:
        return finish("login", "Log in as %s at the screen" % ADMIN, False, "The login at macOS's login window did not complete: %s." % how)
    p.S["uid"] = admin_uid()
    good, owner, described = console_is_admin("after-login")
    row("stat -f %Su /dev/console", owner)
    row("State:/Users/ConsoleUser", described)

    def desktop_up():
        return all(desktop_owners())
    p.wait_for(desktop_up, 240, 3.0)
    finder, dock = desktop_owners()
    row("Finder of that desktop runs as %s" % ADMIN, "yes" if finder else "NO")
    row("Dock of that desktop runs as %s" % ADMIN, "yes" if dock else "NO")
    row("The job is still running, with the runner's session off the console", "yes")
    remember()
    good = good and finder and dock and bool(p.S["uid"])
    return finish("login", "Log in as %s at the screen" % ADMIN, good,
                  "A login happened but macOS does not report %s as the console user with its own Finder and Dock." % ADMIN)


# ---------------------------------------------------------------- the control gate (no screenshot)

def change_focus_with_clicks(context):
    """A harmless focus change made by the pointer, checked by which application macOS says is in front."""
    finder = dock_item(context, "Finder")
    if finder:
        p.click_at(context, finder["frame"], "Finder in the Dock")
        away = bool(p.wait_for(lambda: frontmost(context) == "com.apple.finder", 8, 1.0))
        if away:
            # The click opens a Finder window when there was none: close it again.
            p.qa(context, "key", "13", "--mods", "cmd", quiet=True)
            time.sleep(0.8)
        back = bring_textedit_forward(context)
        return away and back, "clicked Finder in the Dock (Finder in front: %s), then TextEdit (TextEdit in front again: %s)" % (away, back)
    # The Dock did not say where its icons are: leave TextEdit by the keyboard, come back by a click on its document.
    p.qa(context, "key", "48", "--mods", "cmd", quiet=True)
    away = bool(p.wait_for(lambda: frontmost(context) not in ("", TEXTEDIT), 8, 1.0))
    areas = text_areas(context, 10)
    if areas:
        p.click_at(context, areas[0]["frame"], "the TextEdit document")
    back = bool(p.wait_for(lambda: frontmost(context) == TEXTEDIT, 8, 1.0))
    return away and back, "left TextEdit with Command-Tab (%s), came back by a click on its document (%s)" % (away, back)


def step_gate():
    title = "Control gate (no screenshot)"
    if not recall():
        return finish("gate", title, False, "GUI CONTROL FAILURE: no %s session was established by the step before." % ADMIN)
    p.S["no_shots"] = NO_SHOTS
    context = "user"
    inside = session(context, 90)
    row("A program started by the job inside that session", "runs as %s in the session of \"%s\"; on the console: %s; may read other apps: %s; may post input: %s" % (
        ADMIN, inside.get("sessionUser", "?"), inside.get("sessionOnConsole"), inside.get("accessibilityTrusted"), inside.get("postEvents"))
        if inside else "did not run")
    if not (inside.get("sessionUser") == ADMIN and inside.get("sessionOnConsole") and inside.get("accessibilityTrusted")):
        return finish("gate", title, False, "GUI CONTROL FAILURE: the job cannot start a working program inside %s's session." % ADMIN)
    p.setup_screens(context)
    p.run(["/usr/bin/sudo", "-n", "-u", ADMIN, "/usr/bin/touch", DOCUMENT], quiet=True)
    p.run(p.wrap("user", ["/usr/bin/open", "-a", "TextEdit", DOCUMENT]))
    areas = text_areas(context, 120)
    row("TextEdit opened a new document", "yes" if areas else "NO")
    if not areas:
        who_has_the_keyboard(context, "no-document")
        return finish("gate", title, False, "GUI CONTROL FAILURE: TextEdit's document did not appear on %s's desktop." % ADMIN)
    focused_ok = typed = read = False
    line = GATE_LINES[0]
    for attempt, line in enumerate(GATE_LINES, 1):
        areas = text_areas(context, 10) or areas
        p.click_at(context, areas[0]["frame"], "the TextEdit document")
        time.sleep(1.0)
        focused = p.qa(context, "ax", "focused", quiet=True, timeout=15)
        focused_ok = bool(focused.get("found")) and (focused.get("element") or {}).get("role") == "AXTextArea"
        typed = p.qa(context, "type", line, quiet=True).get("_code") == 0
        time.sleep(1.5)
        text = document_text(context)
        read = text is not None and text.strip() == line
        p.log("control gate, attempt %d: document focused %s, %d characters typed %s, read back the same %s (%s characters in the document)" % (
            attempt, focused_ok, len(line), typed, read, "no answer" if text is None else len(text)))
        if read:
            break
        who_has_the_keyboard(context, "gate-attempt-%d" % attempt)
        if attempt < len(GATE_LINES):
            # Start again from an empty document, once, with the line that has no space in it.
            p.qa(context, "key", "0", "--mods", "cmd", quiet=True)
            p.qa(context, "key", "51", quiet=True)
            time.sleep(2.0)
            if text is not None and text.strip() and focused_ok:
                p.NOTES.append("The sentence with spaces arrived in TextEdit but macOS changed it on the way (%d characters typed, %d in the document): "
                               "its typing aids act on Space. The line without spaces was used instead." % (len(line), len(text.strip())))
    p.S["gate_text"] = line if read else ""
    row("Document focused by a click", "yes" if focused_ok else "NO")
    row("Line typed with HID key events", "yes: \"%s\"" % line if typed else "NO")
    row("The same line read back from the document (no screen capture)", "yes" if read else "NO")
    if not read:
        return finish("gate", title, False, "GUI CONTROL FAILURE: a line typed by the job did not arrive in TextEdit on %s's desktop." % ADMIN)
    changed, how = change_focus_with_clicks(context)
    row("Focus changed by clicks", "%s (%s)" % ("yes" if changed else "NO", how))
    still, owner, described = console_is_admin("after-gate")
    row("Console user still %s" % ADMIN, "%s (/dev/console: %s; %s)" % ("yes" if still else "NO", owner, described))
    row("Screenshots taken so far", "none")
    remember()
    good = read and changed and still
    return finish("gate", title, good, "GUI CONTROL FAILURE: %s." % ("a click did not change which application is in front" if not changed else "%s is no longer the console user" % ADMIN))


# ---------------------------------------------------------------- screen-capture consent

def consent_dialogs(context):
    """System dialogs on that desktop that ask to allow screen capture: (pid, label of its allow button, the button)."""
    pids = []
    focused = p.qa(context, "ax", "focused", quiet=True, timeout=12)
    if focused.get("found") and focused.get("pid"):
        pids.append(int(focused["pid"]))
    for window in p.qa(context, "windows", quiet=True, timeout=20).get("windows") or []:
        if window.get("owner") in QUIET_OWNERS or not window.get("pid"):
            continue
        if window["pid"] not in pids:
            pids.append(int(window["pid"]))
    found = []
    for pid in pids[:14]:
        target = ["--pid", str(pid)]
        buttons = [item for item in p.elements(context, target, "--role", "AXButton")
                   if p.usable(item.get("frame")) and (item.get("title") in ALLOW_LABELS or item.get("description") in ALLOW_LABELS)]
        # Only a dialog that is about the screen: not any button that happens to say Allow.
        if buttons and p.elements(context, target, "--contains", "screen"):
            label = buttons[0].get("title") if buttons[0].get("title") in ALLOW_LABELS else buttons[0].get("description")
            found.append((pid, label, buttons[0]))
    return found


def undescribed_dialog(context):
    """A dialog-sized window of some system process that Accessibility does not
    describe, while the keyboard is not with TextEdit. Returns the window or None."""
    focused = p.qa(context, "ax", "focused", quiet=True, timeout=12)
    if focused.get("found") and focused.get("bundle") == TEXTEDIT:
        return None
    for window in p.qa(context, "windows", quiet=True, timeout=20).get("windows") or []:
        bounds = window.get("bounds") or [0, 0, 0, 0]
        if window.get("owner") in QUIET_OWNERS + ("Control Center", "Notification Center", "SystemUIServer", "TextInputMenuAgent"):
            continue
        if 200 <= bounds[2] <= 360 and 240 <= bounds[3] <= 460:
            return window
    return None


def answer_consent(context, label):
    """Clicks Allow in macOS's own dialog, as a person at that desktop would. Returns (seen, answered, words)."""
    dialogs = p.wait_for(lambda: consent_dialogs(context), 20, 2.0) or []
    if not dialogs:
        window = undescribed_dialog(context)
        if not window:
            return False, True, "macOS raised no screen-capture dialog"
        # macOS 26 draws Allow as the upper of the dialog's two buttons, about four fifths of the way down.
        bounds = window["bounds"]
        p.log("a dialog of \"%s\" (pid %s) at %s holds the keyboard and Accessibility does not describe it" % (window.get("owner"), window.get("pid"), bounds))
        p.shot(context, "%s-undescribed-dialog" % label)
        p.click_at(context, [bounds[0] + bounds[2] * 0.2, bounds[1] + bounds[3] * 0.81 - 6, bounds[2] * 0.6, 12], "where that dialog draws Allow")
        time.sleep(3.0)
        left = undescribed_dialog(context)
        return True, not left, "a dialog of \"%s\" appeared that Accessibility does not describe; clicked where it draws Allow%s" % (
            window.get("owner"), "" if not left else "; it is STILL there")
    seen = []
    for turn, (pid, name, button) in enumerate(dialogs[:3]):
        p.outline(context, "%s-consent-dialog-%d" % (label, turn + 1), ["--pid", str(pid)], depth=14, maximum=300, values=True)
        p.shot(context, "%s-consent-dialog-%d" % (label, turn + 1))
        p.click_at(context, button["frame"], "\"%s\" in macOS's screen-capture dialog" % name)
        time.sleep(2.5)
        if any(other == pid for other, _, _ in consent_dialogs(context)):
            pressed = p.qa(context, "ax", "press", "--pid", str(pid), "--role", "AXButton", "--title", name, timeout=15)
            p.log("the click did not close the dialog; Accessibility press of \"%s\": %s" % (name, pressed.get("ok")))
            time.sleep(2.5)
        focused = p.qa(context, "ax", "focused", quiet=True, timeout=12)
        if focused.get("found") and focused.get("secure"):
            # macOS asks who allows it: the user at this desktop, with its own password, in a password field.
            p.type_password(context)
            p.S["no_shots"] = ""
            time.sleep(3.0)
            seen.append("\"%s\", then %s's password in macOS's password field" % (name, ADMIN))
        else:
            seen.append("\"%s\"" % name)
    left = consent_dialogs(context)
    return True, not left, "macOS asked to allow screen capture; answered in its dialog with %s%s" % (
        " and ".join(seen), "" if not left else "; the dialog is STILL there")


def page_is_captured(context, name):
    """Is TextEdit's page in a screenshot? A program macOS does not let capture
    windows gets the wallpaper only. A page is one flat shade; a wallpaper is not."""
    areas = text_areas(context, 10)
    if not name or not areas:
        return False, "no screenshot or no document to look for"
    frame = areas[0]["frame"]
    rect = "%d,%d,%d,%d" % (frame[0] + 12, frame[1] + 40, max(20, frame[2] - 24), max(20, frame[3] - 80))
    data = p.qa("here", "image", "contrast", p.path(name), "--rect", rect, quiet=True)
    if not data.get("ok"):
        return False, data.get("error", "unreadable")
    share = data.get("fillShare", 0)
    return share >= 0.85, "one shade covers %.0f%% of where the page is" % (share * 100)


def step_consent():
    title = "Screen capture on %s's desktop" % ADMIN
    if not recall():
        return finish("consent", title, False, "No %s session was established." % ADMIN)
    context = "user"
    p.S["no_shots"] = ""
    bring_textedit_forward(context)
    first = p.shot(context, "first-capture-after-the-gate")
    row("First screenshot, taken only after the control gate", "taken" if first else "NOT taken")
    seen, answered, words = answer_consent(context, "capture")
    row("macOS's screen-capture consent", words)
    if not answered:
        remember()
        return finish("consent", title, False, "RUSTDESK SCREEN-RECORDING LIMITATION: macOS's screen-capture dialog could not be answered through its own UI.")
    bring_textedit_forward(context)
    second = p.shot(context, "capture-after-consent")
    pictured, why = p.is_picture(second)
    paged, where = page_is_captured(context, second)
    row("A program started like RustDesk captures windows, not only the wallpaper", "%s (%s; %s)" % ("yes" if pictured and paged else "NO", why, where))
    again, answered_again, words_again = answer_consent(context, "second") if seen else (False, True, "")
    if again:
        row("Asked a second time", words_again)
    # The keyboard must be back with the document: nothing may be holding it.
    areas = text_areas(context, 10)
    if areas:
        p.click_at(context, areas[0]["frame"], "the TextEdit document")
        time.sleep(0.8)
    p.qa(context, "key", "125", "--mods", "cmd", quiet=True)
    p.qa(context, "type", SECOND_LINE, quiet=True)
    time.sleep(1.2)
    text = document_text(context)
    arrives = text is not None and text.strip() == p.S.get("gate_text", "") + SECOND_LINE
    row("Input still arrives in TextEdit afterwards", "yes" if arrives else "NO")
    if not arrives:
        who_has_the_keyboard(context, "after-consent")
    remember()
    good = bool(first and answered and answered_again and pictured and paged and arrives)
    return finish("consent", title, good,
                  "RUSTDESK SCREEN-RECORDING LIMITATION: a program started by the job cannot capture %s's desktop, or a dialog still holds the keyboard." % ADMIN)


# ---------------------------------------------------------------- the session ready gate

def step_ready(final):
    title = "Session ready gate"
    if not recall():
        return finish("ready", title, False, "No %s session was established." % ADMIN)
    context = "user"
    p.S["no_shots"] = "RustDesk's window shows this session's ID: nothing is captured while it is on screen"
    still, owner, described = console_is_admin("ready")
    row("Console user", "%s (%s)" % (owner, described))
    finder, dock = desktop_owners()
    row("Finder and Dock run as %s" % ADMIN, "yes" if finder and dock else "NO")
    rustdesk = [(pid, user) for pid, user, comm in p.processes() if comm.endswith("/RustDesk.app/Contents/MacOS/RustDesk")]
    as_admin = bool(rustdesk) and all(user == ADMIN for _, user in rustdesk)
    def listed():
        apps = p.qa(context, "apps", quiet=True, timeout=20).get("applications") or []
        return any(app.get("pid") in [pid for pid, _ in rustdesk] for app in apps)
    in_session = bool(p.wait_for(listed, 20, 3.0))
    row("RustDesk runs as %s" % ADMIN, "yes (%s)" % ", ".join("pid %d" % pid for pid, _ in rustdesk) if as_admin else "NO (%s)" % (
        ", ".join("pid %d as %s" % item for item in rustdesk) or "not running"))
    row("RustDesk is an application of %s's session on the console" % ADMIN, "yes" if in_session else "NO")
    seen, answered, words = answer_consent(context, "rustdesk")
    row("Screen-capture consent with RustDesk running", words)
    if seen and answered and not final:
        # macOS was answered while RustDesk was already running: it is started again, once.
        remember()
        p.log("a consent dialog was answered while RustDesk was running: RustDesk is started again once, then this gate is repeated")
        return 10
    brought = bring_textedit_forward(context)
    areas = text_areas(context, 10)
    arrives = False
    if areas:
        p.click_at(context, areas[0]["frame"], "the TextEdit document")
        time.sleep(0.8)
        p.qa(context, "key", "125", "--mods", "cmd", quiet=True)
        p.qa(context, "type", SECOND_LINE, quiet=True)
        time.sleep(1.2)
        text = document_text(context)
        arrives = text is not None and text.strip() == p.S.get("gate_text", "") + SECOND_LINE + SECOND_LINE
    row("With RustDesk running, a click and typed keys still arrive in TextEdit", "yes" if arrives else "NO (TextEdit in front: %s)" % brought)
    if not arrives:
        who_has_the_keyboard(context, "ready")
    left = consent_dialogs(context)
    row("A permission dialog remains", "NO" if not left else "YES (%d)" % len(left))
    # Leave a clean desktop: the test document is closed (it is saved as it goes, so nothing asks).
    p.run(["/usr/bin/sudo", "-n", "/usr/bin/pkill", "-u", str(p.S["uid"]), "-x", "TextEdit"], quiet=True)
    still_after, owner_after, _ = console_is_admin("ready-end")
    row("Console user at the end of the gate", owner_after)
    row("What this gate cannot see", "RustDesk's own picture and input path: a program started the same way, in the same session, "
        "captures windows and its keys and clicks arrive. Only connecting shows RustDesk itself.")
    remember()
    good = bool(still and still_after and finder and dock and as_admin and in_session and answered and arrives and not left)
    label = "The session did not reach the ready gate."
    if not answered or left:
        label = "RUSTDESK SCREEN-RECORDING LIMITATION: a screen-capture dialog could not be answered through macOS's own UI."
    elif not (as_admin and in_session):
        label = "RustDesk is not running inside %s's session." % ADMIN
    elif not arrives:
        label = "GUI CONTROL FAILURE: with RustDesk running, input no longer arrives in TextEdit."
    return finish("ready", title, good, label)


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step not in ("login", "gate", "consent", "ready"):
        print("usage: console_session.py login|gate|consent|ready [--final]", file=sys.stderr)
        return 2
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" \
            or p.run(["/usr/bin/id", "-un"], quiet=True)[1].strip() != "runner":
        print("This switches the user at the screen of the machine it runs on. It only runs on a GitHub-hosted runner.", file=sys.stderr)
        return 2
    os.makedirs(p.OUT, exist_ok=True)
    try:
        with open(p.CREDENTIALS, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("ADMIN_PASSWORD="):
                    p.S["secret"] = line.split("=", 1)[1].strip()
    except OSError:
        pass
    if len(p.S["secret"]) < 8:
        print("This session has no temporary administrator password.", file=sys.stderr)
        return 2
    try:
        if step == "login":
            return step_login()
        if step == "gate":
            return step_gate()
        if step == "consent":
            return step_consent()
        return step_ready("--final" in sys.argv)
    except Exception:  # noqa: BLE001  (whatever went wrong, it is said and the step fails)
        p.log("the step itself failed:\n%s" % traceback.format_exc())
        row("A fault in this step", traceback.format_exc().strip().splitlines()[-1][:300])
        return finish(step, "Step \"%s\"" % step, False, "HARNESS FAILURE in step \"%s\": the session is not opened." % step) or 1


if __name__ == "__main__":
    sys.exit(main())
