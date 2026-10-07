import AppKit
import CoreGraphics
import Foundation

/// Keyboard and pointer events posted at the HID level: they travel through
/// the window server like a device's, so system hot keys, event taps and the
/// frontmost application all see them. Nothing here talks to the app under
/// test directly.
enum Events {
    static let source = CGEventSource(stateID: .hidSystemState)
    static let modifierKeys: [(name: String, code: CGKeyCode, flag: CGEventFlags)] = [
        ("ctrl", 59, .maskControl), ("opt", 58, .maskAlternate), ("shift", 56, .maskShift), ("cmd", 55, .maskCommand)
    ]

    static func modifiers(_ text: String?) -> [(name: String, code: CGKeyCode, flag: CGEventFlags)] {
        guard let text, !text.isEmpty else { return [] }
        let wanted = Set(text.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() })
        let known = Set(modifierKeys.map(\.name))
        if let unknown = wanted.subtracting(known).first { fail("unknown modifier: \(unknown) (use opt, cmd, ctrl, shift)") }
        return modifierKeys.filter { wanted.contains($0.name) }
    }
    static func flags(_ text: String?) -> CGEventFlags {
        modifiers(text).reduce(CGEventFlags()) { $0.union($1.flag) }
    }

    /// A modifier going down or up is a flags-changed event carrying every
    /// modifier that is held afterwards.
    static func modifier(_ code: CGKeyCode, down: Bool, held: CGEventFlags) {
        guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down) else { fail("could not create a modifier event") }
        event.type = .flagsChanged
        event.flags = held
        event.post(tap: .cghidEventTap)
    }
    static func key(_ code: CGKeyCode, down: Bool, flags: CGEventFlags) {
        guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down) else { fail("could not create a key event") }
        event.flags = flags
        event.post(tap: .cghidEventTap)
    }
    /// Modifiers down one by one, the key down and up, modifiers up: what a
    /// hand does.
    static func chord(_ code: CGKeyCode, modifiers text: String?, holdMs: Int) -> [String: Any] {
        let mods = modifiers(text)
        var held = CGEventFlags()
        for mod in mods {
            held.insert(mod.flag)
            modifier(mod.code, down: true, held: held)
            milliseconds(35)
        }
        let pressed = utcMilliseconds()
        key(code, down: true, flags: held)
        milliseconds(holdMs)
        key(code, down: false, flags: held)
        milliseconds(35)
        for mod in mods.reversed() {
            held.remove(mod.flag)
            modifier(mod.code, down: false, held: held)
            milliseconds(25)
        }
        return ["ok": true, "keyCode": Int(code), "modifiers": mods.map(\.name), "pressedAtUtcMs": pressed, "pressedAt": isoNow()]
    }

    static func location() -> CGPoint { CGEvent(source: nil)?.location ?? .zero }

    static func mouse(_ type: CGEventType, at point: CGPoint, button: CGMouseButton = .left, flags: CGEventFlags, clicks: Int64 = 1) {
        guard let event = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: point, mouseButton: button) else {
            fail("could not create a pointer event")
        }
        event.flags = flags
        event.setIntegerValueField(.mouseEventClickState, value: clicks)
        event.post(tap: .cghidEventTap)
    }
    /// Moves in small steps, as a hand does: an app that follows the pointer
    /// sees it arrive, not teleport.
    static func move(to target: CGPoint, from start: CGPoint? = nil, flags: CGEventFlags, steps: Int, totalMs: Int, type: CGEventType = .mouseMoved) {
        let origin = start ?? location()
        let count = max(1, steps)
        for step in 1...count {
            let t = Double(step) / Double(count)
            let point = CGPoint(x: origin.x + (target.x - origin.x) * t, y: origin.y + (target.y - origin.y) * t)
            mouse(type, at: point, flags: flags)
            milliseconds(max(1, totalMs / count))
        }
    }
    static func click(at point: CGPoint, flags: CGEventFlags, count: Int, right: Bool) {
        let down: CGEventType = right ? .rightMouseDown : .leftMouseDown
        let up: CGEventType = right ? .rightMouseUp : .leftMouseUp
        let button: CGMouseButton = right ? .right : .left
        for index in 1...max(1, count) {
            mouse(down, at: point, button: button, flags: flags, clicks: Int64(index))
            milliseconds(45)
            mouse(up, at: point, button: button, flags: flags, clicks: Int64(index))
            if index < count { milliseconds(90) }
        }
    }
    static func drag(from start: CGPoint, to end: CGPoint, flags: CGEventFlags, steps: Int, totalMs: Int) {
        mouse(.leftMouseDown, at: start, flags: flags)
        milliseconds(120)
        move(to: end, from: start, flags: flags, steps: steps, totalMs: totalMs, type: .leftMouseDragged)
        milliseconds(120)
        mouse(.leftMouseUp, at: end, flags: flags)
    }
    /// One wheel notch per event (line units, no phases): a mouse wheel.
    static func scroll(lines: Int32, flags: CGEventFlags) {
        guard let event = CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 1, wheel1: lines, wheel2: 0, wheel3: 0) else {
            fail("could not create a scroll event")
        }
        event.flags = flags
        event.post(tap: .cghidEventTap)
    }
    /// Types text as characters, whatever the keyboard layout.
    static func type(_ text: String) {
        for character in text {
            let units = Array(String(character).utf16)
            for down in [true, false] {
                guard let event = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down) else { fail("could not create a key event") }
                event.flags = []
                units.withUnsafeBufferPointer { event.keyboardSetUnicodeString(stringLength: units.count, unicodeString: $0.baseAddress) }
                event.post(tap: .cghidEventTap)
                milliseconds(12)
            }
        }
    }
}
