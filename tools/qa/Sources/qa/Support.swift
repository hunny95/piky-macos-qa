import AppKit
import Foundation

/// One JSON object per invocation, on standard output.
func emit(_ object: [String: Any]) {
    let safe = JSONSerialization.isValidJSONObject(object) ? object : ["error": "unserializable result"]
    if let data = try? JSONSerialization.data(withJSONObject: safe, options: [.sortedKeys, .withoutEscapingSlashes]),
       let text = String(data: data, encoding: .utf8) {
        print(text)
    }
}

func fail(_ message: String, code: Int32 = 2) -> Never {
    emit(["ok": false, "error": message])
    exit(code)
}

/// `--name value` options, bare `--flag`s and positionals.
struct Arguments {
    private(set) var positionals: [String] = []
    private var options: [String: String] = [:]
    private var flags: Set<String> = []
    static let flagNames: Set<String> = ["all", "text", "points", "enabled", "stdin", "system", "no-value", "onscreen"]

    init(_ raw: [String]) {
        var index = 0
        while index < raw.count {
            let item = raw[index]
            if item.hasPrefix("--"), item.count > 2 {
                let name = String(item.dropFirst(2))
                if Arguments.flagNames.contains(name) {
                    flags.insert(name)
                } else if index + 1 < raw.count {
                    options[name] = raw[index + 1]
                    index += 1
                } else {
                    fail("option --\(name) needs a value")
                }
            } else {
                positionals.append(item)
            }
            index += 1
        }
    }
    func string(_ name: String) -> String? { options[name] }
    func int(_ name: String, _ fallback: Int) -> Int { options[name].flatMap(Int.init) ?? fallback }
    func double(_ name: String, _ fallback: Double) -> Double { options[name].flatMap(Double.init) ?? fallback }
    func has(_ name: String) -> Bool { flags.contains(name) }
    func positional(_ index: Int) -> String? { positionals.indices.contains(index) ? positionals[index] : nil }
    func number(_ index: Int) -> Double {
        guard let text = positional(index), let value = Double(text) else { fail("expected a number at position \(index + 1)") }
        return value
    }
    /// "x,y,w,h"
    func rect(_ name: String) -> CGRect? {
        guard let parts = options[name]?.split(separator: ",").map({ Double($0.trimmingCharacters(in: .whitespaces)) }),
              parts.count == 4, let x = parts[0], let y = parts[1], let w = parts[2], let h = parts[3] else { return nil }
        return CGRect(x: x, y: y, width: w, height: h)
    }
    /// "x,y"
    func point(_ name: String) -> CGPoint? {
        guard let parts = options[name]?.split(separator: ",").map({ Double($0.trimmingCharacters(in: .whitespaces)) }),
              parts.count == 2, let x = parts[0], let y = parts[1] else { return nil }
        return CGPoint(x: x, y: y)
    }
}

func rectList(_ rect: CGRect) -> [Double] {
    [Double(rect.minX), Double(rect.minY), Double(rect.width), Double(rect.height)].map { ($0 * 10).rounded() / 10 }
}

func milliseconds(_ value: Int) {
    if value > 0 { usleep(useconds_t(value) * 1000) }
}

func utcMilliseconds() -> Int { Int((Date().timeIntervalSince1970 * 1000).rounded()) }

func isoNow() -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.string(from: Date())
}

func mainDisplayBounds() -> CGRect { CGDisplayBounds(CGMainDisplayID()) }
