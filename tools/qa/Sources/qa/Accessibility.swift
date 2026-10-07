import AppKit
import ApplicationServices
import CryptoKit
import Foundation

/// Reads what macOS Accessibility says about another application's windows:
/// the same description VoiceOver gets. Read-only except for `press`,
/// `action` and `setFrame`, which do what a person's click or drag would.
enum AX {
    static let textAttributes = [kAXTitleAttribute as String, kAXDescriptionAttribute as String, kAXValueAttribute as String,
                                 kAXIdentifierAttribute as String, kAXHelpAttribute as String, "AXFilename", "AXLabel"]

    static func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
    }
    static func string(_ element: AXUIElement, _ name: String) -> String? {
        guard let value = attribute(element, name) else { return nil }
        if let text = value as? String { return text }
        if let text = value as? NSAttributedString { return text.string }
        if let url = value as? URL { return url.absoluteString }
        if let number = value as? NSNumber { return number.stringValue }
        return nil
    }
    static func bool(_ element: AXUIElement, _ name: String) -> Bool? {
        (attribute(element, name) as? NSNumber)?.boolValue
    }
    static func element(_ value: CFTypeRef?) -> AXUIElement? {
        guard let value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }
    static func elements(_ element: AXUIElement, _ name: String) -> [AXUIElement] {
        guard let value = attribute(element, name), let list = value as? [AXUIElement] else { return [] }
        return list
    }
    static func frame(_ element: AXUIElement) -> CGRect? {
        guard let position = attribute(element, kAXPositionAttribute as String), let size = attribute(element, kAXSizeAttribute as String),
              CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID() else { return nil }
        var point = CGPoint.zero, extent = CGSize.zero
        guard AXValueGetValue(position as! AXValue, .cgPoint, &point), AXValueGetValue(size as! AXValue, .cgSize, &extent) else { return nil }
        return CGRect(origin: point, size: extent)
    }
    static func actions(_ element: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(element, &names) == .success, let list = names as? [String] else { return [] }
        return list
    }
    static func role(_ element: AXUIElement) -> String { string(element, kAXRoleAttribute as String) ?? "" }
    static func subrole(_ element: AXUIElement) -> String { string(element, kAXSubroleAttribute as String) ?? "" }
    static func isSecure(_ element: AXUIElement) -> Bool { subrole(element) == "AXSecureTextField" }

    /// Everything a reader needs to recognise an element. The contents of a
    /// password field are never read.
    static func describe(_ element: AXUIElement, includeValue: Bool = true) -> [String: Any] {
        var result: [String: Any] = ["role": role(element)]
        let sub = subrole(element)
        if !sub.isEmpty { result["subrole"] = sub }
        for (key, name) in [("title", kAXTitleAttribute as String), ("description", kAXDescriptionAttribute as String),
                            ("identifier", kAXIdentifierAttribute as String), ("help", kAXHelpAttribute as String)] {
            if let text = string(element, name), !text.isEmpty { result[key] = String(text.prefix(400)) }
        }
        if includeValue, sub != "AXSecureTextField", let text = string(element, kAXValueAttribute as String), !text.isEmpty {
            result["value"] = String(text.prefix(400))
            if text.count > 400 { result["valueLength"] = text.count }
        }
        if let rect = frame(element) { result["frame"] = rectList(rect) }
        if let enabled = bool(element, kAXEnabledAttribute as String) { result["enabled"] = enabled }
        if bool(element, kAXFocusedAttribute as String) == true { result["focused"] = true }
        if bool(element, kAXSelectedAttribute as String) == true { result["selected"] = true }
        let names = actions(element)
        if !names.isEmpty { result["actions"] = names }
        return result
    }

    /// Windows, the menu bar and the status items: an application's children
    /// leave out the last one.
    static func children(_ element: AXUIElement, root: Bool) -> [AXUIElement] {
        var list = elements(element, kAXChildrenAttribute as String)
        guard root else { return list }
        for extra in elements(element, kAXWindowsAttribute as String) where !list.contains(where: { CFEqual($0, extra) }) { list.append(extra) }
        if let extras = AX.element(attribute(element, "AXExtrasMenuBar")), !list.contains(where: { CFEqual($0, extras) }) { list.append(extras) }
        return list
    }

    struct Target {
        let pid: pid_t
        let element: AXUIElement
        let name: String
    }
    static func target(_ arguments: Arguments) -> Target {
        if arguments.has("system") {
            return Target(pid: 0, element: AXUIElementCreateSystemWide(), name: "system")
        }
        var pid: pid_t?
        var name = ""
        if let text = arguments.string("pid"), let value = Int32(text) {
            pid = value
            name = NSRunningApplication(processIdentifier: value)?.localizedName ?? "pid \(value)"
        } else if let bundle = arguments.string("bundle") {
            let app = NSRunningApplication.runningApplications(withBundleIdentifier: bundle).first
            pid = app?.processIdentifier
            name = app?.localizedName ?? bundle
        } else if let wanted = arguments.string("name") {
            if let app = NSWorkspace.shared.runningApplications.first(where: { $0.localizedName == wanted || $0.executableURL?.lastPathComponent == wanted }) {
                pid = app.processIdentifier
            } else {
                // A background agent without an application record.
                let process = Process(), pipe = Pipe()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
                process.arguments = ["-x", wanted]
                process.standardOutput = pipe
                process.standardError = FileHandle.nullDevice
                try? process.run()
                process.waitUntilExit()
                let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                pid = output.split(separator: "\n").first.flatMap { Int32($0) }
            }
            name = wanted
        } else {
            fail("name the application: --bundle, --name, --pid or --system")
        }
        guard let pid else {
            emit(["ok": false, "found": false, "error": "not running", "application": name])
            exit(1)
        }
        let element = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(element, 2.0)
        // One question first: an application that does not answer would
        // otherwise cost this timeout for every attribute asked of it.
        var answer: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &answer)
        if status != .success {
            emit(["ok": false, "found": false, "error": "no Accessibility answer (status \(status.rawValue))", "application": name, "pid": Int(pid)])
            exit(1)
        }
        return Target(pid: pid, element: element, name: name)
    }

    struct Selector {
        var role: String?
        var subrole: String?
        var text: String?
        var contains: String?
        var near: String?
        var enabledOnly = false
        var onscreenOnly = false
        init(_ arguments: Arguments) {
            role = arguments.string("role")
            subrole = arguments.string("subrole")
            text = arguments.string("title")
            contains = arguments.string("contains")
            near = arguments.string("near")
            enabledOnly = arguments.has("enabled")
            onscreenOnly = arguments.has("onscreen")
        }
        var isEmpty: Bool { role == nil && subrole == nil && text == nil && contains == nil && near == nil }
        func texts(_ element: AXUIElement) -> [String] {
            guard !AX.isSecure(element) else { return [] }
            return AX.textAttributes.compactMap { AX.string(element, $0) }.filter { !$0.isEmpty }
        }
        func matches(_ element: AXUIElement) -> Bool {
            if let role, AX.role(element) != role { return false }
            if let subrole, AX.subrole(element) != subrole { return false }
            if text != nil || contains != nil {
                let found = texts(element)
                // Swift compares strings by canonical equivalence, so a file
                // name stored decomposed equals the same name composed.
                if let text, !found.contains(where: { $0 == text }) { return false }
                if let contains, !found.contains(where: { $0.localizedCaseInsensitiveContains(contains) }) { return false }
            }
            if enabledOnly, AX.bool(element, kAXEnabledAttribute as String) == false { return false }
            if onscreenOnly {
                guard let rect = AX.frame(element), rect.width > 0, rect.height > 0 else { return false }
            }
            if let near, !AX.hasNeighbour(element, text: near) { return false }
            return true
        }
    }
    /// Is some element carrying `text` in the same row or group as this one?
    /// (A switch has no name of its own; the label beside it has.)
    static func hasNeighbour(_ element: AXUIElement, text: String) -> Bool {
        var current = element
        for _ in 0..<4 {
            guard let parent = AX.element(attribute(current, kAXParentAttribute as String)) else { return false }
            var queue: [(AXUIElement, Int)] = [(parent, 0)]
            var seen = 0
            while !queue.isEmpty, seen < 120 {
                let (node, depth) = queue.removeFirst()
                seen += 1
                if !isSecure(node), textAttributes.contains(where: { string(node, $0) == text }) { return true }
                if depth < 4 { queue.append(contentsOf: children(node, root: false).prefix(40).map { ($0, depth + 1) }) }
            }
            current = parent
        }
        return false
    }

    /// Breadth first, bounded: the first match is the outermost one.
    static func search(_ root: AXUIElement, _ selector: Selector, limit: Int, maxNodes: Int = 12_000, maxDepth: Int = 60) -> (matches: [AXUIElement], visited: Int) {
        var matches: [AXUIElement] = []
        var queue: [(AXUIElement, Int)] = [(root, 0)]
        var index = 0
        while index < queue.count, index < maxNodes {
            let (node, depth) = queue[index]
            index += 1
            if depth > 0, selector.matches(node) {
                matches.append(node)
                if matches.count >= limit { break }
            }
            if depth < maxDepth { queue.append(contentsOf: children(node, root: depth == 0).map { ($0, depth + 1) }) }
        }
        return (matches, index)
    }
    static func find(_ arguments: Arguments, limit: Int) -> (target: Target, matches: [AXUIElement], visited: Int) {
        let target = target(arguments)
        let selector = Selector(arguments)
        if selector.isEmpty { fail("give at least one of --role, --subrole, --title, --contains, --near") }
        let deadline = Date().addingTimeInterval(arguments.double("timeout", 0))
        while true {
            let result = search(target.element, selector, limit: limit)
            if !result.matches.isEmpty || Date() >= deadline { return (target, result.matches, result.visited) }
            usleep(300_000)
        }
    }

    static func tree(_ element: AXUIElement, depth: Int, maxDepth: Int, budget: inout Int, includeValue: Bool) -> [String: Any] {
        var node = describe(element, includeValue: includeValue)
        budget -= 1
        guard depth < maxDepth, budget > 0 else { return node }
        var kids: [[String: Any]] = []
        for child in children(element, root: depth == 0) {
            guard budget > 0 else { node["truncated"] = true; break }
            kids.append(tree(child, depth: depth + 1, maxDepth: maxDepth, budget: &budget, includeValue: includeValue))
        }
        if !kids.isEmpty { node["children"] = kids }
        return node
    }
    /// An indented outline, one element per line: easier to read in a log than JSON.
    static func outline(_ node: [String: Any], indent: Int = 0, into lines: inout [String]) {
        var parts = [node["role"] as? String ?? "?"]
        if let sub = node["subrole"] as? String { parts.append("(\(sub))") }
        for key in ["title", "description", "value", "identifier", "help"] {
            if let text = node[key] as? String { parts.append("\(key)=\(String(reflecting: String(text.prefix(160))))") }
        }
        if let rect = node["frame"] as? [Double] { parts.append("frame=\(rect.map { String(Int($0)) }.joined(separator: ","))") }
        if node["enabled"] as? Bool == false { parts.append("disabled") }
        if node["focused"] as? Bool == true { parts.append("FOCUSED") }
        if node["selected"] as? Bool == true { parts.append("SELECTED") }
        if let actions = node["actions"] as? [String], !actions.isEmpty { parts.append("actions=\(actions.joined(separator: "|"))") }
        if node["truncated"] as? Bool == true { parts.append("…") }
        lines.append(String(repeating: "  ", count: indent) + parts.joined(separator: " "))
        for child in node["children"] as? [[String: Any]] ?? [] { outline(child, indent: indent + 1, into: &lines) }
    }

    static func sha256(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func setFrame(_ window: AXUIElement, _ rect: CGRect) -> Bool {
        var origin = rect.origin, size = rect.size
        guard let position = AXValueCreate(.cgPoint, &origin), let extent = AXValueCreate(.cgSize, &size) else { return false }
        let moved = AXUIElementSetAttributeValue(window, kAXPositionAttribute as CFString, position) == .success
        let sized = AXUIElementSetAttributeValue(window, kAXSizeAttribute as CFString, extent) == .success
        // Position again: a window that had to shrink first may now fit.
        _ = AXUIElementSetAttributeValue(window, kAXPositionAttribute as CFString, position)
        return moved && sized
    }

    /// Where on screen a run of characters is drawn in a text element.
    static func bounds(of range: NSRange, in element: AXUIElement) -> CGRect? {
        var cfRange = CFRange(location: range.location, length: range.length)
        guard let parameter = AXValueCreate(.cfRange, &cfRange) else { return nil }
        var value: CFTypeRef?
        guard AXUIElementCopyParameterizedAttributeValue(element, kAXBoundsForRangeParameterizedAttribute as CFString, parameter, &value) == .success,
              let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        var rect = CGRect.zero
        guard AXValueGetValue(value as! AXValue, .cgRect, &rect) else { return nil }
        return rect
    }
}
