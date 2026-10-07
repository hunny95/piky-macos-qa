// swift-tools-version: 5.10
import PackageDescription

// A QA tool: a message box that records exactly what was pasted or dropped
// into it. The app under test never links it.
let package = Package(
    name: "TestReceiver",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "ReceiverKit"),
        .executableTarget(name: "TestReceiver", dependencies: ["ReceiverKit"])
    ]
)
