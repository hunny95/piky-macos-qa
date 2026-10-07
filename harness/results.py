#!/usr/bin/python3
"""Writes RESULTS.md from the run's list of results."""
import json
import os

from qalib import FAIL, INCONCLUSIVE, INFO, LIMIT, NOTRUN, OUT, PASS, output, save_text

# The worst result of an area is the area's result.
ORDER = [FAIL, INCONCLUSIVE, LIMIT, NOTRUN, PASS]
AREAS = [
    ("Safari browser download", ("1 Safari download",)),
    ("Gatekeeper", ("2 Gatekeeper", "2b Second install (no quarantine)")),
    ("First-run UI", ("3 First run",)),
    ("PIKY's own permissions", ("4 PIKY's own permissions", "5 ⌥Space before Accessibility", "6 A PIKY that may work")),
    ("⌥Space", ("7 ⌥Space",)),
    ("Text Pick", ("8 Text Pick",)),
    ("Finder file Pick", ("9 Finder file Pick",)),
    ("Camera", ("10 Camera",)),
    ("⌘Return into TestReceiver", ("11 ⌘Return into TestReceiver",)),
    ("Undo, New Pack, Library, restart", ("12 Undo, New Pack, Library, restart",)),
]


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def worst(entries):
    statuses = [entry["status"] for entry in entries if entry["status"] != INFO]
    for status in ORDER:
        if status in statuses:
            return status
    return INFO if entries else NOTRUN


def write(results, context, release, state):
    version = output(["/usr/bin/sw_vers", "-productVersion"]).splitlines()[0] if results else "?"
    build = output(["/usr/bin/sw_vers", "-buildVersion"]).splitlines()[0] if results else "?"
    environment = dict((name, os.environ.get(name, "")) for name in (
        "ImageOS", "ImageVersion", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "RUNNER_OS", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
        "GITHUB_SHA", "GITHUB_SERVER_URL", "QA_RUNNER_LABEL"))
    counts = dict((status, len([entry for entry in results if entry["status"] == status])) for status in (PASS, FAIL, LIMIT, INCONCLUSIVE, NOTRUN, INFO))
    lines = [
        "# PIKY headed QA: macOS %s (%s) on GitHub-hosted `%s`" % (version, build, environment["QA_RUNNER_LABEL"] or "?"),
        "",
        "| | |",
        "| --- | --- |",
        "| File under test | `%s`, PIKY %s (%s), not notarized |" % (release["PIKY_DMG_NAME"], release["PIKY_VERSION"], release["PIKY_BUILD"]),
        "| Expected | %s bytes, SHA-256 `%s` |" % (release["PIKY_DMG_BYTES"], release["PIKY_DMG_SHA256"]),
        "| Downloaded from | %s |" % release["PIKY_DMG_URL"],
        "| Machine | %s, image %s %s, %s; a standard GitHub-hosted runner, destroyed after the job |" % (
            environment["RUNNER_ARCH"] or "?", environment["ImageOS"] or "?", environment["ImageVersion"] or "?", environment["RUNNER_ENVIRONMENT"] or "?"),
        "| Run | %s/%s/actions/runs/%s (attempt %s), harness commit `%s` |" % (
            environment["GITHUB_SERVER_URL"], environment["GITHUB_REPOSITORY"], environment["GITHUB_RUN_ID"], environment["GITHUB_RUN_ATTEMPT"], environment["GITHUB_SHA"][:12]),
        "| Installed copy used after Gatekeeper | %s |" % (context.get("install") or "none"),
        "| PIKY exercised under | %s |" % (context.get("mode") or "not reached"),
        "| Results | %s PASS, %s FAIL, %s RUNNER ENVIRONMENT LIMITATION, %s INCONCLUSIVE, %s NOT RUN, %s notes |" % (
            counts[PASS], counts[FAIL], counts[LIMIT], counts[INCONCLUSIVE], counts[NOTRUN], counts[INFO]),
        "",
        "PASS: what a person would see, was seen. FAIL: PIKY did something wrong. RUNNER ENVIRONMENT LIMITATION: the hosted runner",
        "cannot show this. INCONCLUSIVE: the harness could not set the step up, so it says nothing about PIKY. INFO: an observation.",
        "",
        "## By area",
        "",
        "| Area | Result | Checks |",
        "| --- | --- | --- |",
    ]
    for area, stages in AREAS:
        entries = [entry for entry in results if entry["stage"] in stages]
        verdicts = [entry for entry in entries if entry["status"] != INFO]
        lines.append("| %s | **%s** | %s of %s PASS |" % (area, worst(entries), len([entry for entry in verdicts if entry["status"] == PASS]), len(verdicts)))
    lines += ["", "## Every check", "", "| # | Stage | Check | Result | What was seen | Evidence |", "| --- | --- | --- | --- | --- | --- |"]
    for index, entry in enumerate(results, 1):
        lines.append("| %s | %s | %s | **%s** | %s | %s |" % (
            index, cell(entry["stage"]), cell(entry["check"]), entry["status"], cell(entry["detail"]),
            "<br>".join("`%s`" % item for item in entry["evidence"][:6]) + (" …" if len(entry["evidence"]) > 6 else "")))
    timing = context.get("timing") or {}
    lines += ["", "## Timing", ""]
    if timing:
        lines += ["```json", json.dumps(timing, indent=2, sort_keys=True), "```",
                  "", "Measured on a hosted virtual machine. It bounds how slow a delivery can be here; it does not measure a real Mac."]
    else:
        lines.append("No delivery was measured in this run.")
    lines += [
        "", "## What this run cannot show", "",
        "- **A new Mac's permissions.** GitHub's image pre-allows its own agent for Accessibility, Apple Events and screen capture",
        "  (`os/tcc-environment.txt`). Steps marked “runner-attributed permissions” ran PIKY's installed binary under those; they",
        "  show how PIKY behaves on this macOS, not that a person can grant PIKY its permissions.",
        "- **A hand.** Keys, clicks, drags and wheel notches were posted as events at the HID level. Nothing here is evidence about",
        "  trackpad feel, swipe steps, a notch, Retina sharpness or a second display.",
        "- **A real destination.** TestReceiver is an AppKit message box; Slack, Claude and browsers handle pastes and drops differently.",
        "- **Anything the list above marks RUNNER ENVIRONMENT LIMITATION, INCONCLUSIVE or NOT RUN.**",
        "", "## In this folder", "",
        "`RESULTS.md` (this file), `results.jsonl` (the same, for programs), `run.log`, `screenshots/` (%s), `ax/` (what macOS Accessibility" % state.get("shots", 0),
        "said at each step), `os/` (machine, security settings, the runner's existing permissions), `gatekeeper/` (quarantine and first-open",
        "observations), `receiver/received.jsonl` (what TestReceiver got), `piky-diagnostics/` (PIKY's own content-free records),",
        "`logs/` (PIKY's and the system's log lines that name PIKY), `timing.json`.",
        "",
        "Only QA fixtures were selected, picked or delivered. The machine had no personal data and no longer exists.",
    ]
    save_text("RESULTS.md", "\n".join(lines))
    return os.path.join(OUT, "RESULTS.md")
