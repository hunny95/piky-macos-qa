// swift-tools-version: 5.10
import PackageDescription

// The QA driver: posts real keyboard and pointer events, reads other apps'
// Accessibility trees and measures screenshots. A test tool for disposable
// machines; it contains nothing of the app under test.
let package = Package(
    name: "qa",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "qa", swiftSettings: [.unsafeFlags(["-swift-version", "5"])])
    ]
)
