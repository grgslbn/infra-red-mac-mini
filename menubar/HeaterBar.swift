// HeaterBar: native menu-bar panel for the office heater.
// Thin UI over the `heater` CLI: all automation logic stays in Python.
// Left-click: open panel. Right-click: toggle power.
import AppKit
import SwiftUI

// MARK: - Data from `heater panel`

struct Flex: Decodable, CustomStringConvertible {
    let description: String
    init(from d: Decoder) throws {
        let c = try d.singleValueContainer()
        if let s = try? c.decode(String.self) { description = s }
        else if let i = try? c.decode(Int.self) { description = String(i) }
        else if let x = try? c.decode(Double.self) { description = String(x) }
        else if let b = try? c.decode(Bool.self) { description = b ? "on" : "off" }
        else { description = "" }
    }
}

struct Preset: Decodable, Hashable { let label: String; let temp: Double }

struct Panel: Decodable {
    var ok: Bool
    var error: String?
    var power: Bool?
    var target: Double?
    var current: Double?
    var mode: String?
    var timer: Flex?
    var manual_off: Bool
    var auto_off_reason: String?
    var presets: [Preset]
    var timer_choices: [Double]
    var has_timer: Bool
    var modes: [String]
    var min_temp: Double
    var max_temp: Double
    var wake_action: String
    var safety_timer_hours: Double
    var idle_off_minutes: Double
}

func deg(_ v: Double?) -> String {
    guard let v else { return "–" }
    return v == v.rounded() ? "\(Int(v))°" : String(format: "%.1f°", v)
}

// MARK: - Model

@MainActor
final class Model: ObservableObject {
    @Published var panel: Panel?
    @Published var busy = false
    @Published var actionError: String?
    @Published var pendingTarget: Double?
    var onChange: (() -> Void)?
    private var debounce: DispatchWorkItem?

    let heaterPath: String = {
        if let p = UserDefaults.standard.string(forKey: "heaterPath"),
           FileManager.default.isExecutableFile(atPath: p) { return p }
        for p in ["/opt/homebrew/bin/heater", "/usr/local/bin/heater"]
        where FileManager.default.isExecutableFile(atPath: p) { return p }
        return "/opt/homebrew/bin/heater"
    }()

    var target: Double? { pendingTarget ?? panel?.target }

    nonisolated static func exec(_ path: String, _ args: [String]) -> (Int32, String, String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        let out = Pipe(), err = Pipe()
        p.standardOutput = out; p.standardError = err
        do { try p.run() } catch { return (127, "", "Can't run \(path). Run install.sh.") }
        let o = out.fileHandleForReading.readDataToEndOfFile()
        let e = err.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return (p.terminationStatus, String(decoding: o, as: UTF8.self), String(decoding: e, as: UTF8.self))
    }

    private func background(_ args: [String], then: @escaping @MainActor (Int32, String, String) -> Void) {
        let path = heaterPath
        DispatchQueue.global(qos: .userInitiated).async {
            let r = Model.exec(path, args)
            Task { @MainActor in then(r.0, r.1, r.2) }
        }
    }

    func refresh() {
        background(["panel"]) { code, out, err in
            if let data = out.data(using: .utf8), let p = try? JSONDecoder().decode(Panel.self, from: data) {
                self.panel = p
                if self.debounce == nil { self.pendingTarget = nil }
            } else {
                self.panel = nil
                self.actionError = err.isEmpty ? "No answer from the heater command." : err.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            self.onChange?()
        }
    }

    func act(_ args: [String]) {
        busy = true; actionError = nil
        background(args) { code, _, err in
            self.busy = false
            if code != 0 {
                self.actionError = err.replacingOccurrences(of: "heater: ", with: "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
            }
            self.refresh()
        }
    }

    func setPower(_ on: Bool) {
        panel?.power = on          // optimistic
        onChange?()
        act([on ? "on" : "off"])
    }

    func togglePower() { setPower(!(panel?.power ?? false)) }

    func nudge(_ delta: Double) {
        guard let p = panel, let t = target else { return }
        setTarget(min(p.max_temp, max(p.min_temp, t + delta)))
    }

    func setTarget(_ t: Double, turnOn: Bool = false) {
        pendingTarget = t
        onChange?()
        debounce?.cancel()
        let item = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                guard let self else { return }
                self.debounce = nil
                let s = t == t.rounded() ? String(Int(t)) : String(t)
                self.act(turnOn && self.panel?.power != true ? ["on", s] : ["set", s])
            }
        }
        debounce = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: item)
    }
}

// MARK: - Views

struct Chip: View {
    let title: String
    let selected: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.system(size: 12))
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 7)
                    .fill(selected ? Color.orange.opacity(0.18) : Color.clear))
                .overlay(RoundedRectangle(cornerRadius: 7)
                    .stroke(selected ? Color.orange.opacity(0.6) : Color.secondary.opacity(0.35), lineWidth: 0.5))
                .foregroundStyle(selected ? Color.orange : Color.secondary)
                .contentShape(Rectangle())
        }.buttonStyle(.plain)
    }
}

struct Row: View {
    let icon: String, label: String, value: String
    var good = true
    var body: some View {
        HStack {
            Image(systemName: icon).frame(width: 16)
            Text(label)
            Spacer()
            Text(value).foregroundStyle(good ? Color.green : Color.secondary)
        }.font(.system(size: 12)).foregroundStyle(.secondary)
    }
}

struct PanelView: View {
    @ObservedObject var m: Model

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if let p = m.panel, p.ok { controls(p) } else { offline }
            if let e = m.actionError, !e.isEmpty {
                Text(e).font(.system(size: 11)).foregroundStyle(.red).padding(.top, 8)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Divider().padding(.vertical, 10)
            footer
        }
        .padding(16)
        .frame(width: 300)
    }

    var header: some View {
        HStack(spacing: 8) {
            Image(systemName: m.panel?.power == true ? "flame.fill" : "flame")
                .font(.system(size: 18))
                .foregroundStyle(m.panel?.power == true ? Color.orange : Color.secondary)
            Text("Office heater").font(.system(size: 14, weight: .semibold))
            Spacer()
            if m.busy { ProgressView().controlSize(.small) }
            Toggle("", isOn: Binding(get: { m.panel?.power ?? false }, set: { m.setPower($0) }))
                .toggleStyle(.switch).tint(.orange).labelsHidden()
                .disabled(m.panel?.ok != true)
        }
    }

    @ViewBuilder func controls(_ p: Panel) -> some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 0) {
                Text("Room").font(.system(size: 11)).foregroundStyle(.secondary)
                Text(deg(p.current)).font(.system(size: 32, weight: .medium)).monospacedDigit()
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text("Target").font(.system(size: 11)).foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    roundButton("minus") { m.nudge(-1) }
                    Text(deg(m.target)).font(.system(size: 22, weight: .medium)).monospacedDigit()
                        .frame(minWidth: 44)
                    roundButton("plus") { m.nudge(+1) }
                }
            }
        }.padding(.top, 14)

        if p.manual_off && p.power != true {
            Text("You switched it off today, so it won't start on its own.")
                .font(.system(size: 11)).foregroundStyle(.secondary).padding(.top, 8)
        }

        HStack(spacing: 6) {
            ForEach(p.presets, id: \.self) { pr in
                Chip(title: "\(pr.label) \(deg(pr.temp))", selected: m.target == pr.temp && p.power == true) {
                    m.setTarget(pr.temp, turnOn: true)
                }
            }
        }.padding(.top, 12)

        if !p.modes.isEmpty {
            label("Mode")
            HStack(spacing: 6) {
                ForEach(p.modes, id: \.self) { md in
                    Chip(title: md.capitalized, selected: p.mode == md) { m.act(["mode", md]) }
                }
            }
        }

        if p.has_timer {
            label("Auto-off timer")
            HStack(spacing: 6) {
                ForEach(p.timer_choices, id: \.self) { h in
                    Chip(title: "\(Int(h))h", selected: false) { m.act(["timer", String(h)]) }
                }
                Chip(title: "Off", selected: false) { m.act(["timer", "0"]) }
                Spacer()
                if let t = p.timer?.description, !t.isEmpty, t != "0", t != "cancel" {
                    Text(t).font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }

        Divider().padding(.vertical, 10)
        VStack(spacing: 7) {
            Row(icon: "moon", label: "Off when Mac sleeps", value: "on")
            Row(icon: "sun.max", label: "Back on when you return",
                value: ["restore": "on", "always_on": "always"][p.wake_action] ?? "off",
                good: p.wake_action != "never")
            Row(icon: "checkmark.shield", label: "Safety cut-off",
                value: p.has_timer && p.safety_timer_hours > 0 ? "\(Int(p.safety_timer_hours))h rolling" : "not set up",
                good: p.has_timer && p.safety_timer_hours > 0)
            Row(icon: "hourglass", label: "Off when you're away",
                value: p.idle_off_minutes > 0 ? "after \(Int(p.idle_off_minutes)) min" : "off",
                good: p.idle_off_minutes > 0)
        }
    }

    var offline: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(m.panel == nil ? "Loading…" : "Can't reach the heater")
                .font(.system(size: 14, weight: .medium)).padding(.top, 14)
            if let e = m.panel?.error {
                Text(e).font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text("Check the wall switch on the panel and the 2.4 GHz Wi-Fi.")
                .font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }

    var footer: some View {
        HStack {
            Text(statusLine).font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
            Button { m.refresh() } label: { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.borderless).help("Refresh")
            Menu {
                Button("Open config") { open(path: configPath) }
                Button("Open log") { NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory() + "/Library/Logs/heater.log")) }
                Divider()
                Button("Quit HeaterBar") { NSApp.terminate(nil) }
            } label: { Image(systemName: "ellipsis.circle") }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
        }
    }

    var configPath: String {
        // heater -> <project>/bin/heater; config sits in <project>
        let real = (try? FileManager.default.destinationOfSymbolicLink(atPath: m.heaterPath)) ?? m.heaterPath
        return URL(fileURLWithPath: real).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("config.toml").path
    }

    func open(path: String) { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }

    var statusLine: String {
        guard let p = m.panel, p.ok else { return "Offline" }
        if p.power == true {
            if let c = p.current, let t = p.target, c < t { return "Heating · \(deg(t - c)) to go" }
            return "Holding \(deg(p.target))"
        }
        switch p.auto_off_reason {
        case "sleep": return "Off · Mac was asleep"
        case "display_sleep": return "Off · display was asleep"
        case "idle": return "Off · you were away"
        case "hours": return "Off · outside working hours"
        default: return p.manual_off ? "Off · switched off by you" : "Off"
        }
    }

    func label(_ s: String) -> some View {
        Text(s).font(.system(size: 11)).foregroundStyle(.secondary).padding(.top, 14).padding(.bottom, 6)
    }

    func roundButton(_ icon: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon).font(.system(size: 12, weight: .semibold))
                .frame(width: 28, height: 28)
                .background(Circle().stroke(Color.secondary.opacity(0.4), lineWidth: 0.5))
                .contentShape(Circle())
        }.buttonStyle(.plain)
    }
}

// MARK: - Status item

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = Model()
    var item: NSStatusItem!
    let popover = NSPopover()
    var timer: Timer?

    func applicationDidFinishLaunching(_ n: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let b = item.button {
            b.target = self
            b.action = #selector(clicked)
            b.sendAction(on: [.leftMouseUp, .rightMouseUp])
            b.imagePosition = .imageLeading
        }
        let host = NSHostingController(rootView: PanelView(m: model))
        host.sizingOptions = .preferredContentSize
        popover.contentViewController = host
        popover.behavior = .transient
        model.onChange = { [weak self] in self?.render() }
        render()
        model.refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.model.refresh() }
        }
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 8) { Task { @MainActor in self?.model.refresh() } }
        }
    }

    func render() {
        guard let b = item.button else { return }
        let p = model.panel
        let on = p?.ok == true && p?.power == true
        let name = on ? "flame.fill" : (p?.ok == false ? "exclamationmark.triangle" : "flame")
        var img = NSImage(systemSymbolName: name, accessibilityDescription: "Heater")
        if on, let i = img {
            img = i.withSymbolConfiguration(.init(paletteColors: [.systemOrange]))
            img?.isTemplate = false
        } else {
            img?.isTemplate = true
        }
        b.image = img
        var title = ""
        if let p, p.ok {
            title = on ? " \(deg(p.current)) → \(deg(model.target))" : " \(deg(p.current))"
        }
        b.attributedTitle = NSAttributedString(string: title, attributes: [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .regular)])
        b.toolTip = p?.ok == false ? (p?.error ?? "Heater unreachable") : "Office heater · right-click to switch on/off"
    }

    @objc func clicked() {
        if NSApp.currentEvent?.type == .rightMouseUp {
            if model.panel?.ok == true { model.togglePower() } else { model.refresh() }
            return
        }
        if popover.isShown {
            popover.performClose(nil)
        } else if let b = item.button {
            model.refresh()
            popover.show(relativeTo: b.bounds, of: b, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}

@main
enum Main {
    static func main() {
        MainActor.assumeIsolated {
            // Debug: `HeaterBar --snapshot out.png` renders the panel to an image and exits.
            let args = CommandLine.arguments
            if let i = args.firstIndex(of: "--snapshot"), i + 1 < args.count {
                let m = Model()
                let r = Model.exec(m.heaterPath, ["panel"])
                m.panel = try? JSONDecoder().decode(Panel.self, from: Data(r.1.utf8))
                let renderer = ImageRenderer(content: PanelView(m: m).background(Color(nsColor: .windowBackgroundColor)))
                renderer.scale = 2
                if let cg = renderer.cgImage,
                   let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: args[i + 1]))
                }
                return
            }
            let app = NSApplication.shared
            let d = AppDelegate()
            app.delegate = d
            app.setActivationPolicy(.accessory)
            withExtendedLifetime(d) { app.run() }
        }
    }
}
