// Mac Game Porter — GUI for porter.sh (install a Windows game / FreeArc repack as a Mac app).
import AppKit
import SwiftUI
import UniformTypeIdentifiers

let home = FileManager.default.homeDirectoryForCurrentUser
let porterHome = home.appendingPathComponent("Library/Application Support/MacGamePorter")
let gamesDir = home.appendingPathComponent("Games")

func slug(_ name: String) -> String {
    let s = String(name.map { $0.isLetter || $0.isNumber ? $0 : "-" }).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    return s.isEmpty ? "game" : s.lowercased()
}

/// Resources bundled into the .app by gui/build.sh; falls back to the repo when run from source.
func resource(_ path: String) -> URL {
    if let r = Bundle.main.resourceURL?.appendingPathComponent(path), FileManager.default.fileExists(atPath: r.path) {
        return r
    }
    return URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(path)
}

enum SourceKind { case repack(Int), game, unknown }

func inspect(_ url: URL) -> SourceKind {
    let files = (try? FileManager.default.contentsOfDirectory(atPath: url.path)) ?? []
    let archives = files.filter { ["bin", "arc"].contains(($0 as NSString).pathExtension.lowercased()) }
    if files.contains(where: { $0.lowercased() == "setup.exe" }) && !archives.isEmpty { return .repack(archives.count) }
    let e = FileManager.default.enumerator(at: url, includingPropertiesForKeys: nil)
    while let f = e?.nextObject() as? URL { if f.pathExtension.lowercased() == "exe" { return .game } }
    return .unknown
}

func suggestedName(_ url: URL) -> String {
    var n = url.lastPathComponent
    for pattern in [#"\[[^\]]*\]"#, #"\([^)]*\)"#, #"(?i)\b(fitgirl|dodi|elamigos|repack|goty|v\d[\w.]*)\b"#] {
        n = n.replacingOccurrences(of: pattern, with: "", options: .regularExpression)
    }
    return n.replacingOccurrences(of: "_", with: " ").trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: "-")))
}

struct InstalledGame: Identifiable {
    let url: URL
    var id: String { url.path }
    var name: String { url.deletingPathExtension().lastPathComponent }
}

func installedGames() -> [InstalledGame] {
    let apps = (try? FileManager.default.contentsOfDirectory(at: gamesDir, includingPropertiesForKeys: nil)) ?? []
    return apps.filter { FileManager.default.fileExists(atPath: $0.appendingPathComponent("Contents/Resources/porter.conf").path) }
        .sorted { $0.lastPathComponent < $1.lastPathComponent }.map(InstalledGame.init)
}

@MainActor
final class PortJob: ObservableObject {
    @Published var source: URL?
    @Published var kind: SourceKind = .unknown
    @Published var name = ""
    @Published var makeDMG = false
    @Published var running = false
    @Published var finished = false
    @Published var failed = false
    @Published var phase = "Choose a repack or game folder to begin."
    @Published var progress: Double? = nil
    @Published var detail = ""
    @Published var log: [String] = []
    @Published var games = installedGames()
    private var process: Process?
    private var timer: Timer?

    var innoextractMissing: Bool {
        if case .repack = kind {
            return !["/opt/homebrew/bin/innoextract", "/usr/local/bin/innoextract"].contains { FileManager.default.fileExists(atPath: $0) }
        }
        return false
    }

    func choose(_ url: URL) {
        source = url
        kind = inspect(url)
        name = suggestedName(url)
        finished = false; failed = false; progress = nil; detail = ""
        switch kind {
        case .repack(let n): phase = "Repack with \(n) archive\(n == 1 ? "" : "s"): extracted natively, no Windows installer needed."
        case .game: phase = "Installed Windows game folder."
        case .unknown: phase = "No setup.exe/archives or .exe found in this folder."
        }
    }

    func start() {
        guard let source else { return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        var args = [resource("porter-src/porter.sh").path, "install", source.path, "--name", name]
        if makeDMG { args.append("--dmg") }
        p.arguments = args
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["PORTER_TOOLS"] = resource("tools").path
        env["PYTHONUNBUFFERED"] = "1"
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor in self?.append(text) }
        }
        p.terminationHandler = { [weak self] proc in
            Task { @MainActor in self?.ended(proc.terminationStatus) }
        }
        log = []; running = true; finished = false; failed = false; progress = nil
        phase = "Starting…"
        do { try p.run() } catch { append("could not start porter: \(error)\n"); ended(1); return }
        process = p
        let status = porterHome.appendingPathComponent("work/\(slug(name))/status.json")
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.poll(status) }
        }
    }

    func cancel() {
        process?.terminate()        // porter forwards SIGTERM to every decoder in its process group
        phase = "Cancelling…"
    }

    private func append(_ text: String) {
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            log.append(String(line))
            if line.hasPrefix("[porter] ") { phase = String(line.dropFirst(9)) }
        }
        if log.count > 2000 { log.removeFirst(log.count - 2000) }
    }

    private func poll(_ url: URL) {
        guard let data = try? Data(contentsOf: url),
              let s = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let updated = s["updated"] as? Double, Date().timeIntervalSince1970 - updated < 30 else { return }
        let gb = { (k: String) in ((s[k] as? Double) ?? 0) / 1e9 }
        let written = gb("written"), total = gb("total"), read = gb("read"), comp = gb("compsize")
        let archive = (s["archive_index"] as? Int).map { "Archive \($0) of \(s["archive_count"] as? Int ?? $0) · " } ?? ""
        if written > 0, total > 0 {
            progress = written / total
            detail = archive + String(format: "writing %.1f of %.1f GB", written, total)
        } else if comp > 0 {
            progress = read / comp
            detail = archive + String(format: "unpacking %.1f of %.1f GB", read, comp)
        }
        if let ph = s["phase"] as? String { phase = ph }
    }

    private func ended(_ code: Int32) {
        timer?.invalidate(); timer = nil
        pipe_cleanup()
        running = false
        process = nil
        games = installedGames()
        if code == 0 {
            finished = true; progress = 1; phase = "Done — \(name) is ready to play."; detail = ""
        } else {
            failed = true; phase = "Stopped (exit \(code)). See the log for details."
        }
    }

    private func pipe_cleanup() {
        (process?.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler = nil
    }

    var appURL: URL { gamesDir.appendingPathComponent("\(name).app") }
}

struct ContentView: View {
    @StateObject private var job = PortJob()
    @State private var showLog = false
    @State private var dropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: "gamecontroller.fill").font(.system(size: 30)).foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Mac Game Porter").font(.title2.bold())
                    Text("Turn a Windows game or repack into a Mac app (Game Porting Toolkit · D3DMetal)")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }

            dropZone

            if job.source != nil {
                Form {
                    TextField("Game name", text: $job.name)
                    Toggle("Also create a self-contained DMG (for another Mac)", isOn: $job.makeDMG)
                }
                .disabled(job.running)
            }

            if job.innoextractMissing {
                Label("Repacks need innoextract. Install it with: brew install innoextract", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
            }

            statusArea

            HStack {
                if job.running {
                    Button("Cancel", role: .cancel) { job.cancel() }
                } else {
                    Button("Port Game") { job.start() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(job.source == nil || job.name.trimmingCharacters(in: .whitespaces).isEmpty || job.innoextractMissing)
                }
                if job.finished {
                    Button("Play") { NSWorkspace.shared.open(job.appURL) }
                    Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([job.appURL]) }
                }
                Spacer()
                Button(showLog ? "Hide Log" : "Show Log") { showLog.toggle() }
            }

            if showLog { logView }

            Divider()
            gamesList
        }
        .padding(20)
        .frame(minWidth: 620, minHeight: 520, maxHeight: .infinity, alignment: .top)
    }

    private var dropZone: some View {
        RoundedRectangle(cornerRadius: 12)
            .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6]))
            .foregroundStyle(dropTargeted ? Color.accentColor : .secondary.opacity(0.5))
            .background(RoundedRectangle(cornerRadius: 12).fill(dropTargeted ? Color.accentColor.opacity(0.08) : .clear))
            .frame(height: 88)
            .overlay {
                VStack(spacing: 6) {
                    if let src = job.source {
                        Text(src.lastPathComponent).font(.headline).lineLimit(1).truncationMode(.middle)
                        Text(src.deletingLastPathComponent().path).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                    } else {
                        Text("Drop a repack or game folder here").font(.headline)
                    }
                    Button(job.source == nil ? "Choose Folder…" : "Change…") { pickFolder() }.disabled(job.running)
                }
                .padding(.horizontal)
            }
            .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
                guard !job.running, let item = providers.first else { return false }
                _ = item.loadObject(ofClass: URL.self) { url, _ in
                    if let url, url.hasDirectoryPath { Task { @MainActor in job.choose(url) } }
                }
                return true
            }
    }

    private var statusArea: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(job.phase).font(.callout).foregroundStyle(job.failed ? .red : .primary).lineLimit(2)
            if job.running || job.finished {
                if let p = job.progress { ProgressView(value: p) } else { ProgressView().progressViewStyle(.linear) }
            }
            if !job.detail.isEmpty { Text(job.detail).font(.caption).foregroundStyle(.secondary) }
        }
    }

    private var logView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 1) {
                    ForEach(Array(job.log.enumerated()), id: \.offset) { i, line in
                        Text(line).font(.system(.caption, design: .monospaced)).textSelection(.enabled).id(i)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(8)
            }
            .frame(minHeight: 140, maxHeight: 220)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .textBackgroundColor)))
            .onChange(of: job.log.count) { _, n in proxy.scrollTo(n - 1, anchor: .bottom) }
        }
    }

    private var gamesList: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Your games").font(.headline)
            if job.games.isEmpty {
                Text("Ported games appear here (they live in ~/Games).").font(.callout).foregroundStyle(.secondary)
            }
            ForEach(job.games) { g in
                HStack {
                    Image(nsImage: NSWorkspace.shared.icon(forFile: g.url.path)).resizable().frame(width: 28, height: 28)
                    Text(g.name)
                    Spacer()
                    Button("Show") { NSWorkspace.shared.activateFileViewerSelecting([g.url]) }
                    Button("Play") { NSWorkspace.shared.open(g.url) }
                }
            }
        }
    }

    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.prompt = "Choose"
        panel.message = "Choose a FitGirl-style repack folder (setup.exe + .bin files) or an installed Windows game folder"
        if panel.runModal() == .OK, let url = panel.url { job.choose(url) }
    }
}

@main
struct MacGamePorterApp: App {
    var body: some Scene {
        WindowGroup("Mac Game Porter") { ContentView() }
            .windowResizability(.contentMinSize)
    }
}
