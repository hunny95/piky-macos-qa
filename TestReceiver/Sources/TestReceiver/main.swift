import AppKit
import ReceiverKit

// PIKY TestReceiver: a receiving app whose contents can be read back.
//
//   TestReceiver [--log <file>]                         the window
//   TestReceiver --read-pasteboard <name> [--log <file>]  no window: print what that pasteboard holds, as one JSON line
//   TestReceiver --version

let arguments = Array(CommandLine.arguments.dropFirst())
func value(after flag: String) -> String? {
    guard let index = arguments.firstIndex(of: flag), arguments.indices.contains(index + 1) else { return nil }
    return arguments[index + 1]
}
let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development"

if arguments.contains("--version") { print("PIKY TestReceiver \(version)"); exit(0) }
if arguments.contains("--help") || arguments.contains("-h") {
    print("""
    PIKY TestReceiver \(version)
      TestReceiver [--log <file>]
      TestReceiver --read-pasteboard <name> [--log <file>]
    Default log: \(ReceiptLog.defaultURL.path)
    """)
    exit(0)
}
if let name = value(after: "--read-pasteboard") {
    // Headless: what any app would read from that pasteboard, and nothing else.
    let board = NSPasteboard(name: NSPasteboard.Name(name))
    let contents = PasteboardReader.read(board)
    var receipt = Receipt(sequence: 1, via: "pasteboard", text: contents.text, files: contents.files)
    do {
        if let path = value(after: "--log"), let logged = try ReceiptLog(url: URL(fileURLWithPath: path)).record(text: contents.text, files: contents.files, via: "pasteboard") {
            receipt = logged
        }
        print(try receipt.line())
    } catch {
        FileHandle.standardError.write(Data("TestReceiver: \(error.localizedDescription)\n".utf8)); exit(2)
    }
    exit(receipt.isEmpty ? 3 : 0)
}

@MainActor final class ReceiverApp: NSObject, NSApplicationDelegate {
    let log: ReceiptLog
    var window: NSWindow?
    init(log: ReceiptLog) { self.log = log }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        let panel = ReceiverPanel(log: log)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 640),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "PIKY TestReceiver"
        window.contentView = panel
        window.contentMinSize = NSSize(width: 560, height: 520)
        window.center()
        window.isReleasedWhenClosed = false
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(panel.composer.textView)
        self.window = window
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    /// ⌘V reaches a text view through the Edit menu's key equivalent.
    private func installMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(), appMenu = NSMenu(title: "TestReceiver")
        appMenu.addItem(NSMenuItem(title: "Quit TestReceiver", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        appItem.submenu = appMenu; main.addItem(appItem)
        let editItem = NSMenuItem(), edit = NSMenu(title: "Edit")
        for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(NSMenuItem(title: title, action: Selector(selector), keyEquivalent: key))
        }
        editItem.submenu = edit; main.addItem(editItem)
        NSApp.mainMenu = main
    }
}

// Top-level code runs on the main thread.
MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = ReceiverApp(log: ReceiptLog(url: value(after: "--log").map { URL(fileURLWithPath: $0) } ?? ReceiptLog.defaultURL))
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    withExtendedLifetime(delegate) { app.run() }
}
