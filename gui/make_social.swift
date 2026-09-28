// Render the 1280x640 social preview card (docs/og.png) used by GitHub, the website and link previews.
//   swift gui/make_social.swift docs/og.png
import AppKit

let out = CommandLine.arguments[1]
let w = 1280, h = 640
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let bounds = NSRect(x: 0, y: 0, width: w, height: h)
NSGradient(colors: [NSColor(calibratedRed: 0.07, green: 0.06, blue: 0.16, alpha: 1),
                    NSColor(calibratedRed: 0.13, green: 0.10, blue: 0.34, alpha: 1)])!.draw(in: bounds, angle: -30)

// Icon tile
let tile = NSRect(x: 96, y: 200, width: 240, height: 240)
NSGradient(colors: [NSColor(calibratedRed: 0.36, green: 0.22, blue: 0.95, alpha: 1),
                    NSColor(calibratedRed: 0.10, green: 0.55, blue: 0.98, alpha: 1)])!
    .draw(in: NSBezierPath(roundedRect: tile, xRadius: 54, yRadius: 54), angle: -60)
if let sym = NSImage(systemSymbolName: "gamecontroller.fill", accessibilityDescription: nil)?
    .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 118, weight: .semibold).applying(.init(paletteColors: [.white]))) {
    sym.draw(in: NSRect(x: tile.midX - sym.size.width / 2, y: tile.midY - sym.size.height / 2, width: sym.size.width, height: sym.size.height))
}

func draw(_ s: String, _ font: NSFont, _ color: NSColor, _ y: CGFloat) {
    NSAttributedString(string: s, attributes: [.font: font, .foregroundColor: color]).draw(at: NSPoint(x: 400, y: y))
}
draw("Mac Game Porter", .systemFont(ofSize: 76, weight: .bold), .white, 372)
draw("Play Windows games on your Mac", .systemFont(ofSize: 40, weight: .semibold),
     NSColor(calibratedRed: 0.72, green: 0.78, blue: 1, alpha: 1), 310)
draw("Apple Silicon · Game Porting Toolkit · D3DMetal · DirectX 12 → Metal", .systemFont(ofSize: 26, weight: .regular),
     NSColor(white: 1, alpha: 0.7), 248)
draw("Free & open source · github.com/KarmSakha/mac-game-porter", .systemFont(ofSize: 24, weight: .medium),
     NSColor(white: 1, alpha: 0.55), 200)
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
