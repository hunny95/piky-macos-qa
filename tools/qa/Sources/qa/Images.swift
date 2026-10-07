import AppKit
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Measurements of a screenshot: is a colour there, how strong is the
/// contrast in a region, did a region change. Numbers only.
struct Bitmap {
    let width: Int
    let height: Int
    let bytes: [UInt8] // RGBA, row 0 at the top

    init(path: String) {
        guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fail("could not read the image \(path)") }
        self.init(image)
    }
    init(_ image: CGImage) {
        let w = image.width, h = image.height
        var data = [UInt8](repeating: 0, count: w * h * 4)
        let space = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
        data.withUnsafeMutableBytes { buffer in
            guard let context = CGContext(data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                          space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
            context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        }
        width = w
        height = h
        bytes = data
    }
    /// The rectangle in pixels, clipped to the image.
    func clip(_ rect: CGRect?, scale: Double) -> (x0: Int, y0: Int, x1: Int, y1: Int) {
        guard let rect else { return (0, 0, width, height) }
        let x0 = max(0, min(width, Int((Double(rect.minX) * scale).rounded(.down))))
        let y0 = max(0, min(height, Int((Double(rect.minY) * scale).rounded(.down))))
        let x1 = max(x0, min(width, Int((Double(rect.maxX) * scale).rounded(.up))))
        let y1 = max(y0, min(height, Int((Double(rect.maxY) * scale).rounded(.up))))
        return (x0, y0, x1, y1)
    }
    @inline(__always) func pixel(_ x: Int, _ y: Int) -> (r: Int, g: Int, b: Int) {
        let offset = (y * width + x) * 4
        return (Int(bytes[offset]), Int(bytes[offset + 1]), Int(bytes[offset + 2]))
    }
    /// Relative luminance (WCAG) of an sRGB pixel, 0…1.
    static func luminance(_ r: Int, _ g: Int, _ b: Int) -> Double {
        func linear(_ value: Int) -> Double {
            let c = Double(value) / 255
            return c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
    }
    static func ratio(_ a: Double, _ b: Double) -> Double { (max(a, b) + 0.05) / (min(a, b) + 0.05) }
}

enum Images {
    /// The factor from screen points to this image's pixels: given, or worked
    /// out from the main display (a screenshot of it).
    static func scale(_ arguments: Arguments, _ bitmap: Bitmap) -> Double {
        if let text = arguments.string("scale"), let value = Double(text), value > 0 { return value }
        guard arguments.has("points") else { return 1 }
        let display = mainDisplayBounds().width
        return display > 0 ? Double(bitmap.width) / Double(display) : 1
    }

    static func info(_ path: String) -> [String: Any] {
        let bitmap = Bitmap(path: path)
        let display = mainDisplayBounds()
        return ["ok": true, "width": bitmap.width, "height": bitmap.height,
                "mainDisplayPoints": [Double(display.width), Double(display.height)],
                "scaleFromMainDisplay": display.width > 0 ? Double(bitmap.width) / Double(display.width) : 1]
    }

    /// The fill a region mostly has, the tone furthest from it that a real
    /// share of the pixels have, and the WCAG contrast between the two. A
    /// label that cannot be read on its button scores close to 1.
    static func contrast(_ path: String, _ arguments: Arguments) -> [String: Any] {
        let bitmap = Bitmap(path: path)
        let area = bitmap.clip(arguments.rect("rect"), scale: scale(arguments, bitmap))
        var bins = [Int](repeating: 0, count: 64)
        var sums = [Double](repeating: 0, count: 64)
        var colors = [(r: Int, g: Int, b: Int)](repeating: (0, 0, 0), count: 64)
        var total = 0
        for y in area.y0..<area.y1 {
            for x in area.x0..<area.x1 {
                let p = bitmap.pixel(x, y)
                let l = Bitmap.luminance(p.r, p.g, p.b)
                // Bins in perceptual steps (the square root spreads the dark end).
                let bin = min(63, Int(l.squareRoot() * 64))
                bins[bin] += 1; sums[bin] += l
                colors[bin] = (colors[bin].r + p.r, colors[bin].g + p.g, colors[bin].b + p.b)
                total += 1
            }
        }
        guard total > 0 else { return ["ok": false, "error": "empty region"] }
        let fillBin = bins.indices.max { bins[$0] < bins[$1] } ?? 0
        let fill = sums[fillBin] / Double(bins[fillBin])
        // A tone counts when at least 0.4% of the region has it (thin label strokes).
        let floor = max(3, total / 250)
        var best = fill, bestRatio = 1.0, bestBin = fillBin
        for bin in bins.indices where bins[bin] >= floor && bin != fillBin {
            let tone = sums[bin] / Double(bins[bin])
            let ratio = Bitmap.ratio(fill, tone)
            if ratio > bestRatio { bestRatio = ratio; best = tone; bestBin = bin }
        }
        func hex(_ bin: Int) -> String {
            let n = max(1, bins[bin])
            return String(format: "%02X%02X%02X", colors[bin].r / n, colors[bin].g / n, colors[bin].b / n)
        }
        return ["ok": true, "pixels": total, "fillLuminance": (fill * 1000).rounded() / 1000, "fillColor": hex(fillBin),
                "fillShare": (Double(bins[fillBin]) / Double(total) * 1000).rounded() / 1000,
                "markLuminance": (best * 1000).rounded() / 1000, "markColor": hex(bestBin),
                "markShare": (Double(bins[bestBin]) / Double(total) * 1000).rounded() / 1000,
                "contrastRatio": (bestRatio * 100).rounded() / 100,
                "regionPixels": [area.x0, area.y0, area.x1 - area.x0, area.y1 - area.y0]]
    }

    /// How many pixels are within `tolerance` of a colour, and the box around them (in points).
    static func color(_ path: String, _ arguments: Arguments) -> [String: Any] {
        guard let text = arguments.string("rgb"), text.count == 6, let value = Int(text, radix: 16) else { fail("--rgb RRGGBB is needed") }
        let target = (r: (value >> 16) & 255, g: (value >> 8) & 255, b: value & 255)
        let tolerance = arguments.int("tol", 40)
        let bitmap = Bitmap(path: path)
        let factor = scale(arguments, bitmap)
        let area = bitmap.clip(arguments.rect("rect"), scale: factor)
        var count = 0, minX = Int.max, minY = Int.max, maxX = -1, maxY = -1
        for y in area.y0..<area.y1 {
            for x in area.x0..<area.x1 {
                let p = bitmap.pixel(x, y)
                if abs(p.r - target.r) <= tolerance, abs(p.g - target.g) <= tolerance, abs(p.b - target.b) <= tolerance {
                    count += 1
                    minX = min(minX, x); minY = min(minY, y); maxX = max(maxX, x); maxY = max(maxY, y)
                }
            }
        }
        var result: [String: Any] = ["ok": true, "count": count, "pixelsSearched": (area.x1 - area.x0) * (area.y1 - area.y0), "scale": factor]
        if count > 0 {
            result["boxPoints"] = [Double(minX) / factor, Double(minY) / factor, Double(maxX - minX + 1) / factor, Double(maxY - minY + 1) / factor].map { ($0 * 10).rounded() / 10 }
        }
        return result
    }

    /// The share of pixels that differ between two screenshots of the same size.
    static func diff(_ first: String, _ second: String, _ arguments: Arguments) -> [String: Any] {
        let a = Bitmap(path: first), b = Bitmap(path: second)
        guard a.width == b.width, a.height == b.height else { return ["ok": false, "error": "the images differ in size"] }
        let area = a.clip(arguments.rect("rect"), scale: scale(arguments, a))
        let threshold = arguments.int("tol", 24)
        var changed = 0, total = 0
        for y in area.y0..<area.y1 {
            for x in area.x0..<area.x1 {
                let p = a.pixel(x, y), q = b.pixel(x, y)
                if abs(p.r - q.r) + abs(p.g - q.g) + abs(p.b - q.b) > threshold { changed += 1 }
                total += 1
            }
        }
        return ["ok": true, "changed": changed, "pixels": total, "share": total > 0 ? (Double(changed) / Double(total) * 10_000).rounded() / 10_000 : 0]
    }

    static func crop(_ path: String, _ output: String, _ arguments: Arguments) -> [String: Any] {
        guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fail("could not read the image \(path)") }
        let bitmap = Bitmap(image)
        let area = bitmap.clip(arguments.rect("rect"), scale: scale(arguments, bitmap))
        let rect = CGRect(x: area.x0, y: area.y0, width: area.x1 - area.x0, height: area.y1 - area.y0)
        guard rect.width > 0, rect.height > 0, let cropped = image.cropping(to: rect),
              let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: output) as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            return ["ok": false, "error": "nothing to crop"]
        }
        CGImageDestinationAddImage(destination, cropped, nil)
        return ["ok": CGImageDestinationFinalize(destination), "width": Int(rect.width), "height": Int(rect.height)]
    }
}
