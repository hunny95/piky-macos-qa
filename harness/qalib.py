#!/usr/bin/python3
"""Shared by the headed run: running commands, the qa driver, evidence files
and the list of results. Standard library only (the Python that ships with
Xcode is 3.9)."""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.environ.get("QA_SIMULATE", "") != ""
OUT = os.path.abspath(os.environ.get("QA_OUT", os.path.join(ROOT, "evidence")))
TOOLS = os.path.abspath(os.environ.get("QA_TOOLS", os.path.join(ROOT, "build")))
QA_BIN = os.path.join(TOOLS, "qa")
RECEIVER_APP = os.path.join(TOOLS, "TestReceiver.app")
BUNDLE = "app.getpiky.mac"
if SIM:
    # A dry run never looks at, writes to or removes anything real: its
    # "home" and its "Applications" are folders inside the evidence folder.
    HOME = os.path.join(OUT, "sim-home")
    APP = os.path.join(OUT, "sim-root", "Applications", "PIKY.app")
    TEMP = os.path.join(OUT, "sim-tmp")
    for _folder in (HOME, os.path.dirname(APP), TEMP):
        os.makedirs(_folder, exist_ok=True)
else:
    HOME = os.path.expanduser("~")
    APP = "/Applications/PIKY.app"
    TEMP = os.environ.get("RUNNER_TEMP") or "/tmp"
PIKY_BIN = APP + "/Contents/MacOS/PIKY"
SUPPORT = os.path.join(HOME, "Library/Application Support/PIKY")

PASS = "PASS"
FAIL = "FAIL"
LIMIT = "RUNNER ENVIRONMENT LIMITATION"
INCONCLUSIVE = "INCONCLUSIVE"
NOTRUN = "NOT RUN"
INFO = "INFO"

RESULTS = []
STATE = {"shots": 0, "dumps": 0, "scale": 1.0, "stage": "start"}
_sim = None
if SIM:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import simulate as _sim  # noqa: E402  (a stand-in for the Mac, for dry runs of this script)


def now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log(message):
    line = "%s  %s" % (now_iso(), message)
    print(line, flush=True)
    try:
        with open(os.path.join(OUT, "run.log"), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def path(*parts):
    """A file inside the evidence folder (its folder is created)."""
    target = os.path.join(OUT, *parts)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


def save_text(relative, text):
    target = path(relative)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") or not text else text + "\n")
    return relative


def run(command, timeout=60, input_text=None, quiet=False, secret=False):
    """Runs a command to its end. Returns (status, stdout, stderr); never raises.
    `secret` keeps the command line out of the log."""
    shown = "(not shown)" if secret else " ".join(str(part) for part in command)
    if SIM:
        code, out, err = _sim.run(command)
        if not quiet:
            log("$ %s -> %s (simulated)" % (shown[:200], code))
        return code, out, err
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


def output(command, timeout=60):
    """A command's standard output and error together, for a record."""
    code, out, err = run(command, timeout=timeout, quiet=True)
    text = out + (("\n" + err) if err.strip() else "")
    return text.strip() + ("\n[exit status %s]" % code if code != 0 else "")


def qa(*arguments, **options):
    """One call of the driver. Returns its JSON object, with "_code"."""
    quiet = options.get("quiet", False)
    secret = options.get("secret", False)
    arguments = [str(argument) for argument in arguments]
    if SIM:
        data = _sim.qa(arguments)
        data.setdefault("ok", True)
        data.setdefault("_code", 0 if data.get("found", True) else 1)
    else:
        code, out, err = run([QA_BIN] + arguments, timeout=options.get("timeout", 40), input_text=options.get("input_text"), quiet=True)
        lines = [line for line in out.strip().splitlines() if line.strip()]
        try:
            data = json.loads(lines[-1]) if lines else {}
        except ValueError:
            data = {"ok": False, "error": "unreadable answer", "raw": out[:300]}
        if not isinstance(data, dict):
            data = {"ok": False, "error": "unexpected answer"}
        if code != 0 and "error" not in data and err.strip():
            data["error"] = err.strip()[:300]
        data.setdefault("ok", code == 0)
        data["_code"] = code
    if not quiet:
        brief = dict((key, value) for key, value in data.items() if key not in ("elements", "tree", "windows", "applications"))
        if "elements" in data:
            brief["elements"] = len(data["elements"])
        log("qa %s -> %s" % ("(not shown)" if secret else " ".join(arguments)[:220], json.dumps(brief, ensure_ascii=False)[:420]))
    return data


def app_arguments(app):
    """How an application is named to the driver: a bundle identifier, or
    {"pid": n} / {"name": "process"}."""
    if isinstance(app, dict):
        if "pid" in app:
            return ["--pid", str(app["pid"])]
        return ["--name", app["name"]]
    return ["--bundle", app]


def shot(label):
    """A screenshot of the main display, with the pointer in it."""
    STATE["shots"] += 1
    relative = "screenshots/%03d-%s.png" % (STATE["shots"], re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"))
    target = path(relative)
    code, _, err = run(["/usr/sbin/screencapture", "-x", "-C", "-m", "-t", "png", target], timeout=30, quiet=True)
    if SIM:
        open(target, "wb").close()
    if code != 0 or not os.path.exists(target):
        log("screenshot %s failed: %s" % (label, err.strip()[:160]))
        return None
    log("screenshot %s" % relative)
    return relative


def ax_dump(label, app, depth=40, maximum=3000):
    """What Accessibility says about an application's windows, as an outline."""
    STATE["dumps"] += 1
    relative = "ax/%03d-%s.txt" % (STATE["dumps"], re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"))
    code, out, err = run([QA_BIN, "ax", "tree"] + app_arguments(app) + ["--depth", str(depth), "--max", str(maximum), "--text"], timeout=60, quiet=True)
    save_text(relative, out if out.strip() else "(no answer: %s)" % (err.strip() or "exit status %s" % code))
    log("accessibility outline %s (%s lines)" % (relative, len(out.splitlines())))
    return relative


def record(check, status, detail="", evidence=None, data=None, stage=None):
    """One line of the results."""
    entry = {"stage": stage or STATE["stage"], "check": check, "status": status, "detail": detail,
             "evidence": [item for item in (evidence or []) if item], "at": now_iso()}
    if data is not None:
        entry["data"] = data
    RESULTS.append(entry)
    with open(path("results.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    log("RESULT [%s] %s: %s%s" % (status, entry["stage"], check, (" — " + detail) if detail else ""))
    return entry


def wait_for(test, timeout, interval=0.4):
    """Calls `test` until it returns something true; that value, or None."""
    deadline = time.time() + (0.05 if SIM else timeout)
    while True:
        value = test()
        if value:
            return value
        if time.time() >= deadline:
            return None
        pause(interval)


def pause(seconds):
    if not SIM:
        time.sleep(seconds)


def sha256_file(target):
    digest = hashlib.sha256()
    with open(target, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def release():
    """release.env as a dictionary."""
    values = {}
    with open(os.path.join(ROOT, "release.env"), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return values


def center(frame):
    return frame[0] + frame[2] / 2.0, frame[1] + frame[3] / 2.0


def find(app, *selector, **options):
    """Elements of an application matching a selector (see qa ax find)."""
    arguments = ["ax", "find"] + app_arguments(app) + list(selector)
    if options.get("all"):
        arguments.append("--all")
    if options.get("timeout"):
        arguments += ["--timeout", str(options["timeout"])]
    answer = qa(*arguments, quiet=options.get("quiet", True), timeout=options.get("timeout", 0) + 40)
    return answer.get("elements", []) if answer.get("found") else []


def usable(frame):
    return bool(frame) and len(frame) == 4 and frame[2] > 1 and frame[3] > 1


def click_element(app, *selector, **options):
    """Finds an element and clicks its middle with the pointer, as a person
    would. Falls back to the element's own press action when it has no place
    on screen. Returns how it was done, or None when it is not there."""
    elements = find(app, *selector, timeout=options.get("timeout", 0))
    if not elements:
        return None
    element = elements[options.get("index", 0)] if len(elements) > options.get("index", 0) else elements[0]
    frame = element.get("frame")
    if usable(frame) and not options.get("press_only"):
        x, y = center(frame)
        extra = ["--button", "right"] if options.get("right") else []
        qa("click", "%.1f" % x, "%.1f" % y, *extra)
        return {"how": "pointer click", "element": element}
    answer = qa(*(["ax", "press"] + app_arguments(app) + list(selector)))
    return {"how": "accessibility press", "element": element, "ok": answer.get("ok")}


def windows(owner=None):
    arguments = ["windows"] + (["--owner", owner] if owner else [])
    return qa(*arguments, quiet=True).get("windows", [])


def read_dialog(app):
    """The words and buttons of an application's windows, as Accessibility gives them."""
    answer = qa(*(["ax", "tree"] + app_arguments(app) + ["--depth", "14", "--max", "600"]), quiet=True)
    texts, buttons = [], []

    def walk(node):
        role = node.get("role", "")
        if role == "AXStaticText":
            for key in ("value", "title", "description"):
                value = node.get(key)
                if value and value not in texts:
                    texts.append(value)
                    break
        elif role == "AXButton":
            label = node.get("title") or node.get("description")
            if label and label not in buttons:
                buttons.append(label)
        for child in node.get("children", []):
            walk(child)

    if isinstance(answer.get("tree"), dict):
        walk(answer["tree"])
    return {"texts": texts, "buttons": buttons, "readable": bool(answer.get("tree"))}


def contrast(screenshot, frame, inset=1.0):
    """Label-on-fill contrast inside a frame (points) of a screenshot."""
    if not screenshot or not usable(frame):
        return {}
    rect = "%.1f,%.1f,%.1f,%.1f" % (frame[0] + inset, frame[1] + inset, frame[2] - 2 * inset, frame[3] - 2 * inset)
    return qa("image", "contrast", path(screenshot), "--rect", rect, "--scale", STATE["scale"], quiet=True)


def crop(screenshot, frame, label, margin=6.0):
    if not screenshot or not usable(frame):
        return None
    relative = "screenshots/crop-%s.png" % re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    rect = "%.1f,%.1f,%.1f,%.1f" % (max(0, frame[0] - margin), max(0, frame[1] - margin), frame[2] + 2 * margin, frame[3] + 2 * margin)
    answer = qa("image", "crop", path(screenshot), path(relative), "--rect", rect, "--scale", STATE["scale"], quiet=True)
    return relative if answer.get("ok") else None


def pink(screenshot, frame=None, margin=0.0):
    """How much of PIKY's outline colour a region of a screenshot holds."""
    if not screenshot:
        return {}
    arguments = ["image", "color", path(screenshot), "--rgb", "F0226E", "--tol", "48", "--scale", STATE["scale"]]
    if frame:
        arguments += ["--rect", "%.1f,%.1f,%.1f,%.1f" % (max(0, frame[0] - margin), max(0, frame[1] - margin), frame[2] + 2 * margin, frame[3] + 2 * margin)]
    return qa(*arguments, quiet=True)
