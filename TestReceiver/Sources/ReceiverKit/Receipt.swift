import AppKit
import CryptoKit
import UniformTypeIdentifiers

/// One file as it arrived. `sha256` is of the bytes read here, so it can be
/// compared with TestFiles/MANIFEST.sha256.
public struct ReceivedFile: Codable, Equatable, Sendable {
    public let name: String
    public let url: String
    /// image, pdf, text, other; or missing when the file could not be read.
    public let kind: String
    public let bytes: Int?
    public let sha256: String?
}

/// One delivery: everything a paste or a drop handed over, in the order it
/// was handed over.
public struct Receipt: Codable, Equatable, Sendable {
    public var sequence: Int
    /// ISO 8601, UTC, with milliseconds.
    public var timestamp: String
    /// paste (⌘V in the box), drop (files dragged onto it), picker (the
    /// Attach button), pasteboard (read headless with --read-pasteboard).
    public var via: String
    public var text: String?
    public var textCharacters: Int
    public var fileURLs: [String]
    public var filenames: [String]
    public var attachmentCount: Int
    public var imageCount: Int
    public var files: [ReceivedFile]

    public init(sequence: Int, date: Date = Date(), via: String, text: String?, files urls: [URL]) {
        let received = urls.map(Receipt.describe)
        self.sequence = sequence
        self.timestamp = Receipt.stamp(date)
        self.via = via
        self.text = text?.isEmpty == true ? nil : text
        self.textCharacters = text?.count ?? 0
        self.fileURLs = urls.map(\.absoluteString)
        self.filenames = urls.map(\.lastPathComponent)
        self.attachmentCount = urls.count
        self.imageCount = received.filter { $0.kind == "image" }.count
        self.files = received
    }
    public var isEmpty: Bool { text == nil && files.isEmpty }

    static func stamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
    /// Reads the whole file, as an app that shows or uploads an attachment does.
    static func describe(_ url: URL) -> ReceivedFile {
        let name = url.lastPathComponent
        guard let data = try? Data(contentsOf: url, options: .mappedIfSafe) else {
            return ReceivedFile(name: name, url: url.absoluteString, kind: "missing", bytes: nil, sha256: nil)
        }
        let type = UTType(filenameExtension: url.pathExtension)
        let kind: String
        if type?.conforms(to: .image) == true { kind = "image" }
        else if type?.conforms(to: .pdf) == true { kind = "pdf" }
        else if type?.conforms(to: .text) == true { kind = "text" }
        else { kind = "other" }
        return ReceivedFile(name: name, url: url.absoluteString, kind: kind, bytes: data.count,
                            sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined())
    }
    /// One line of JSON with stable key order.
    public func line() throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return String(decoding: try encoder.encode(self), as: UTF8.self)
    }
    /// A few lines a person can read in the window.
    public var summary: String {
        var lines = ["#\(sequence)  \(timestamp)  via \(via)"]
        if let text {
            let first = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
            lines.append("   text: \(textCharacters) characters · “\(first.prefix(70))\(first.count > 70 || text.contains("\n") ? "…" : "")”")
        } else { lines.append("   text: none") }
        lines.append("   files: \(attachmentCount) (\(imageCount) \(imageCount == 1 ? "image" : "images"))")
        for (index, file) in files.enumerated() {
            let size = file.bytes.map { "\($0) bytes" } ?? "not readable"
            lines.append("   \(index + 1). \(file.name)  [\(file.kind), \(size)]  \(file.sha256.map { String($0.prefix(12)) + "…" } ?? "")")
        }
        return lines.joined(separator: "\n")
    }
}

/// What a pasteboard holds, the way any receiving app reads it: the string,
/// and file URLs item by item so their order is the sender's order.
public enum PasteboardReader {
    public static func read(_ board: NSPasteboard) -> (text: String?, files: [URL]) {
        var files: [URL] = []
        for item in board.pasteboardItems ?? [] {
            guard let raw = item.string(forType: .fileURL), let url = URL(string: raw), url.isFileURL else { continue }
            files.append(url.standardizedFileURL)
        }
        if files.isEmpty, let urls = board.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] {
            files = urls.map(\.standardizedFileURL)
        }
        return (board.string(forType: .string), files)
    }
}

/// The receiver's record: one JSON object per line, appended, never rewritten.
public final class ReceiptLog {
    public let url: URL
    public private(set) var count: Int
    public init(url: URL) {
        self.url = url
        let existing = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        count = existing.split(separator: "\n", omittingEmptySubsequences: true).count
    }
    public static var defaultURL: URL {
        FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs/PIKY QA TestReceiver/received.jsonl")
    }
    /// Records what a pasteboard handed over. Nothing is recorded for an empty one.
    @discardableResult public func record(from board: NSPasteboard, via: String, date: Date = Date()) throws -> Receipt? {
        let contents = PasteboardReader.read(board)
        return try record(text: contents.text, files: contents.files, via: via, date: date)
    }
    @discardableResult public func record(text: String?, files: [URL], via: String, date: Date = Date()) throws -> Receipt? {
        let receipt = Receipt(sequence: count + 1, date: date, via: via, text: text, files: files)
        guard !receipt.isEmpty else { return nil }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let bytes = Data((try receipt.line() + "\n").utf8)
        if let handle = try? FileHandle(forWritingTo: url) {
            defer { try? handle.close() }
            _ = try handle.seekToEnd(); try handle.write(contentsOf: bytes)
        } else { try bytes.write(to: url, options: .atomic) }
        count += 1
        return receipt
    }
    public func all() -> [Receipt] {
        let text = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        return text.split(separator: "\n", omittingEmptySubsequences: true).compactMap { try? JSONDecoder().decode(Receipt.self, from: Data($0.utf8)) }
    }
    public func clear() throws {
        if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
        count = 0
    }
}
