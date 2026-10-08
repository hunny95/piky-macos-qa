import AppKit
import ApplicationServices
import Carbon
import CoreGraphics
import Foundation

// qa: the driver the headed run uses. Every command prints one JSON object.
// Exit status: 0 done, 1 not found / not true, 2 used wrongly or failed.
//
//   qa probe | session | screens | windows [--owner NAME] [--pid N] | apps | now
//   qa key <keycode> [--mods opt,cmd,ctrl,shift] [--hold-ms N]
//   qa mod <down|up> <opt|cmd|ctrl|shift> [--held opt,…]      qa release
//   qa type <text> | qa type --stdin
//   qa move <x> <y> [--mods …] [--steps N] [--ms N]
//   qa click <x> <y> [--mods …] [--count N] [--button right]
//   qa drag <x1> <y1> <x2> <y2> [--mods …] [--steps N] [--ms N] [--settle-ms N]
//   qa scroll <lines> [--mods …] [--at x,y]
//   qa ax tree|find|press|action <name>|focused|set-frame|text-range|selection|value  (see below)
//   qa image info|contrast|color|diff|crop …
//
// An application is named with --bundle <id>, --name <process>, --pid <n>.
// An element is chosen with --role, --subrole, --title (exact, any of title,
// description, value, identifier, help), --contains, --near <label beside it>.

let arguments = Arguments(Array(CommandLine.arguments.dropFirst()))
guard let command = arguments.positional(0) else { fail("usage: qa <command> … (see the head of main.swift)") }

func describeMatches(_ result: (target: AX.Target, matches: [AXUIElement], visited: Int)) -> [String: Any] {
    ["ok": true, "found": !result.matches.isEmpty, "count": result.matches.count, "application": result.target.name,
     "pid": Int(result.target.pid), "visited": result.visited, "elements": result.matches.map { AX.describe($0) }]
}

switch command {
case "probe":
    let front = NSWorkspace.shared.frontmostApplication
    let session = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
    let display = mainDisplayBounds()
    let cursor = Events.location()
    emit(["ok": true,
          "accessibilityTrusted": AXIsProcessTrusted(),
          "screenCapture": CGPreflightScreenCaptureAccess(),
          "postEvents": CGPreflightPostEventAccess(),
          "listenEvents": CGPreflightListenEventAccess(),
          "secureInput": IsSecureEventInputEnabled(),
          "frontmost": ["name": front?.localizedName ?? "", "bundle": front?.bundleIdentifier ?? "", "pid": Int(front?.processIdentifier ?? 0)],
          "sessionOnConsole": session["kCGSSessionOnConsoleKey"] as? Bool ?? false,
          "sessionLoginDone": session["kCGSessionLoginDoneKey"] as? Bool ?? false,
          // Whose login session this process is in, and whether its screen is locked.
          "sessionUser": session["kCGSSessionUserNameKey"] as? String ?? "",
          "screenLocked": session["CGSSessionScreenIsLocked"] as? Bool ?? false,
          "mainDisplayPoints": [Double(display.width), Double(display.height)],
          "cursor": [Double(cursor.x), Double(cursor.y)],
          "at": isoNow()])

case "session":
    // Whose login session this process is in and what it may do there. Unlike
    // `probe` it asks macOS nothing about screen capture.
    let front = NSWorkspace.shared.frontmostApplication
    let session = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
    emit(["ok": true,
          "accessibilityTrusted": AXIsProcessTrusted(),
          "postEvents": CGPreflightPostEventAccess(),
          "frontmost": ["name": front?.localizedName ?? "", "bundle": front?.bundleIdentifier ?? "", "pid": Int(front?.processIdentifier ?? 0)],
          "sessionOnConsole": session["kCGSSessionOnConsoleKey"] as? Bool ?? false,
          "sessionLoginDone": session["kCGSessionLoginDoneKey"] as? Bool ?? false,
          "sessionUser": session["kCGSSessionUserNameKey"] as? String ?? "",
          "screenLocked": session["CGSSessionScreenIsLocked"] as? Bool ?? false,
          "at": isoNow()])

case "now":
    emit(["ok": true, "utcMs": utcMilliseconds(), "at": isoNow(), "uptime": ProcessInfo.processInfo.systemUptime])

case "screens":
    emit(["ok": true, "screens": NSScreen.screens.map { screen -> [String: Any] in
        ["frame": rectList(screen.frame), "visibleFrame": rectList(screen.visibleFrame), "scale": Double(screen.backingScaleFactor),
         "name": screen.localizedName]
    }, "mainDisplayPoints": rectList(mainDisplayBounds())])

case "apps":
    emit(["ok": true, "applications": NSWorkspace.shared.runningApplications.map { app -> [String: Any] in
        ["name": app.localizedName ?? "", "bundle": app.bundleIdentifier ?? "", "pid": Int(app.processIdentifier),
         "active": app.isActive, "hidden": app.isHidden, "policy": app.activationPolicy.rawValue]
    }])

case "windows":
    // What the window server shows, front to back. Titles need Screen
    // Recording; owners, layers and bounds do not.
    let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    let owner = arguments.string("owner")
    let pid = arguments.string("pid").flatMap(Int.init)
    var rows: [[String: Any]] = []
    for window in list {
        let name = window[kCGWindowOwnerName as String] as? String ?? ""
        let ownerPID = window[kCGWindowOwnerPID as String] as? Int ?? 0
        if let owner, name != owner { continue }
        if let pid, ownerPID != pid { continue }
        let bounds = window[kCGWindowBounds as String] as? [String: Any] ?? [:]
        func number(_ key: String) -> Double { (bounds[key] as? NSNumber)?.doubleValue ?? 0 }
        rows.append(["owner": name, "pid": ownerPID, "id": window[kCGWindowNumber as String] as? Int ?? 0,
                     "layer": window[kCGWindowLayer as String] as? Int ?? 0, "title": window[kCGWindowName as String] as? String ?? "",
                     "alpha": (window[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1,
                     "bounds": [number("X"), number("Y"), number("Width"), number("Height")]])
    }
    emit(["ok": true, "count": rows.count, "windows": rows])

case "key":
    guard let text = arguments.positional(1), let code = UInt16(text) else { fail("usage: qa key <keycode> [--mods …]") }
    emit(Events.chord(CGKeyCode(code), modifiers: arguments.string("mods"), holdMs: arguments.int("hold-ms", 70)))

case "mod":
    guard let direction = arguments.positional(1), ["down", "up"].contains(direction), let name = arguments.positional(2),
          let mod = Events.modifiers(name).first else { fail("usage: qa mod <down|up> <opt|cmd|ctrl|shift> [--held …]") }
    var held = Events.flags(arguments.string("held"))
    if direction == "down" { held.insert(mod.flag) } else { held.remove(mod.flag) }
    Events.modifier(mod.code, down: direction == "down", held: held)
    emit(["ok": true, "modifier": mod.name, "down": direction == "down", "at": isoNow()])

case "release":
    // Whatever happened before: no modifier is left held.
    for mod in Events.modifierKeys { Events.modifier(mod.code, down: false, held: []); milliseconds(15) }
    emit(["ok": true, "released": Events.modifierKeys.map(\.name)])

case "type":
    let text: String
    if arguments.has("stdin") {
        text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8)?.trimmingCharacters(in: .newlines) ?? ""
    } else {
        guard let given = arguments.positional(1) else { fail("usage: qa type <text> | qa type --stdin") }
        text = given
    }
    Events.type(text)
    // The text itself is never echoed: it may be a password.
    emit(["ok": true, "characters": text.count])

case "move":
    let target = CGPoint(x: arguments.number(1), y: arguments.number(2))
    Events.move(to: target, flags: Events.flags(arguments.string("mods")), steps: arguments.int("steps", 12), totalMs: arguments.int("ms", 240))
    emit(["ok": true, "cursor": [Double(target.x), Double(target.y)], "at": isoNow()])

case "click":
    let target = CGPoint(x: arguments.number(1), y: arguments.number(2))
    let flags = Events.flags(arguments.string("mods"))
    Events.move(to: target, flags: flags, steps: arguments.int("steps", 8), totalMs: arguments.int("ms", 160))
    milliseconds(120)
    Events.click(at: target, flags: flags, count: arguments.int("count", 1), right: arguments.string("button") == "right")
    emit(["ok": true, "clicked": [Double(target.x), Double(target.y)], "count": arguments.int("count", 1), "at": isoNow(), "utcMs": utcMilliseconds()])

case "drag":
    let start = CGPoint(x: arguments.number(1), y: arguments.number(2)), end = CGPoint(x: arguments.number(3), y: arguments.number(4))
    let flags = Events.flags(arguments.string("mods"))
    Events.move(to: start, flags: flags, steps: 8, totalMs: 160)
    milliseconds(150)
    Events.drag(from: start, to: end, flags: flags, steps: arguments.int("steps", 24), totalMs: arguments.int("ms", 600), settleMs: arguments.int("settle-ms", 120))
    emit(["ok": true, "from": [Double(start.x), Double(start.y)], "to": [Double(end.x), Double(end.y)], "at": isoNow()])

case "scroll":
    guard let text = arguments.positional(1), let lines = Int32(text) else { fail("usage: qa scroll <lines> [--mods …] [--at x,y]") }
    let flags = Events.flags(arguments.string("mods"))
    if let point = arguments.point("at") { Events.move(to: point, flags: flags, steps: 6, totalMs: 120); milliseconds(120) }
    Events.scroll(lines: lines, flags: flags)
    emit(["ok": true, "lines": Int(lines), "at": isoNow()])

case "ax":
    guard let verb = arguments.positional(1) else { fail("usage: qa ax tree|find|press|action|focused|set-frame|text-range|selection|value") }
    switch verb {
    case "tree":
        let target = AX.target(arguments)
        var budget = arguments.int("max", 2500)
        let root = AX.tree(target.element, depth: 0, maxDepth: arguments.int("depth", 30), budget: &budget, includeValue: !arguments.has("no-value"))
        if arguments.has("text") {
            var lines: [String] = []
            AX.outline(root, into: &lines)
            print("# \(target.name) (pid \(target.pid)), \(lines.count) elements\(budget <= 0 ? ", truncated" : "")")
            print(lines.joined(separator: "\n"))
        } else {
            emit(["ok": true, "application": target.name, "pid": Int(target.pid), "truncated": budget <= 0, "tree": root])
        }

    case "find":
        let result = AX.find(arguments, limit: arguments.has("all") ? 200 : max(1, arguments.int("index", 0) + 1))
        emit(describeMatches(result))
        exit(result.matches.isEmpty ? 1 : 0)

    case "press", "action":
        let index = arguments.int("index", 0)
        let result = AX.find(arguments, limit: index + 1)
        guard result.matches.indices.contains(index) else {
            emit(["ok": true, "found": false, "application": result.target.name, "visited": result.visited])
            exit(1)
        }
        let element = result.matches[index]
        let action = verb == "press" ? kAXPressAction as String : (arguments.positional(2) ?? "")
        guard !action.isEmpty else { fail("usage: qa ax action <AXAction> …") }
        let described = AX.describe(element)
        let status = AXUIElementPerformAction(element, action as CFString)
        emit(["ok": status == .success, "found": true, "action": action, "status": Int(status.rawValue), "element": described, "at": isoNow(), "utcMs": utcMilliseconds()])
        exit(status == .success ? 0 : 2)

    case "focused":
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 2.0)
        guard let element = AX.element(AX.attribute(system, kAXFocusedUIElementAttribute as String)) else {
            emit(["ok": true, "found": false, "secureInput": IsSecureEventInputEnabled()])
            exit(1)
        }
        var pid: pid_t = 0
        AXUIElementGetPid(element, &pid)
        let app = NSRunningApplication(processIdentifier: pid)
        emit(["ok": true, "found": true, "element": AX.describe(element), "secure": AX.isSecure(element), "secureInput": IsSecureEventInputEnabled(),
              "pid": Int(pid), "application": app?.localizedName ?? "", "bundle": app?.bundleIdentifier ?? ""])

    case "set-frame":
        let target = AX.target(arguments)
        guard let rect = arguments.rect("rect") else { fail("usage: qa ax set-frame --bundle <id> --rect x,y,w,h") }
        let windows = AX.elements(target.element, kAXWindowsAttribute as String)
        guard let window = AX.element(AX.attribute(target.element, kAXMainWindowAttribute as String)) ?? windows.first else {
            emit(["ok": true, "found": false, "application": target.name])
            exit(1)
        }
        let done = AX.setFrame(window, rect)
        emit(["ok": done, "found": true, "frame": AX.frame(window).map(rectList) ?? [], "application": target.name])
        exit(done ? 0 : 2)

    case "text-range":
        // Where a known run of text is drawn, in the first text element that holds it.
        guard let needle = arguments.string("needle"), !needle.isEmpty else { fail("usage: qa ax text-range --bundle <id> --needle <text>") }
        let target = AX.target(arguments)
        var selector = AX.Selector(arguments)
        if selector.role == nil { selector.role = kAXTextAreaRole as String }
        for element in AX.search(target.element, selector, limit: 20).matches {
            guard let value = AX.string(element, kAXValueAttribute as String) else { continue }
            let range = (value as NSString).range(of: needle)
            guard range.location != NSNotFound else { continue }
            var result: [String: Any] = ["ok": true, "found": true, "location": range.location, "length": range.length,
                                         "elementFrame": AX.frame(element).map(rectList) ?? [], "valueLength": (value as NSString).length]
            if let whole = AX.bounds(of: range, in: element) { result["bounds"] = rectList(whole) }
            if let first = AX.bounds(of: NSRange(location: range.location, length: 1), in: element) { result["first"] = rectList(first) }
            if let last = AX.bounds(of: NSRange(location: range.location + range.length - 1, length: 1), in: element) { result["last"] = rectList(last) }
            emit(result)
            exit(0)
        }
        emit(["ok": true, "found": false, "application": target.name])
        exit(1)

    case "selection":
        // What the focused element of an application has selected (QA fixtures only).
        let target = AX.target(arguments)
        guard let element = AX.element(AX.attribute(target.element, kAXFocusedUIElementAttribute as String)) else {
            emit(["ok": true, "found": false, "application": target.name])
            exit(1)
        }
        let text = AX.isSecure(element) ? "" : (AX.string(element, kAXSelectedTextAttribute as String) ?? "")
        emit(["ok": true, "found": true, "role": AX.role(element), "length": text.count, "sha256": AX.sha256(text), "text": String(text.prefix(600))])

    case "value":
        let result = AX.find(arguments, limit: 1)
        guard let element = result.matches.first else {
            emit(["ok": true, "found": false, "application": result.target.name])
            exit(1)
        }
        let text = AX.isSecure(element) ? "" : (AX.string(element, kAXValueAttribute as String) ?? "")
        emit(["ok": true, "found": true, "length": text.count, "sha256": AX.sha256(text), "text": String(text.prefix(2000)),
              "endsWithNewline": text.hasSuffix("\n"), "element": AX.describe(element, includeValue: false)])

    default:
        fail("unknown: qa ax \(verb)")
    }

case "image":
    guard let verb = arguments.positional(1), let path = arguments.positional(2) else { fail("usage: qa image info|contrast|color|diff|crop <png> …") }
    switch verb {
    case "info": emit(Images.info(path))
    case "contrast": emit(Images.contrast(path, arguments))
    case "color": emit(Images.color(path, arguments))
    case "diff":
        guard let second = arguments.positional(3) else { fail("usage: qa image diff <a.png> <b.png> [--rect …]") }
        emit(Images.diff(path, second, arguments))
    case "crop":
        guard let output = arguments.positional(3) else { fail("usage: qa image crop <in.png> <out.png> --rect x,y,w,h") }
        emit(Images.crop(path, output, arguments))
    default: fail("unknown: qa image \(verb)")
    }

default:
    fail("unknown command: \(command)")
}
