//! Docs desktop app.
//!
//! Usage: `iridium_docs [--control <port>] [--sample] [files…]`; `--help` prints `USAGE`.
//!
//! `--control <port>` (or `IRIDIUM_DOCS_CONTROL_PORT`) starts a localhost JSON-lines control server:
//! `{"id":1,"key":"…","method":"engine.execute","params":{"command":"text.insert","params":{"text":"Hi"}}}`.
//! Every request needs the key the app writes to `<settings>/control-key.<instance>` (mode 0600,
//! removed on exit). See `docs/control-protocol.md`.
#![cfg_attr(all(target_os = "windows", not(debug_assertions)), windows_subsystem = "windows")]
#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

use iridium_docs_shell::{Launch, Shell};

#[cfg(any(target_os = "windows", target_os = "macos", test))]
mod graphics;
mod logging;

/// The app and, on macOS, how it quits; the shell does the rest (`iridium_docs_shell`). The control
/// key file is the shell's: it removes it in `save_state`.
struct App(Shell);

impl eframe::App for App {
    fn logic(&mut self, ctx: &egui::Context, frame: &mut eframe::Frame) {
        self.0.logic(ctx);
        self.0.show_file_dialogs(frame);
        // The window's close was allowed. On macOS, letting eframe drop the window inside
        // `-[NSApplication run]` aborts in `-[_NSTouchBarFinderObservation invalidate]`; quit the way
        // Command-Q does instead.
        #[cfg(target_os = "macos")]
        if self.0.take_quit() {
            schedule_macos_terminate(&mut self.0);
        }
    }
    fn raw_input_hook(&mut self, ctx: &egui::Context, raw: &mut egui::RawInput) {
        self.0.raw_input_hook(ctx, raw);
    }
    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        self.0.ui(ui);
        self.0.show_file_dialogs(frame);
    }
    fn on_exit(&mut self) {
        self.0.save_state();
    }
}

/// Quit the way Command-Q does, on the next turn of the main queue.
///
/// Called when the window is closing. Doing it on the next turn lets the close
/// button's display cycle finish while the window still exists; `terminate:`
/// then ends the process. State is saved first, as `on_exit` does, because a
/// fallback [`std::process::exit`] skips `on_exit`. A second close while a quit
/// is already scheduled is ignored.
#[cfg(target_os = "macos")]
fn schedule_macos_terminate(shell: &mut Shell) {
    use std::sync::atomic::{AtomicBool, Ordering};
    static QUIT: AtomicBool = AtomicBool::new(false);
    if QUIT.swap(true, Ordering::Relaxed) {
        return;
    }
    log::info!("window close: quitting");
    // This path can bypass on_exit. Join the owned workers before termination and cleanup.
    shell.save_state();
    dispatch2::DispatchQueue::main().exec_async(|| {
        if let Some(mtm) = objc2::MainThreadMarker::new() {
            objc2_app_kit::NSApplication::sharedApplication(mtm).terminate(None);
        }
        // `terminate:` does not return when it succeeds. If it did, leave anyway:
        // staying up after the close was cancelled would trap the user in the window.
        std::process::exit(0);
    });
}

/// Window, Dock and taskbar icon.
fn app_icon() -> Option<egui::IconData> {
    #[cfg(target_os = "macos")]
    let png: &[u8] = include_bytes!("../../../assets/app-icon/iridium-docs-macos-512.png");
    #[cfg(not(target_os = "macos"))]
    let png: &[u8] = include_bytes!("../../../assets/app-icon/hicolor/256x256/apps/ph.docs.png");
    eframe::icon_data::from_png_bytes(png).map_err(|e| log::warn!("app icon: {e}")).ok()
}

const USAGE: &str = "\
iridium_docs — the Docs desktop app

USAGE:
  iridium_docs [--sample] [--control PORT] [FILE…]

OPTIONS:
  --sample            open the sample document
  --control PORT      start the localhost control server on PORT, for agents and scripts
                      (or set IRIDIUM_DOCS_CONTROL_PORT); see docs/control-protocol.md
  --version           print the version
  -h, --help          print this help
";

/// The commit the build came from (short), or `dev`.
fn build_sha() -> &'static str {
    option_env!("IRIDIUM_DOCS_BUILD_SHA").map(|s| s.get(..8).unwrap_or(s)).unwrap_or("dev")
}

/// The arguments as text, and apart the files whose names aren't valid Unicode, such as a Latin-1
/// one (#1440). A `--control` port that isn't is an error.
fn text_args() -> (Vec<String>, Vec<std::path::PathBuf>) {
    let (mut args, mut files) = (Vec::new(), Vec::new());
    for (i, a) in std::env::args_os().skip(1).enumerate() {
        match a.into_string() {
            Ok(a) => args.push(a),
            Err(a) if args.last().is_some_and(|p| p == "--control") => {
                // Unlike `eprintln!`, never panics.
                let (n, lossy) = (i + 1, a.to_string_lossy());
                let _ = std::io::Write::write_fmt(&mut std::io::stderr(), format_args!("iridium_docs: argument {n} is not valid Unicode: {lossy}\n"));
                std::process::exit(2);
            }
            Err(a) => files.push(a.into()),
        }
    }
    (args, files)
}

/// The arguments without the ones macOS adds when it launches an app (#1103): `-psn_0_12345`, and
/// the `-NS…` / `-Apple…` options (`-AppleLanguages (en)`, `-NSDocumentRevisionsDebugMode YES`) with
/// the value after each. They are not files, and opening them as files fails.
fn without_launch_args(args: Vec<String>) -> Vec<String> {
    let mut kept = Vec::with_capacity(args.len());
    let mut args = args.into_iter().peekable();
    while let Some(a) = args.next() {
        if a.starts_with("-psn_") {
            continue;
        }
        if a.starts_with("-NS") || a.starts_with("-Apple") {
            // Its value, unless the next argument is another flag.
            args.next_if(|v| !v.starts_with('-'));
            continue;
        }
        kept.push(a);
    }
    kept
}

/// Parses the command line, installs logging and the panic hook, restores preferences and window
/// geometry, opens requested documents or the Start screen, starts the control server when
/// asked, and runs the eframe event loop.
fn main() -> eframe::Result {
    // Windows: the update helper is a copy of this program started with `--finish-update`.
    #[cfg(windows)]
    if let Some(result) = craft_update::self_update::finish(&iridium_docs_ui_egui::UPDATE_APP, &std::env::args_os().skip(1).collect::<Vec<_>>()) {
        std::process::exit(i32::from(result.is_err()));
    }
    // First, so the panic hook and every start-up warning are recorded (`logging`).
    let logger = logging::install();
    logging::install_panic_hook();
    let mut control_port: Option<u16> = std::env::var("IRIDIUM_DOCS_CONTROL_PORT").ok().and_then(|p| p.parse().ok());
    let mut files = Vec::new();
    let mut sample = false;
    let (args, other_files) = text_args();
    // Only macOS (Finder / LaunchServices) adds these; elsewhere `-NS…` could be a real file name.
    let args = if cfg!(target_os = "macos") { without_launch_args(args) } else { args };
    let mut bad_control: Option<Option<String>> = None;
    let mut args = args.into_iter().peekable();
    while let Some(a) = args.next() {
        match a.as_str() {
            // A flag after `--control` stays a flag; a bad or missing port is an error (#1426).
            "--control" => {
                let port = args.next_if(|p| p.strip_prefix('-').is_none_or(|n| n.starts_with(|c: char| c.is_ascii_digit())));
                match port.as_deref().and_then(|p| p.parse::<std::num::NonZeroU16>().ok()) {
                    Some(p) => control_port = Some(p.get()),
                    None => bad_control = Some(port),
                }
            }
            "--sample" => sample = true,
            "--version" => {
                println!("iridium_docs {} ({})", env!("CARGO_PKG_VERSION"), build_sha());
                return Ok(());
            }
            // Before the window opens (#968). Unlike `print!`, a closed stdout can't panic.
            "--help" | "-h" => {
                let _ = std::io::Write::write_all(&mut std::io::stdout(), USAGE.as_bytes());
                return Ok(());
            }
            _ => files.push(a),
        }
    }
    // After the loop, so `--version` later on the line still wins. Unlike `eprintln!`, never panics.
    if let Some(port) = bad_control {
        let got = port.map(|p| format!(", got {p:?}")).unwrap_or_default();
        let _ = std::io::Write::write_fmt(&mut std::io::stderr(), format_args!("iridium_docs: --control needs a port number from 1 to 65535{got}\n"));
        std::process::exit(2);
    }
    // The log file lives in the settings directory, next to the preferences; opened after the
    // arguments, so `--version` leaves no file behind. Records logged until now are written to it
    // first. Runs without preferences (agents' test runs) log to standard error only, so they
    // don't rotate away the user's own logs.
    if let Some(logger) = logger {
        match iridium_docs_shell::log_dir().filter(|_| iridium_docs_shell::prefs_enabled()) {
            Some(dir) => match logger.attach_dir(&dir) {
                Ok(path) => log::info!("Docs {} ({}), log file {}", env!("CARGO_PKG_VERSION"), build_sha(), path.display()),
                // Standard error only by now (`attach_dir` gave up on the file); unlike `eprintln!`, never panics.
                Err(e) => log::warn!("no log file: {e}"),
            },
            None => logger.no_file(),
        }
    }
    let mut options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Docs")
            .with_app_id("ph.docs")
            .with_inner_size([1440.0, 920.0])
            .with_min_inner_size([760.0, 480.0])
            .with_drag_and_drop(true)
            .with_fullsize_content_view(true)
            .with_titlebar_shown(false)
            .with_title_shown(false),
        ..Default::default()
    };
    if let Some(icon) = app_icon() {
        options.viewport = options.viewport.with_icon(icon);
    }
    // Before eframe creates the wgpu instance: default Windows to DirectX 12 only, or OpenGL when
    // DirectX 12 has no GPU driver or this is a 32-bit build, and compile DirectX 12 shaders with
    // FXC, which needs no DLL of ours (#603; see graphics.rs).
    #[cfg(target_os = "windows")]
    graphics::configure(&mut options, eframe::wgpu::Backends::from_env());
    // Intel Macs: Metal's compiler aborts on wgpu's indirect-validation shaders (#2652).
    #[cfg(target_os = "macos")]
    graphics::configure_indirect_validation(&mut options, graphics::skips_indirect_validation(true, cfg!(target_arch = "x86_64")));
    iridium_docs_shell::load_user_fonts();
    // Windows opened for further documents start like the first one, before its saved place.
    let window_builder = options.viewport.clone();
    let restored = iridium_docs_shell::saved_window();
    if let Some(window) = restored {
        options.viewport = window.apply(options.viewport);
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    // winit has no file drag-and-drop on Wayland (only on X11), so dropping files from the file
    // manager showed a "no" cursor. Run through XWayland when it's there; IRIDIUM_DOCS_WAYLAND=1
    // keeps the native Wayland backend.
    if std::env::var_os("DISPLAY").is_some() && std::env::var_os("IRIDIUM_DOCS_WAYLAND").is_none() {
        options.event_loop_builder = Some(Box::new(|b| {
            use winit::platform::x11::EventLoopBuilderExtX11;
            b.with_x11();
        }));
    }
    // Registered before the event loop starts, so it catches the Finder event that launched us as
    // well as later ones. Lives until the event loop returns; the app creator only borrows it.
    #[cfg(target_os = "macos")]
    let apple_events = iridium_docs_shell::apple_events::AppleEvents::install();
    #[cfg(target_os = "macos")]
    let apple_events = &apple_events;
    eframe::run_native(
        "Docs",
        options,
        Box::new(move |cc| {
            let launch = Launch {
                files,
                other_files,
                sample,
                control_port,
                window: restored,
                window_builder,
                #[cfg(target_os = "macos")]
                apple_events: apple_events.connect(&cc.egui_ctx),
            };
            Ok(Box::new(App(Shell::new(cc, launch))))
        }),
    )
}

#[cfg(test)]
mod launch_arg_tests {
    use super::without_launch_args;

    fn strip(args: &[&str]) -> Vec<String> {
        without_launch_args(args.iter().map(|a| a.to_string()).collect())
    }

    #[test]
    fn macos_launch_arguments_are_not_files() {
        assert_eq!(strip(&["-psn_0_12345", "a.docx"]), ["a.docx"]);
        assert_eq!(strip(&["-AppleLanguages", "(en)", "a.docx"]), ["a.docx"]);
        assert_eq!(strip(&["a.docx", "-NSDocumentRevisionsDebugMode", "YES", "b.docx"]), ["a.docx", "b.docx"]);
        // A flag with no value after it, or followed by another flag, takes nothing with it.
        assert_eq!(strip(&["a.docx", "-AppleLocale"]), ["a.docx"]);
        assert_eq!(strip(&["-NSFoo", "--sample", "a.docx"]), ["--sample", "a.docx"]);
    }

    #[test]
    fn real_arguments_are_kept() {
        assert_eq!(strip(&["--control", "7981", "--sample", "-h"]), ["--control", "7981", "--sample", "-h"]);
        // Files whose names merely start like a launch argument keep their place when they are paths.
        assert_eq!(strip(&["./-psn_x.docx", "Apple.docx", "-", "-nsfoo"]), ["./-psn_x.docx", "Apple.docx", "-", "-nsfoo"]);
        assert!(strip(&[]).is_empty());
    }
}
