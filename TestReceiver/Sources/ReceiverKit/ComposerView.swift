import AppKit

/// The box people type in. ⌘V is recorded instead of being typed out as file
/// locations: files become attachments, text is inserted as text.
public final class ReceiverTextView: NSTextView {
    weak var composer: ComposerView?
    public override func paste(_ sender: Any?) { composer?.accept(.general, via: "paste") }
    public override func pasteAsPlainText(_ sender: Any?) { composer?.accept(.general, via: "paste") }
    /// Drops belong to the composer around this box (its attachment area).
    public override var acceptableDragTypes: [NSPasteboard.PasteboardType] { [] }
}

/// A message composer shaped like the ones PIKY delivers into: a text area
/// macOS Accessibility describes, and beside it, in the same group, a button
/// named "Attach files". That button is what tells PIKY this box can take
/// files (it then drops them here); without it PIKY pastes the text and says
/// which files still need adding.
@MainActor public final class ComposerView: NSView {
    public let textView = ReceiverTextView(frame: NSRect(x: 0, y: 0, width: 400, height: 110))
    public let scrollView = NSScrollView()
    public let attachButton = NSButton(title: "Attach files", target: nil, action: nil)
    public let attachmentsLabel = NSTextField(labelWithString: "")
    public let log: ReceiptLog
    public var onReceipt: ((Receipt) -> Void)?
    public var onProblem: ((String) -> Void)?
    public private(set) var attached: [String] = []
    /// Off: a plain text box with no way to attach (no button, no drops).
    public var offersAttachments = true {
        didSet {
            attachButton.isHidden = !offersAttachments
            if offersAttachments { registerForDraggedTypes([.fileURL]) } else { unregisterDraggedTypes() }
        }
    }

    public init(log: ReceiptLog) {
        self.log = log
        super.init(frame: NSRect(x: 0, y: 0, width: 640, height: 170))
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        setAccessibilityLabel("Message composer")

        textView.composer = self
        textView.isRichText = false
        textView.allowsUndo = true
        textView.font = .systemFont(ofSize: 14)
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        textView.isAutomaticSpellingCorrectionEnabled = false
        textView.minSize = .zero
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.textContainerInset = NSSize(width: 6, height: 8)
        textView.setAccessibilityLabel("Message")
        textView.updateDragTypeRegistration()

        scrollView.documentView = textView
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        attachButton.bezelStyle = .rounded
        attachButton.target = self
        attachButton.action = #selector(pickFiles)
        attachButton.translatesAutoresizingMaskIntoConstraints = false
        attachButton.setContentHuggingPriority(.required, for: .horizontal)

        attachmentsLabel.textColor = .secondaryLabelColor
        attachmentsLabel.lineBreakMode = .byTruncatingMiddle
        attachmentsLabel.translatesAutoresizingMaskIntoConstraints = false
        attachmentsLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        addSubview(scrollView); addSubview(attachButton); addSubview(attachmentsLabel)
        NSLayoutConstraint.activate([
            scrollView.topAnchor.constraint(equalTo: topAnchor),
            scrollView.leadingAnchor.constraint(equalTo: leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: attachButton.topAnchor, constant: -8),
            attachButton.leadingAnchor.constraint(equalTo: leadingAnchor),
            attachButton.bottomAnchor.constraint(equalTo: bottomAnchor),
            attachmentsLabel.leadingAnchor.constraint(equalTo: attachButton.trailingAnchor, constant: 10),
            attachmentsLabel.trailingAnchor.constraint(equalTo: trailingAnchor),
            attachmentsLabel.centerYAnchor.constraint(equalTo: attachButton.centerYAnchor)
        ])
        registerForDraggedTypes([.fileURL])
        refreshAttachments()
    }
    @available(*, unavailable) required init?(coder: NSCoder) { fatalError("ComposerView is built in code") }

    /// Takes whatever the pasteboard hands over, records it, and shows it the
    /// way a chat box would: text typed in, files listed as attachments.
    @discardableResult public func accept(_ board: NSPasteboard, via: String) -> Receipt? {
        let contents = PasteboardReader.read(board)
        do {
            guard let receipt = try log.record(text: contents.text, files: contents.files, via: via) else { return nil }
            if contents.files.isEmpty, let text = contents.text {
                textView.insertText(text, replacementRange: textView.selectedRange())
            } else {
                attached += receipt.filenames
                refreshAttachments()
            }
            onReceipt?(receipt)
            return receipt
        } catch {
            onProblem?("Could not write the log: \(error.localizedDescription)")
            return nil
        }
    }
    public func clear() {
        attached = []; textView.string = ""; refreshAttachments()
    }
    private func refreshAttachments() {
        attachmentsLabel.stringValue = attached.isEmpty ? "No attachments yet"
            : "\(attached.count) attached: " + attached.enumerated().map { "\($0.offset + 1). \($0.element)" }.joined(separator: "   ")
    }
    /// The button works by itself too: a baseline that does not involve PIKY.
    @objc private func pickFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        do {
            guard let receipt = try log.record(text: nil, files: panel.urls, via: "picker") else { return }
            attached += receipt.filenames; refreshAttachments(); onReceipt?(receipt)
        } catch { onProblem?("Could not write the log: \(error.localizedDescription)") }
    }

    // MARK: Drops
    private func carriesFiles(_ info: NSDraggingInfo) -> Bool {
        info.draggingPasteboard.canReadObject(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true])
    }
    public override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation { offersAttachments && carriesFiles(sender) ? .copy : [] }
    public override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation { offersAttachments && carriesFiles(sender) ? .copy : [] }
    public override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool { offersAttachments }
    public override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard offersAttachments else { return false }
        return accept(sender.draggingPasteboard, via: "drop") != nil
    }
}

/// The whole window's contents: instructions, the composer, a switch for
/// whether it takes attachments, and everything received so far.
@MainActor public final class ReceiverPanel: NSView {
    public let composer: ComposerView
    public let received = NSTextView(frame: NSRect(x: 0, y: 0, width: 400, height: 200))
    public let attachmentsSwitch = NSButton(checkboxWithTitle: "This box takes attachments (shows “Attach files”; PIKY then drops files onto it)", target: nil, action: nil)
    public let status = NSTextField(labelWithString: "")
    private let log: ReceiptLog

    public init(log: ReceiptLog) {
        self.log = log
        composer = ComposerView(log: log)
        super.init(frame: NSRect(x: 0, y: 0, width: 720, height: 640))

        let intro = NSTextField(wrappingLabelWithString:
            "Click in the box below, then press ⌘Return in PIKY. Everything that arrives is listed underneath and written to the log. Use only the QA fixture files and the QA page here.")
        intro.textColor = .secondaryLabelColor

        attachmentsSwitch.state = .on
        attachmentsSwitch.target = self; attachmentsSwitch.action = #selector(toggleAttachments)

        let heading = NSTextField(labelWithString: "Received")
        heading.font = .boldSystemFont(ofSize: 13)
        let clear = NSButton(title: "Clear", target: self, action: #selector(clearAll))
        let reveal = NSButton(title: "Show Log in Finder", target: self, action: #selector(revealLog))
        let copy = NSButton(title: "Copy Log", target: self, action: #selector(copyLog))
        let bar = NSStackView(views: [heading, NSView(), copy, reveal, clear])
        bar.orientation = .horizontal

        received.isEditable = false; received.isSelectable = true; received.isRichText = false
        received.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        received.textContainerInset = NSSize(width: 6, height: 6)
        received.autoresizingMask = [.width]; received.isVerticallyResizable = true
        received.textContainer?.widthTracksTextView = true
        received.setAccessibilityLabel("Received deliveries")
        let scroll = NSScrollView(); scroll.documentView = received; scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder

        status.textColor = .tertiaryLabelColor; status.font = .systemFont(ofSize: 11); status.lineBreakMode = .byTruncatingMiddle
        status.stringValue = "Log: \(log.url.path)"

        let stack = NSStackView(views: [intro, composer, attachmentsSwitch, bar, scroll, status])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 12, right: 16)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        composer.translatesAutoresizingMaskIntoConstraints = false
        scroll.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: topAnchor), stack.bottomAnchor.constraint(equalTo: bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: leadingAnchor), stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            composer.heightAnchor.constraint(equalToConstant: 170),
            composer.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32),
            bar.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32),
            intro.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32),
            scroll.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32),
            scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 160),
            status.widthAnchor.constraint(lessThanOrEqualTo: stack.widthAnchor, constant: -32)
        ])
        composer.onReceipt = { [weak self] receipt in self?.show(receipt) }
        composer.onProblem = { [weak self] message in self?.status.stringValue = message }
        for receipt in log.all() { show(receipt) }
    }
    @available(*, unavailable) required init?(coder: NSCoder) { fatalError("ReceiverPanel is built in code") }

    private func show(_ receipt: Receipt) {
        let existing = received.string
        received.string = existing.isEmpty ? receipt.summary : existing + "\n\n" + receipt.summary
        received.scrollToEndOfDocument(nil)
    }
    @objc private func toggleAttachments() { composer.offersAttachments = attachmentsSwitch.state == .on }
    @objc private func clearAll() {
        do { try log.clear(); received.string = ""; composer.clear(); status.stringValue = "Log: \(log.url.path)" }
        catch { status.stringValue = "Could not clear the log: \(error.localizedDescription)" }
    }
    @objc private func revealLog() {
        try? FileManager.default.createDirectory(at: log.url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: log.url.path) { FileManager.default.createFile(atPath: log.url.path, contents: nil) }
        NSWorkspace.shared.activateFileViewerSelecting([log.url])
    }
    @objc private func copyLog() {
        let text = (try? String(contentsOf: log.url, encoding: .utf8)) ?? ""
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
        status.stringValue = "Copied \(log.count) \(log.count == 1 ? "delivery" : "deliveries") as JSON lines."
    }
}
