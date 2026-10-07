#!/usr/bin/python3
"""A stand-in for the Mac, so run.py can be walked through without touching
a real desktop:  QA_SIMULATE=1 QA_OUT=/tmp/x /usr/bin/python3 harness/run.py

It keeps a toy PIKY (a count, picking or not, which windows are up) and
answers the commands the run uses. It proves nothing about PIKY: it exists to
catch mistakes in the harness before a runner is spent on them.

QA_SIMULATE=blocked plays a runner where Gatekeeper and the permission switch
cannot be passed; anything else plays one where every step works."""
import json
import os
import plistlib

BLOCKED = os.environ.get("QA_SIMULATE") == "blocked"
HOME = os.path.expanduser("~")
RELEASE_NAME = "PIKY-0.2.0-universal.dmg"
TOY = {"running": False, "count": 0, "picking": False, "onboarding": 0, "windows": ["Meet PIKY"], "alert": False, "front": "com.apple.finder",
       "receiver_log": None, "packs": {}, "menu": False, "last_find": "", "launches": 0, "settings_pane": False, "opt": False}


def run(command):
    command = [str(part) for part in command]
    name = os.path.basename(command[0])
    joined = " ".join(command)
    if name == "sw_vers":
        return 0, "14.8.9\n" if "-productVersion" in command else "23J999\n" if "-buildVersion" in command else "ProductName: macOS\nProductVersion: 14.8.9\n", ""
    if name == "pgrep":
        if "PIKY" in joined:
            return (0, "4242\n", "") if TOY["running"] else (1, "", "")
        return 1, "", ""
    if name == "ls":
        if joined.endswith("/Downloads"):
            return 0, RELEASE_NAME + "\n", ""
        return 0, "Applications\nPIKY.app\n", ""
    if name == "stat":
        return 0, "5019073\n", ""
    if name == "shasum":
        return 0, "98e824f265b352ed2e5f567559fd6af3dfb98bb507986aa87a54bc19d1fb3a44  x\n", ""
    if name == "xattr":
        if "-px" in command:
            return 0, plistlib.dumps(["https://example.invalid/PIKY.dmg"], fmt=plistlib.FMT_BINARY).hex(), ""
        return 0, "0083;66f0a1b2;Safari;0A1B2C3D\n", ""
    if name == "hdiutil" and "info" in command:
        return 0, plistlib.dumps({"images": [{"image-path": HOME + "/Downloads/" + RELEASE_NAME, "system-entities": [{"mount-point": "/Volumes/PIKY"}]}]}).decode(), ""
    if name == "open":
        if "--piky-permission-check" in command:
            return 0, "", ""
        if any(part.endswith("/Applications/PIKY.app") for part in command) and "-R" not in command:
            TOY["launches"] += 1
            if BLOCKED and TOY["launches"] == 1:
                TOY["alert"] = True
            else:
                TOY["running"] = True
        if "--log" in command:
            TOY["receiver_log"] = command[command.index("--log") + 1]
        if "-b" in command:
            TOY["front"] = command[command.index("-b") + 1]
        if "-a" in command:
            TOY["front"] = {"Safari": "com.apple.Safari", "TextEdit": "com.apple.TextEdit"}.get(command[command.index("-a") + 1], TOY["front"])
        if "x-apple.systempreferences" in joined:
            TOY["settings_pane"] = True
        return 0, "", ""
    if name == "defaults" and "currentGroup" in command:
        return 0, "AAAAAAAA-0000-0000-0000-000000000001\n", ""
    if name == "kill":
        TOY["running"] = False
        return 0, "", ""
    if name == "PIKY":
        if "--piky-permission-check" in command:
            return 0, '{"accessibility":true,"screen":true}', ""
        TOY["running"] = True
        return 0, "", ""
    return 0, "", ""


def status_label():
    return "PIKY, %s Pick%s%s. Show Pack" % (TOY["count"], "" if TOY["count"] == 1 else "s", ", picking" if TOY["picking"] else "")


def element(role, title, frame, **more):
    data = {"role": role, "title": title, "frame": frame, "enabled": True}
    data.update(more)
    return data


def option(arguments, name):
    return arguments[arguments.index(name) + 1] if name in arguments else None


def find(arguments):
    role, title, contains, near = option(arguments, "--role"), option(arguments, "--title"), option(arguments, "--contains"), option(arguments, "--near")
    app = option(arguments, "--bundle") or option(arguments, "--name") or option(arguments, "--pid") or ""
    TOY["last_find"] = title or contains or near or role or ""
    found = []
    if app == "app.getpiky.mac" and TOY["running"]:
        if contains == "Show Pack":
            found.append(element("AXMenuBarItem", "", [1500, 0, 54, 24], description=status_label(), help="PIKY\n⌥Space starts picking."))
        elif role == "AXWindow":
            found += [element("AXWindow", name, [700, 200, 520, 610]) for name in TOY["windows"] if title in (None, name)]
        elif role == "AXButton" and title:
            steps = ["Continue", "Skip for now"] if not BLOCKED or TOY["onboarding"] >= 9 else ["Continue", "Turn on Accessibility"]
            if "Meet PIKY" in TOY["windows"] and TOY["onboarding"] < len(steps) and steps[TOY["onboarding"]] == title:
                found.append(element("AXButton", title, [1080, 760, 110, 36]))
            if title == "Done" and "PIKY Settings" in TOY["windows"]:
                found.append(element("AXButton", title, [1080, 700, 70, 30]))
            if title == "Undo last Pick" and TOY["count"] > 0:
                found.append(element("AXButton", title, [1540, 2, 14, 20]))
            if title == "Open" and "Library" in TOY["windows"]:
                found.append(element("AXButton", title, [900, 400, 60, 24]))
        elif role == "AXMenuItem" and TOY["menu"]:
            found.append(element("AXMenuItem", title, [1480, 120, 160, 22]))
    elif app == "com.apple.Safari":
        if role == "AXHeading":
            found.append(element("AXHeading", "Checkout health — QA fixture", [40, 120, 1120, 48]))
        elif role == "AXWebArea":
            found.append(element("AXWebArea", "", [0, 96, 1360, 900]))
        elif contains == "elements in place":
            found.append(element("AXStaticText", "", [1100, 950, 200, 20], value="QA page · 20 elements in place"))
    elif app == "com.apple.TextEdit" and role == "AXTextArea":
        found.append(element("AXTextArea", "", [60, 120, 860, 440]))
    elif app == "com.apple.finder" and title:
        found.append(element("AXImage", title, [200 + 10 * len(title), 200, 64, 64]))
    elif app == "TestReceiver" and role == "AXTextArea":
        found.append(element("AXTextArea", "", [580, 140, 720, 110], description="Message"))
    elif app == "com.apple.systempreferences":
        if title == "Open Anyway" and TOY["settings_pane"]:
            found.append(element("AXButton", title, [1100, 700, 110, 24]))
        elif near == "PIKY" and role == "AXCheckBox":
            found.append(element("AXCheckBox", "", [1150, 400, 40, 22], value="0"))
    return {"found": bool(found), "elements": found, "count": len(found)}


def deliver():
    if not TOY["receiver_log"]:
        return
    files = [{"name": "PIKY Pack — QA.md", "url": "file:///nonexistent/note.md", "kind": "text", "bytes": 10, "sha256": "0"}]
    with open(TOY["receiver_log"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"sequence": 1, "timestamp": "2026-10-07T08:00:00.250Z", "via": "drop", "text": None, "textCharacters": 0,
                                 "fileURLs": [item["url"] for item in files], "filenames": [item["name"] for item in files],
                                 "attachmentCount": len(files), "imageCount": 0, "files": files}) + "\n")


def qa(arguments):
    verb = arguments[0]
    if verb == "probe":
        return {"accessibilityTrusted": True, "screenCapture": True, "postEvents": True, "secureInput": False, "sessionOnConsole": True,
                "frontmost": {"bundle": TOY["front"], "name": TOY["front"].split(".")[-1], "pid": 1}, "mainDisplayPoints": [1920, 1080], "cursor": [0, 0]}
    if verb == "windows":
        rows = []
        if TOY["running"]:
            rows.append({"owner": "PIKY", "pid": 4242, "bounds": [700, 200, 520, 610], "layer": 0})
        if TOY["alert"]:
            rows.append({"owner": "CoreServicesUIAgent", "pid": 77, "bounds": [800, 300, 300, 200], "layer": 0})
        if TOY["settings_pane"]:
            rows.append({"owner": "System Settings", "pid": 88, "bounds": [400, 150, 900, 700], "layer": 0})
        owner = option(arguments, "--owner")
        rows = [row for row in rows if owner in (None, row["owner"])]
        return {"windows": rows, "count": len(rows)}
    if verb == "key":
        code, mods = arguments[1], option(arguments, "--mods")
        if code == "49" and mods == "opt" and TOY["running"]:
            if "Meet PIKY" in TOY["windows"] and BLOCKED:
                TOY["windows"].append("PIKY Settings")
            else:
                TOY["picking"] = True
        elif code == "53":
            TOY["picking"] = False
            TOY["menu"] = False
        elif code == "6" and mods == "ctrl,cmd":
            TOY["count"] = max(0, TOY["count"] - 1)
        elif code == "36" and mods == "cmd":
            TOY["picking"] = False
            deliver()
        return {"pressedAt": "2026-10-07T08:00:00.000Z", "pressedAtUtcMs": 1791360000000}
    if verb in ("click", "drag"):
        right = option(arguments, "--button") == "right"
        last = TOY["last_find"]
        if right and TOY["running"]:
            TOY["menu"] = True
        elif last in ("Continue", "Skip for now", "Turn on Accessibility"):
            TOY["onboarding"] += 1
            if last == "Skip for now":
                TOY["windows"] = [name for name in TOY["windows"] if name != "Meet PIKY"]
        elif last == "Done":
            TOY["windows"] = [name for name in TOY["windows"] if name != "PIKY Settings"]
            TOY["onboarding"] = 9
        elif last == "Undo last Pick":
            TOY["count"] = max(0, TOY["count"] - 1)
        elif last == "New Pack" and TOY["menu"]:
            TOY["saved"], TOY["count"], TOY["menu"] = TOY["count"], 0, False
        elif last == "Library…" and TOY["menu"]:
            TOY["windows"].append("Library")
            TOY["menu"] = False
        elif last == "Open":
            TOY["count"] = TOY.get("saved", 0)
        elif last == "Quit PIKY" and TOY["menu"]:
            TOY["running"], TOY["menu"] = False, False
        elif last == "Open Anyway" and not BLOCKED:
            TOY["running"], TOY["alert"] = True, False
        elif last in ("OK", "Done", "Cancel"):
            TOY["alert"] = False
        elif TOY["picking"] and (verb == "drag" or option(arguments, "--count") == "3" or option(arguments, "--mods") == "opt" or last.endswith((".txt", ".png", ".pdf"))):
            TOY["count"] += 1
        TOY["last_find"] = ""
        return {"clicked": [0, 0]}
    if verb == "ax":
        action = arguments[1]
        if action == "find":
            return find(arguments)
        if action == "press":
            return {"found": True, "ok": True}
        if action == "tree":
            texts = [{"role": "AXStaticText", "value": "“PIKY” can’t be opened because Apple cannot check it for malicious software."},
                     {"role": "AXButton", "title": "OK"}, {"role": "AXButton", "title": "Show in Finder"}, {"role": "AXButton", "title": "Open Anyway"}]
            return {"tree": {"role": "AXApplication", "children": texts}}
        if action == "focused":
            return {"found": True, "secure": False, "secureInput": False}
        if action == "text-range":
            return {"found": True, "first": [80, 200, 8, 16], "last": [700, 200, 8, 16], "bounds": [80, 200, 630, 16]}
        if action == "selection":
            return {"found": True, "text": "", "length": 0}
        if action == "value":
            return {"found": True, "length": 0, "endsWithNewline": False, "text": ""}
        if action == "set-frame":
            return {"found": True}
    if verb == "image":
        action = arguments[1]
        if action == "info":
            return {"width": 1920, "height": 1080, "scaleFromMainDisplay": 1.0}
        if action == "contrast":
            return {"contrastRatio": 12.5, "fillColor": "000000", "markColor": "FFFFFF"}
        if action == "color":
            TOY["opt_shots"] = TOY.get("opt_shots", 0) + 1
            return {"count": 900 * (TOY["opt_shots"] % 4), "boxPoints": [80 + TOY["opt_shots"], 566, 300, 220]}
        if action == "diff":
            return {"share": 0.31}
        if action == "crop":
            return {"ok": True}
    if verb == "mod":
        return {"at": "2026-10-07T08:00:00.000Z"}
    return {}
