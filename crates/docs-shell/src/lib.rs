//! Docs desktop shell: everything the app does per window that isn't process-wide.
//!
//! The `iridium-docs` binary owns the process (logging, GPU backend, updater, macOS quit) and
//! builds a [`Shell`] in eframe's creator; the shell owns the editor, the native services (file
//! dialogs, printing, clipboard, default app, animations), preferences, the control server and
//! the window geometry. A host that embeds Docs calls the same methods from its own eframe app.
#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

mod animations;
#[cfg(target_os = "macos")]
pub mod apple_events;
// Desktop only: no system clipboard, native dialogs, spooler or localhost server in a tab.
#[cfg(not(target_arch = "wasm32"))]
mod clipboard;
// Desktop only: no system clipboard, native dialogs, spooler or localhost server in a tab.
#[cfg(not(target_arch = "wasm32"))]
mod control_server;
#[cfg(not(target_arch = "wasm32"))]
mod default_apps;
// Desktop only: no system clipboard, native dialogs, spooler or localhost server in a tab.
#[cfg(not(target_arch = "wasm32"))]
mod file_dialogs;
// Desktop only: no system clipboard, native dialogs, spooler or localhost server in a tab.
#[cfg(not(target_arch = "wasm32"))]
mod print;
mod region;
#[cfg(target_os = "macos")]
mod traffic_lights;

use iridium_docs_engine::Session;
use iridium_docs_ui_egui::{
    Services, UiState, WordApp,
    window_geometry::{RawWindowState, WindowGeometry, take_rescue},
};

/// What the process was started with, parsed by `main`.
pub struct Launch {
    /// Documents to open, by name.
    pub files: Vec<String>,
    /// Documents whose names aren't valid Unicode (#1440).
    pub other_files: Vec<std::path::PathBuf>,
    /// Open the sample document.
    pub sample: bool,
    /// Start the localhost control server on this port.
    pub control_port: Option<u16>,
    /// The window geometry restored from [`saved_window`], before the window opened.
    pub window: Option<WindowGeometry>,
    /// The viewport new document windows start from, before the saved place applies.
    pub window_builder: egui::ViewportBuilder,
    /// The queue of Finder's open-documents events ([`apple_events::AppleEvents::connect`]).
    #[cfg(target_os = "macos")]
    pub apple_events: fmv_macos_events::Inbox,
}

/// The app, the restored window geometry (or, with none, the default: no position) until the
/// first frame that knows the monitor has checked it, the control server's key file (removed on
/// exit), the file dialogs the app asked for and this frame's raw host window state.
pub struct Shell {
    app: WordApp,
    // The look the app installed at construction (`new_for_host`).
    fonts: egui::FontDefinitions,
    style: egui::Style,
    zoom: f32,
    geometry: Option<WindowGeometry>,
    #[cfg(not(target_arch = "wasm32"))]
    key_file: Option<control_server::KeyFile>,
    #[cfg(not(target_arch = "wasm32"))]
    dialogs: file_dialogs::Launcher,
    // The host's answer for this frame. `InputState` still describes the last painted frame on
    // a hidden logic tick.
    window: RawWindowState,
    #[cfg(target_os = "macos")]
    apple_events: fmv_macos_events::Inbox,
    #[cfg(target_os = "macos")]
    quit_pending: bool,
}

impl Shell {
    /// Build the shell: a blank (or sample) document, the saved preferences, recovery, the
    /// control server, then the documents named at launch, or the Start screen.
    pub fn new(cc: &eframe::CreationContext<'_>, launch: Launch) -> Self {
        // Docs has no platform extra that needs the real window: all of it goes through `ctx`.
        Self::new_for_host(&cc.egui_ctx, cc.storage, launch)
    }

    /// Host-facing constructor: no `CreationContext`, so a host can build this module later.
    /// `storage` is unused (Docs keeps its preferences in its own settings folder).
    pub fn new_for_host(ctx: &egui::Context, _storage: Option<&dyn eframe::Storage>, launch: Launch) -> Self {
        let Launch {
            files,
            other_files,
            sample,
            control_port,
            window,
            window_builder,
            #[cfg(target_os = "macos")]
            apple_events,
        } = launch;
        // The system region picks the new document's paper, the units and the decimal
        // separator (#838).
        let region = region::system();
        let doc = if sample { iridium_docs_engine::sample::sample_document() } else { iridium_docs_engine::blank_document(&region) };
        #[cfg(not(target_arch = "wasm32"))]
        let (file_dialog, dialogs) = file_dialogs::hook(ctx);
        let mut session = Session::new(doc);
        session.system_region = region;
        #[cfg(not(target_arch = "wasm32"))]
        let services = services(file_dialog, ctx);
        #[cfg(target_arch = "wasm32")]
        let services = services(ctx);
        let mut app = WordApp::new(session, services);
        #[cfg(not(target_arch = "wasm32"))]
        app.set_startup_update_check(true);
        load_prefs(&mut app);
        load_user_dictionary(&mut app);
        // Language packs from the suite's font store; an Install click is the person's own.
        #[cfg(not(target_arch = "wasm32"))]
        iridium_docs_engine::packs::use_font_store(true);
        // A region chosen in File › Options replaces the system's for the first blank
        // document too (#838).
        if !sample && app.session.prefs.region.is_some() {
            let doc = app.session.blank_document();
            app.session.set_document(doc);
        }
        app.watch_desktop_theme(ctx);
        #[cfg(not(target_arch = "wasm32"))]
        if prefs_enabled()
            && let Some(dir) = iridium_docs_control_key::settings_dir()
        {
            let ctx = ctx.clone();
            if let Err(e) = app.session.enable_recovery(dir.join("recovery"), std::sync::Arc::new(move || ctx.request_repaint())) {
                log::warn!("local recovery unavailable: {e}");
            }
        }
        app.ui.window = window;
        app.set_window_builder(window_builder);
        app.integrated_titlebar = cfg!(target_os = "macos");
        #[cfg(target_os = "macos")]
        if let Some(bar) = traffic_lights::title_bar() {
            log::info!("title bar: {bar:?}");
            app.mac_titlebar = bar;
        }
        #[cfg(not(target_arch = "wasm32"))]
        let mut key_file = None;
        #[cfg(not(target_arch = "wasm32"))]
        if let Some(port) = control_port
            && let Some((rx, file)) = control_server::start(port, ctx.clone(), iridium_docs_control_key::settings_dir().as_deref())
        {
            app = app.with_control(rx);
            key_file = file;
        }
        // Nothing to open (no files, no sample, no control channel driving the editor): start
        // on File › Home, as Word does (#766), unless the Start screen option is off. Files
        // macOS hands over later open on top of it and close it (`apple_events`).
        if files.is_empty() && other_files.is_empty() && !sample && control_port.is_none() {
            app.start_screen();
        }
        // Install Docs' own look now (it would otherwise wait for the first frame), then capture
        // it. Fonts come from what the app installed: `Context::fonts` panics before egui's first pass.
        let fonts = app.install_look(ctx).unwrap_or_default();
        let mut shell = Self {
            app,
            fonts,
            style: (*ctx.global_style()).clone(),
            zoom: ctx.zoom_factor(),
            // With nothing restored, the window the system placed is checked all the same.
            geometry: Some(window.unwrap_or_default()),
            #[cfg(not(target_arch = "wasm32"))]
            key_file,
            #[cfg(not(target_arch = "wasm32"))]
            dialogs,
            window: RawWindowState::default(),
            #[cfg(target_os = "macos")]
            apple_events,
            #[cfg(target_os = "macos")]
            quit_pending: false,
        };
        for f in files {
            shell.open_path(&f);
        }
        #[cfg(not(target_arch = "wasm32"))]
        for f in other_files {
            open_non_unicode(&mut shell.app, &f);
        }
        shell
    }

    /// The font set the app had installed when construction finished.
    pub fn fonts(&self) -> egui::FontDefinitions {
        self.fonts.clone()
    }

    /// The style the app had installed when construction finished.
    pub fn style(&self) -> egui::Style {
        self.style.clone()
    }

    /// The zoom factor in force when construction finished.
    pub fn zoom(&self) -> f32 {
        self.zoom
    }

    /// macOS: re-install the native menu. Docs builds its menu in the egui ribbon, so there is
    /// nothing to do; present so every module's shell has the same surface.
    pub fn install_native_menu(&self) {}

    /// Advances one frame: polls Finder events on macOS, runs the app, fits or rescues the window
    /// and maximizes it after opening, then gates a close or quit request on unsaved changes and
    /// active printing. Asks the viewport to close (not on macOS, see [`Shell::take_quit`]).
    pub fn logic(&mut self, ctx: &egui::Context) {
        #[cfg(target_os = "macos")]
        apple_events::poll(&self.apple_events, &mut self.app, ctx);
        self.app.logic(ctx);
        let window = self.window;
        // A window that doesn't fit on its screen (the default size on a laptop) shrinks to fit
        // there, so all of the scroll bar can be dragged (#1215). Checked on the frame that first
        // knows the monitor: the off-screen check below takes the pending geometry then.
        if let Some((pos, size)) = self.geometry.and_then(|g| g.fit_on_monitor(&window)) {
            ctx.send_viewport_cmd(egui::ViewportCommand::InnerSize(size));
            ctx.send_viewport_cmd(egui::ViewportCommand::OuterPosition(pos));
        }
        // The geometry saved for the next start is the active window's.
        let prev = self.app.ui.window;
        // Another document window's state is the one it last painted with: the host reports only
        // the root window's for this frame.
        let active = self.app.active_viewport();
        let tracked = if active == egui::ViewportId::ROOT {
            window
        } else {
            ctx.input_for(active, |i| RawWindowState::from_viewport(Some(i.viewport()), Some(i.viewport_rect())))
        };
        self.app.ui.window = WindowGeometry::track(prev, &tracked);
        // The first frame, once the monitor is known (as `take_rescue` waits for): maximize a
        // window that opened at its normal size so it never flashed on screen half-opened.
        let maximize = self.geometry.and_then(|g| g.maximize_after_open()).filter(|_| window.monitor_size.is_some());
        if let Some(pos) = take_rescue(&mut self.geometry, &window) {
            ctx.send_viewport_cmd(egui::ViewportCommand::OuterPosition(pos));
        }
        if let Some(command) = maximize {
            ctx.send_viewport_cmd(command);
        }
        // The window's close button: with other windows open only this window closes (the app
        // handles that while drawing it); the last one quits, asking first about unsaved changes
        // (`WordApp::close_requested`).
        let closing = ctx.input(|i| i.viewport().close_requested());
        if closing && (self.app.closes_a_window() || !self.app.close_requested()) {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
        } else if (closing || self.app.quit_requested) && !self.app.printing.busy() {
            // On macOS, letting eframe drop the window inside `-[NSApplication run]` aborts in
            // `-[_NSTouchBarFinderObservation invalidate]`. Command-Q calls `terminate:`. Once
            // the close is allowed, the host takes that path (`take_quit`) instead of dropping
            // the window on this turn.
            #[cfg(target_os = "macos")]
            {
                ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
                self.app.quit_requested = false;
                self.quit_pending = true;
            }
            #[cfg(not(target_os = "macos"))]
            if self.app.quit_requested {
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            }
        }
    }

    /// Records this frame's native window state before forwarding the hook, so logic never reads a
    /// stale inner rectangle from a hidden tick.
    pub fn raw_input_hook(&mut self, ctx: &egui::Context, raw: &mut egui::RawInput) {
        // Keep this frame's native window state. `logic` must not read the last painted
        // `InputState` when a hidden Wayland tick reports no fresh inner rect.
        self.window = RawWindowState::from_raw(raw);
        self.app.raw_input_hook(ctx, raw);
    }

    /// Draw the app into the given region.
    pub fn ui(&mut self, ui: &mut egui::Ui) {
        self.app.ui(ui);
    }

    /// Show the file dialogs the app queued, parented to the host window. Call after `logic` and
    /// after `ui`: those are the passes that ask for one. (Not part of the brief's surface: the
    /// parent window is `eframe::Frame`, which `logic` and `ui` don't receive.)
    pub fn show_file_dialogs(&self, frame: &eframe::Frame) {
        #[cfg(not(target_arch = "wasm32"))]
        self.dialogs.show(frame);
        #[cfg(target_arch = "wasm32")]
        let _ = frame;
    }

    /// Open a file path, as File › Open does; a failure is reported in the app's status bar.
    pub fn open_path(&mut self, path: &str) {
        if let Err(e) = self.app.run("file.open", serde_json::json!({"path": path})) {
            self.app.report_open_failure(path, &e);
        }
    }

    /// Persist what the app persists on quit: finish the print jobs, local recovery and the
    /// preferences; and remove the control key file.
    pub fn save_state(&mut self) {
        #[cfg(not(target_arch = "wasm32"))]
        print::finish_pending_jobs();
        self.app.session.finish_recovery();
        save_prefs(&self.app);
        #[cfg(not(target_arch = "wasm32"))]
        if let Some(key_file) = &self.key_file {
            key_file.remove();
        }
    }

    /// False when the app has unsaved work or a print job in flight, so the host must ask
    /// (`logic` does, through `WordApp::close_requested`) before closing.
    pub fn can_close(&self) -> bool {
        !self.app.printing.busy() && !self.app.has_unsaved_documents()
    }

    /// macOS: whether the last window's close (or Command-Q) was allowed this frame. The host
    /// then quits the process the way Command-Q does; the shell never ends the process.
    #[cfg(target_os = "macos")]
    pub fn take_quit(&mut self) -> bool {
        std::mem::take(&mut self.quit_pending)
    }
}

/// `ui.json` in the settings folder, which the MCP bridge also uses to find the control key.
fn prefs_path() -> Option<std::path::PathBuf> {
    iridium_docs_control_key::settings_dir().map(|b| b.join("ui.json"))
}

/// Where the log files live: `logs` in the preferences folder (see `logging` in the app).
pub fn log_dir() -> Option<std::path::PathBuf> {
    Some(prefs_path()?.parent()?.join("logs"))
}

/// `custom-dictionary.txt` in the settings folder: the words Add to Dictionary kept (#40).
fn user_dict_path() -> Option<std::path::PathBuf> {
    iridium_docs_control_key::settings_dir().map(|b| b.join(iridium_docs_engine::Session::USER_DICT_FILE))
}

fn load_user_dictionary(app: &mut WordApp) {
    if !prefs_enabled() {
        return;
    }
    if let Some(p) = user_dict_path() {
        iridium_docs_proof::load_user_dictionary(&p);
        app.session.user_dict_path = Some(p);
    }
}

/// Runs without preferences (`IRIDIUM_DOCS_NO_PREFS`, agents' test runs) neither read nor write them.
pub fn prefs_enabled() -> bool {
    std::env::var_os("IRIDIUM_DOCS_NO_PREFS").is_none()
}

fn load_prefs(app: &mut WordApp) {
    if !prefs_enabled() {
        return;
    }
    if let Some(p) = prefs_path()
        && let Ok(bytes) = std::fs::read(&p)
        && let Some(ui) = UiState::from_json(&bytes)
    {
        app.apply_prefs(ui);
    }
}

/// Fonts the user added (#582) live in `fonts` in the settings folder: load them, and store fonts
/// added later there. Runs without preferences neither read nor keep them.
pub fn load_user_fonts() {
    if !prefs_enabled() {
        return;
    }
    let Some(dir) = iridium_docs_control_key::settings_dir().map(|d| d.join("fonts")) else { return };
    let (loaded, skipped) = iridium_docs_fonts::FontDb::global().load_user_fonts(&dir);
    if !loaded.is_empty() || !skipped.is_empty() {
        log::info!("user fonts: {} loaded, {} skipped from {}", loaded.len(), skipped.len(), dir.display());
    }
}

/// The saved window geometry, read before the window opens (`load_prefs` runs after).
pub fn saved_window() -> Option<WindowGeometry> {
    if !prefs_enabled() {
        return None;
    }
    let bytes = std::fs::read(prefs_path()?).ok()?;
    UiState::from_json(&bytes)?.window?.sanitized()
}

fn save_prefs(app: &WordApp) {
    if !prefs_enabled() {
        return;
    }
    if let Some(p) = prefs_path() {
        if let Some(dir) = p.parent()
            && let Err(e) = std::fs::create_dir_all(dir)
        {
            log::warn!("preferences: cannot create {}: {e}", dir.display());
            return;
        }
        match serde_json::to_vec_pretty(&app.prefs()) {
            Ok(bytes) => {
                if let Err(e) = write_prefs(&p, &bytes) {
                    log::warn!("preferences: cannot save {}: {e}", p.display());
                }
            }
            Err(e) => log::warn!("preferences: cannot serialize: {e}"),
        }
    }
}

/// Writes `bytes` to a sibling temporary file and renames it over `path`, so a failed or
/// interrupted write leaves the previous preferences in place.
fn write_prefs(path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
    let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| "ui.json".into());
    let tmp = path.with_file_name(format!(".{name}.{}.tmp", std::process::id()));
    let written = std::fs::write(&tmp, bytes).and_then(|()| std::fs::rename(&tmp, path));
    if written.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    written
}

/// Native file dialogs, shown without blocking the window (`file_dialogs`, #94), File › Print
/// through the system spooler (`print`), the system clipboard's text, formatted copies,
/// pictures and format names (`clipboard`, #45, #584, #687, #833), the system's animation setting
/// (`animations`), and making Docs the default app for Word documents (`default_apps`, #295).
#[cfg(not(target_arch = "wasm32"))]
fn services(file_dialog: file_dialogs::Hook, ctx: &egui::Context) -> Services {
    Services {
        file_dialog: Some(file_dialog),
        printers: Some(print::discover()),
        print_native: Some(print::submit()),
        clipboard_picture: Some(Box::new(clipboard::picture)),
        make_default_app: default_apps::hook(),
        // Personal templates live in `Templates` in the settings folder (#2852), made on first save.
        templates_dir: iridium_docs_control_key::settings_dir().map(|d| d.join("Templates")),
        animations_enabled: Some(animations::hook(ctx)),
        clipboard_text: Some(Box::new(clipboard::text)),
        clipboard_html: Some(Box::new(clipboard::html)),
        set_clipboard_html: Some(Box::new(clipboard::set_html)),
        clipboard_rtf: Some(Box::new(clipboard::rtf)),
        clipboard_formats: Some(Box::new(clipboard::formats)),
        ..Default::default()
    }
}

/// The browser has no system clipboard handle, native dialogs, spooler or default-app hook: those
/// entries stay unset (the web host supplies the browser's own).
#[cfg(target_arch = "wasm32")]
fn services(ctx: &egui::Context) -> Services {
    Services { animations_enabled: Some(animations::hook(ctx)), ..Default::default() }
}

#[cfg(not(target_arch = "wasm32"))]
/// Open a file whose name isn't valid Unicode (#1440). `file.open` takes its path as text, so it
/// gets the file's bytes under the lossy name, and the document then keeps the real path to save to.
/// The bytes are read as `file.open` reads a path: only a regular file, and at most 2 GB.
fn open_non_unicode(app: &mut WordApp, path: &std::path::Path) {
    let name = path.to_string_lossy();
    let opened = iridium_docs_engine::io::read_document(path)
        .and_then(|bytes| app.run("file.open", serde_json::json!({"path": name, "data": iridium_docs_engine::cmd::insert::base64_encode(&bytes)})));
    match opened {
        // Not when it waits for a password: that open names the document itself.
        Ok(r) if r.get("pending").is_none() => app.session.path = Some(path.into()),
        Ok(_) => {}
        Err(e) => {
            app.report_open_failure(&name, &e);
        }
    }
}

// Not on macOS: APFS refuses file names that aren't valid UTF-8, so no such file can exist there.
#[cfg(all(test, unix, not(target_os = "macos")))]
mod tests {
    use super::*;
    use std::os::unix::ffi::OsStringExt;
    #[test]
    fn a_file_whose_name_isnt_unicode_opens_and_saves_back_to_itself() {
        let dir = std::env::temp_dir().join(format!("wc-app-non-utf8-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join(std::ffi::OsString::from_vec(b"caf\xe9.txt".to_vec()));
        std::fs::write(&path, "Bonjour").unwrap();

        let mut app = WordApp::new(Session::new(iridium_docs_doc::Document::new()), Services::default());
        open_non_unicode(&mut app, &path);
        assert_eq!(app.session.doc.plain_text(iridium_docs_doc::StoryRef::Body).trim(), "Bonjour");
        assert_eq!(app.session.path.as_deref(), Some(path.as_path()));

        app.run("caret.docEnd", serde_json::json!({})).unwrap();
        app.run("text.insert", serde_json::json!({"text": " encore"})).unwrap();
        app.run("file.save", serde_json::json!({})).unwrap();
        assert!(std::fs::read_to_string(&path).unwrap().contains("Bonjour encore"));
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 1, "a second file was written");

        // A file that can't be read is a warning, as one that fails to open by name is.
        open_non_unicode(&mut app, &dir.join(std::ffi::OsString::from_vec(b"gon\xe9.txt".to_vec())));
        assert_eq!(app.session.path.as_deref(), Some(path.as_path()));
        let _ = std::fs::remove_dir_all(dir);
    }

    /// A named pipe or a device under such a name is a warning, not a read: the pipe blocked
    /// start-up until something wrote to it, and `/dev/zero` read until memory ran out.
    #[test]
    fn a_pipe_or_device_whose_name_isnt_unicode_is_not_read() {
        let dir = std::env::temp_dir().join(format!("wc-app-non-utf8-dev-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let fifo = dir.join(std::ffi::OsString::from_vec(b"fif\xe9.txt".to_vec()));
        if !std::process::Command::new("mkfifo").arg(&fifo).status().is_ok_and(|s| s.success()) {
            let _ = std::fs::remove_dir_all(&dir);
            eprintln!("mkfifo unavailable; skipping");
            return;
        }
        let zero = dir.join(std::ffi::OsString::from_vec(b"z\xe9ro.txt".to_vec()));
        std::os::unix::fs::symlink("/dev/zero", &zero).unwrap();
        // If the open blocks on the pipe, a writer comes after 10 s, so the test fails rather than hangs.
        let unblock = fifo.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_secs(10));
            let _ = std::fs::OpenOptions::new().write(true).open(unblock);
        });

        let mut app = WordApp::new(Session::new(iridium_docs_doc::Document::new()), Services::default());
        app.run("text.insert", serde_json::json!({"text": "kept"})).unwrap();
        for p in [&fifo, &zero] {
            let started = std::time::Instant::now();
            open_non_unicode(&mut app, p);
            assert!(started.elapsed() < std::time::Duration::from_secs(5), "{p:?} took {:?}", started.elapsed());
            assert_eq!(app.session.path, None, "{p:?}");
            assert!(app.session.doc.plain_text(iridium_docs_doc::StoryRef::Body).contains("kept"), "{p:?}");
        }
        let _ = std::fs::remove_dir_all(dir);
    }
}

#[cfg(test)]
mod prefs_tests {
    use super::write_prefs;

    #[test]
    fn failed_preferences_write_keeps_the_old_file_and_reports_the_error() {
        let dir = std::env::temp_dir().join(format!("iridium-docs-prefs-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("ui.json");
        std::fs::write(&path, b"old").unwrap();
        write_prefs(&path, b"new").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"new");
        // A directory squatting on the temporary name makes the preparation step fail.
        std::fs::create_dir(dir.join(format!(".ui.json.{}.tmp", std::process::id()))).unwrap();
        assert!(write_prefs(&path, b"newer").is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"new");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
