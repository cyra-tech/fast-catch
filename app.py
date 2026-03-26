import os
import sys
import ssl
import certifi
import queue
import threading
import subprocess
from pathlib import Path

import objc
from Foundation import NSObject, NSTimer
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSFont,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSOpenPanel,
    NSPopUpButton,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSProgressIndicator,
    NSScrollView,
    NSSquareStatusItemLength,
    NSStatusBar,
    NSTextField,
    NSTextView,
    NSView,
    NSViewController,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSMakeRect,
    NSMaxX,
    NSMinYEdge,
)
from PyObjCTools import AppHelper

APP_NAME = "Fast Catch"
APP_VERSION = "0.1"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"
ACCENT = "#001f4d"

WIDTH_SIZABLE = 1 << 1
HEIGHT_SIZABLE = 1 << 4
MIN_X_MARGIN = 1 << 0
MAX_X_MARGIN = 1 << 2
MIN_Y_MARGIN = 1 << 3
MAX_Y_MARGIN = 1 << 5



def hex_to_rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def nscolor(color: str, alpha: float = 1.0):
    from AppKit import NSColor
    r, g, b = hex_to_rgb(color)
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base, *parts)


def bundled_bin_path(name: str) -> str | None:
    candidate = resource_path("bin", name)
    if os.path.exists(candidate):
        return candidate
    path = shutil_which(name)
    return path


def shutil_which(name: str) -> str | None:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class UILogger:
    def __init__(self, q: queue.Queue):
        self.q = q

    def debug(self, msg):
        self.q.put(("log", str(msg)))

    def warning(self, msg):
        self.q.put(("log", f"WARNING: {msg}"))

    def error(self, msg):
        self.q.put(("log", f"ERROR: {msg}"))


class DownloadManager:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.thread = None
        self.active = False

    def cancel(self):
        self.cancel_event.set()

    def start(self, url: str, folder: str, mode: str, q: queue.Queue):
        if self.active:
            q.put(("error", "A download is already running."))
            return
        self.cancel_event.clear()
        self.thread = threading.Thread(target=self._worker, args=(url, folder, mode, q), daemon=True)
        self.active = True
        self.thread.start()

    def _worker(self, url: str, folder: str, mode: str, q: queue.Queue):
        try:
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
            ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
            import yt_dlp

            ffmpeg = bundled_bin_path("ffmpeg")
            ffprobe = bundled_bin_path("ffprobe")

            os.makedirs(folder, exist_ok=True)
            q.put(("status", "Starting download..."))
            q.put(("log", f"Target folder: {folder}"))

            def hook(data):
                if self.cancel_event.is_set():
                    raise Exception("Download cancelled.")
                status = data.get("status")
                if status == "downloading":
                    p = data.get("_percent_str", "0%")
                    text = p.replace("%", "").strip()
                    try:
                        value = float(text)
                    except ValueError:
                        value = 0.0
                    q.put(("progress", value))
                    speed = data.get("_speed_str", "")
                    eta = data.get("_eta_str", "")
                    q.put(("status", f"Downloading... {p}  {speed}  ETA {eta}".strip()))
                elif status == "finished":
                    q.put(("progress", 100.0))
                    q.put(("status", "Finishing..."))

            ydl_opts = {
                "outtmpl": os.path.join(folder, "%(title)s.%(ext)s"),
                "progress_hooks": [hook],
                "logger": UILogger(q),
                "noplaylist": True,
                "restrictfilenames": False,
                "quiet": True,
                "no_warnings": False,
            }

            if mode == "mp4":
                ydl_opts["format"] = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
                ydl_opts["merge_output_format"] = "mp4"
                if ffmpeg:
                    ydl_opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
            elif mode == "mp3":
                if not (ffmpeg and ffprobe):
                    raise RuntimeError("FFmpeg/FFprobe not found. Build the app after installing ffmpeg so MP3 export can be bundled.")
                ydl_opts["format"] = "bestaudio/best"
                ydl_opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            else:
                raise RuntimeError("Unsupported format.")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if self.cancel_event.is_set():
                q.put(("status", "Cancelled."))
                q.put(("log", "Download cancelled."))
            else:
                q.put(("done", folder))
        except Exception as e:
            q.put(("error", str(e)))
        finally:
            self.active = False
            self.cancel_event.clear()


class MainWindowController(NSObject):
    def initWithApp_(self, app):
        self = objc.super(MainWindowController, self).init()
        if self is None:
            return None
        self.app = app
        self.queue = app.ui_queue
        self._build_window()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.15, self, "processQueue:", None, True
        )
        return self

    @objc.python_method
    def _field(self, frame, value=""):
        f = NSTextField.alloc().initWithFrame_(frame)
        f.setStringValue_(value)
        f.setFont_(NSFont.systemFontOfSize_(16))
        f.setTextColor_(nscolor("#f4f7ff"))
        f.setBackgroundColor_(nscolor("#021632", 0.95))
        f.setBordered_(True)
        f.setDrawsBackground_(True)
        f.setBezeled_(True)
        return f

    @objc.python_method
    def _label(self, frame, text, bold=False, size=15):
        l = NSTextField.labelWithString_(text)
        l.setFrame_(frame)
        l.setTextColor_(nscolor("#e7efff"))
        l.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        l.setBackgroundColor_(nscolor(ACCENT, 0.0))
        return l

    @objc.python_method
    def _button(self, frame, title, action):
        b = NSButton.alloc().initWithFrame_(frame)
        b.setTitle_(title)
        b.setBezelStyle_(NSBezelStyleRounded)
        b.setTarget_(self)
        b.setAction_(action)
        return b

    @objc.python_method
    def _build_window(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, 960, 640),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_(APP_TITLE)
        self.window.setDelegate_(self)
        self.window.setBackgroundColor_(nscolor("#03112a"))
        self.window.setMinSize_((820, 600))

        content = self.window.contentView()
        bg = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        bg.setAutoresizingMask_(WIDTH_SIZABLE | HEIGHT_SIZABLE)
        bg.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        bg.setMaterial_(NSVisualEffectMaterialHUDWindow)
        bg.setState_(NSVisualEffectStateActive)
        content.addSubview_(bg)

        panel = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(28, 325, 904, 220))
        panel.setAutoresizingMask_(WIDTH_SIZABLE | MIN_Y_MARGIN)
        panel.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        panel.setMaterial_(NSVisualEffectMaterialHUDWindow)
        panel.setState_(NSVisualEffectStateActive)
        bg.addSubview_(panel)

        panel.addSubview_(self._label(NSMakeRect(30, 182, 200, 24), "Video link", True, 15))
        self.linkField = self._field(NSMakeRect(30, 145, 840, 34), "")
        self.linkField.setAutoresizingMask_(WIDTH_SIZABLE | MIN_Y_MARGIN)
        panel.addSubview_(self.linkField)

        panel.addSubview_(self._label(NSMakeRect(30, 105, 200, 24), "Download folder", True, 15))
        default_folder = str(Path.home() / "Downloads")
        self.folderField = self._field(NSMakeRect(30, 68, 580, 34), default_folder)
        self.folderField.setAutoresizingMask_(WIDTH_SIZABLE | MIN_Y_MARGIN)
        panel.addSubview_(self.folderField)
        browse = self._button(NSMakeRect(628, 68, 242, 34), "Browse", "browseFolder:")
        browse.setAutoresizingMask_(MIN_X_MARGIN | MAX_Y_MARGIN)
        panel.addSubview_(browse)

        panel.addSubview_(self._label(NSMakeRect(30, 28, 120, 24), "Format", True, 15))
        self.formatPopup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(30, 0, 180, 32), False)
        self.formatPopup.setAutoresizingMask_(MAX_X_MARGIN | MIN_Y_MARGIN)
        self.formatPopup.addItemsWithTitles_(["MP4", "MP3"])
        panel.addSubview_(self.formatPopup)

        btn_y = 262
        self.downloadButton = self._button(NSMakeRect(170, btn_y, 150, 36), "Download", "downloadPressed:")
        self.cancelButton = self._button(NSMakeRect(340, btn_y, 150, 36), "Cancel", "cancelPressed:")
        self.openButton = self._button(NSMakeRect(510, btn_y, 150, 36), "Open Folder", "openFolder:")
        self.clearButton = self._button(NSMakeRect(680, btn_y, 150, 36), "Clear", "clearPressed:")
        for b in (self.downloadButton, self.cancelButton, self.openButton, self.clearButton):
            b.setAutoresizingMask_(MIN_X_MARGIN | MAX_X_MARGIN)
            bg.addSubview_(b)

        bg.addSubview_(self._label(NSMakeRect(30, 220, 120, 24), "Progress", True, 15))
        self.progressBar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(30, 190, 900, 18))
        self.progressBar.setIndeterminate_(False)
        self.progressBar.setMinValue_(0)
        self.progressBar.setMaxValue_(100)
        self.progressBar.setDoubleValue_(0)
        self.progressBar.setAutoresizingMask_(WIDTH_SIZABLE | MAX_Y_MARGIN)
        bg.addSubview_(self.progressBar)

        bg.addSubview_(self._label(NSMakeRect(30, 145, 120, 24), "Status", True, 15))
        self.statusLabel = self._label(NSMakeRect(30, 115, 900, 24), "Ready", False, 14)
        self.statusLabel.setAutoresizingMask_(WIDTH_SIZABLE | MAX_Y_MARGIN)
        bg.addSubview_(self.statusLabel)

        bg.addSubview_(self._label(NSMakeRect(30, 85, 120, 24), "Log", True, 15))
        self.logScroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(30, 20, 900, 70))
        self.logScroll.setAutoresizingMask_(WIDTH_SIZABLE | HEIGHT_SIZABLE)
        self.logScroll.setHasVerticalScroller_(True)
        self.logText = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 900, 70))
        self.logText.setEditable_(False)
        self.logText.setBackgroundColor_(nscolor("#021632", 0.95))
        self.logText.setTextColor_(nscolor("#f4f7ff"))
        self.logText.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12, 0))
        self.logScroll.setDocumentView_(self.logText)
        bg.addSubview_(self.logScroll)

    def windowShouldClose_(self, sender):
        sender.orderOut_(None)
        return False

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeFirstResponder_(self.linkField)

    def browseFolder_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() == 1:
            url = panel.URL()
            if url:
                self.folderField.setStringValue_(url.path())
                self.app.default_folder = url.path()
                if self.app.quick_panel:
                    self.app.quick_panel.setFolder_(url.path())

    def downloadPressed_(self, sender):
        url = self.linkField.stringValue().strip()
        folder = self.folderField.stringValue().strip()
        mode = "mp3" if self.formatPopup.titleOfSelectedItem() == "MP3" else "mp4"
        self._start_download(url, folder, mode)

    @objc.python_method
    def _start_download(self, url, folder, mode):
        if not url:
            self.statusLabel.setStringValue_("Link cannot be empty.")
            return
        if not folder:
            self.statusLabel.setStringValue_("Folder cannot be empty.")
            return
        self.app.default_folder = folder
        if self.app.quick_panel:
            self.app.quick_panel.setFolder_(folder)
        self.progressBar.setDoubleValue_(0)
        self.statusLabel.setStringValue_("Queued...")
        self.app.downloader.start(url, folder, mode, self.queue)

    def cancelPressed_(self, sender):
        self.app.downloader.cancel()
        self.statusLabel.setStringValue_("Cancelling...")
        self._append_log("Cancellation requested.")

    def openFolder_(self, sender):
        folder = self.folderField.stringValue().strip() or self.app.default_folder
        if folder and os.path.isdir(folder):
            subprocess.Popen(["open", folder])

    def clearPressed_(self, sender):
        self.linkField.setStringValue_("")
        self.progressBar.setDoubleValue_(0)
        self.statusLabel.setStringValue_("Ready")
        self.logText.setString_("")

    @objc.python_method
    def _append_log(self, text: str):
        current = self.logText.string() or ""
        self.logText.setString_(current + text.rstrip() + "\n")
        self.logText.scrollRangeToVisible_((len(self.logText.string()), 0))

    def processQueue_(self, timer):
        while True:
            try:
                kind, value = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.progressBar.setDoubleValue_(float(value))
            elif kind == "status":
                self.statusLabel.setStringValue_(str(value))
            elif kind == "log":
                self._append_log(str(value))
            elif kind == "done":
                self.statusLabel.setStringValue_("Download finished successfully.")
                self.progressBar.setDoubleValue_(100)
                self._append_log("Download finished successfully.")
                self.app.update_status_title("✓")
            elif kind == "error":
                self.statusLabel.setStringValue_("Download failed.")
                self._append_log(f"ERROR: {value}")
                self.app.update_status_title("!")


class QuickPanelViewController(NSViewController):
    def initWithApp_(self, app):
        self = objc.super(QuickPanelViewController, self).init()
        if self is None:
            return None
        self.app = app
        self._build_view()
        return self

    @objc.python_method
    def _build_view(self):
        root = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 420, 180))
        root.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        root.setMaterial_(NSVisualEffectMaterialHUDWindow)
        root.setState_(NSVisualEffectStateActive)

        title = NSTextField.labelWithString_(APP_NAME)
        title.setFrame_(NSMakeRect(20, 140, 180, 24))
        title.setTextColor_(nscolor("#f4f7ff"))
        title.setFont_(NSFont.boldSystemFontOfSize_(17))
        root.addSubview_(title)

        self.linkField = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 98, 380, 30))
        self.linkField.setPlaceholderString_("Paste link")
        root.addSubview_(self.linkField)

        self.folderLabel = NSTextField.labelWithString_(self.app.default_folder)
        self.folderLabel.setFrame_(NSMakeRect(20, 66, 275, 20))
        self.folderLabel.setTextColor_(nscolor("#d8e5ff"))
        root.addSubview_(self.folderLabel)

        choose = NSButton.alloc().initWithFrame_(NSMakeRect(305, 60, 95, 28))
        choose.setTitle_("Folder")
        choose.setTarget_(self)
        choose.setAction_("chooseFolder:")
        choose.setBezelStyle_(NSBezelStyleRounded)
        root.addSubview_(choose)

        self.formatPopup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(20, 24, 90, 28), False)
        self.formatPopup.addItemsWithTitles_(["MP4", "MP3"])
        root.addSubview_(self.formatPopup)

        dl = NSButton.alloc().initWithFrame_(NSMakeRect(290, 20, 110, 34))
        dl.setTitle_("Download")
        dl.setTarget_(self)
        dl.setAction_("downloadNow:")
        dl.setBezelStyle_(NSBezelStyleRounded)
        root.addSubview_(dl)

        self.setView_(root)

    def viewDidAppear(self):
        objc.super(QuickPanelViewController, self).viewDidAppear()
        self.view().window().makeFirstResponder_(self.linkField)

    def setFolder_(self, folder: str):
        self.folderLabel.setStringValue_(folder)

    def chooseFolder_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() == 1:
            url = panel.URL()
            if url:
                folder = url.path()
                self.folderLabel.setStringValue_(folder)
                self.app.default_folder = folder
                self.app.main_controller.folderField.setStringValue_(folder)

    def downloadNow_(self, sender):
        url = self.linkField.stringValue().strip()
        folder = self.folderLabel.stringValue().strip() or self.app.default_folder
        mode = "mp3" if self.formatPopup.titleOfSelectedItem() == "MP3" else "mp4"
        self.app.main_controller.linkField.setStringValue_(url)
        self.app.main_controller.folderField.setStringValue_(folder)
        self.app.main_controller._start_download(url, folder, mode)
        self.app.popover.performClose_(None)


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self.ui_queue = queue.Queue()
        self.default_folder = str(Path.home() / "Downloads")
        self.downloader = DownloadManager()
        self._setup_menu()
        self.main_controller = MainWindowController.alloc().initWithApp_(self)
        self.quick_panel = QuickPanelViewController.alloc().initWithApp_(self)
        self._setup_status_item()
        self.main_controller.show()

    @objc.python_method
    def _setup_menu(self):
        menubar = NSMenu.alloc().init()
        NSApp.setMainMenu_(menubar)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)

        app_item = NSMenuItem.alloc().init()
        menubar.addItem_(app_item)
        app_menu = NSMenu.alloc().initWithTitle_(APP_NAME)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Fast Catch", "terminate:", "q")
        app_menu.addItem_(quit_item)
        NSApp.mainMenu().setSubmenu_forItem_(app_menu, app_item)

        edit_item = NSMenuItem.alloc().init()
        menubar.addItem_(edit_item)
        edit_menu = NSMenu.alloc().initWithTitle_("Edit")
        edit_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Undo", "undo:", "z"))
        edit_menu.addItem_(NSMenuItem.separatorItem())
        edit_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Cut", "cut:", "x"))
        edit_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Copy", "copy:", "c"))
        edit_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Paste", "paste:", "v"))
        edit_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Select All", "selectAll:", "a"))
        NSApp.mainMenu().setSubmenu_forItem_(edit_menu, edit_item)

    @objc.python_method
    def _setup_status_item(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSSquareStatusItemLength)
        icon_path = resource_path("app_resources", "menubar_icon_source.png")
        image = NSImage.alloc().initByReferencingFile_(icon_path)
        if image:
            image.setSize_((18, 18))
            self.status_item.button().setImage_(image)
        else:
            self.status_item.button().setTitle_("FC")
        self.status_item.button().setToolTip_(APP_NAME)
        self.status_item.button().setTarget_(self)
        self.status_item.button().setAction_("toggleQuickPanel:")
        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setContentSize_((420, 180))
        self.popover.setContentViewController_(self.quick_panel)

    @objc.python_method
    def update_status_title(self, state_mark: str):
        tip = f"{APP_NAME} {state_mark}"
        self.status_item.button().setToolTip_(tip)

    def toggleQuickPanel_(self, sender):
        button = self.status_item.button()
        if self.popover.isShown():
            self.popover.performClose_(None)
        else:
            self.quick_panel.linkField.setStringValue_("")
            self.quick_panel.setFolder_(self.default_folder)
            self.popover.showRelativeToRect_ofView_preferredEdge_(button.bounds(), button, NSMinYEdge)
            NSApp.activateIgnoringOtherApps_(True)

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
        self.main_controller.show()
        return True

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False


def main():
    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
