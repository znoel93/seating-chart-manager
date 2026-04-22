"""
ui.py — Seating Chart Manager UI.
All colours and fonts are sourced from the `theme` module.
Switching themes calls theme.apply() then app.rebuild() which tears down
and reconstructs the entire widget tree with fresh colours.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
from collections import defaultdict
import os

import db
import optimizer as opt
import optimizer_table_mode as opt_table
import theme
import room_canvas as rc
import exporter


# ── Helpers that read from theme at call time ─────────────────────────────────

def make_btn(parent, text, command, style="primary", padx=14, pady=7, **kwargs):
    palettes = {
        "primary":  (theme.ACCENT,      theme.ACCENT_TEXT, theme.ACCENT_DARK),
        "danger":   (theme.DANGER,       theme.ACCENT_TEXT, theme.DANGER_DARK),
        "ghost":    (theme.GHOST_BG,     theme.TEXT,        theme.GHOST_DARK),
        "success":  (theme.SUCCESS,      theme.ACCENT_TEXT, theme.SUCCESS_DARK),
        "nav":      (theme.SIDEBAR_BG,   theme.SIDEBAR_TEXT, theme.SIDEBAR_ACT),
        "tab":      (theme.BG,           theme.TEXT_DIM,    theme.SEP),
        "tab_act":  (theme.ACCENT,       theme.ACCENT_TEXT, theme.ACCENT_DARK),
        "link":     (theme.BG,           theme.ACCENT,      theme.BG),
    }
    bg, fg, hover = palettes.get(style, palettes["primary"])
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                   font=theme.FONT_BOLD, padx=padx, pady=pady, **kwargs)
    lbl._btn_bg    = bg
    lbl._btn_hover = hover
    lbl._command   = command
    # Dispatch click and hover through the widget's current _command / _btn_*
    # attributes so callers can rebind behaviour dynamically by updating them.
    lbl.bind("<Button-1>", lambda e: lbl._command())
    lbl.bind("<Enter>",    lambda e: lbl.configure(bg=lbl._btn_hover))
    lbl.bind("<Leave>",    lambda e: lbl.configure(bg=lbl._btn_bg))
    return lbl


def styled_entry(parent, **kwargs):
    return tk.Entry(parent, relief="flat", bd=0,
                    bg=theme.GHOST_BG, fg=theme.TEXT,
                    insertbackground=theme.TEXT,
                    highlightthickness=2,
                    highlightbackground=theme.BORDER,
                    highlightcolor=theme.ACCENT,
                    font=theme.FONT_BODY, **kwargs)


def section_label(parent, text, bg=None):
    return tk.Label(parent, text=text, font=theme.FONT_HEAD,
                    bg=bg or theme.BG, fg=theme.TEXT, anchor="w")


def dim_label(parent, text, bg=None, **kwargs):
    """A small-font dim label. Extra kwargs (e.g. wraplength, justify)
    are forwarded to tk.Label."""
    return tk.Label(parent, text=text, font=theme.FONT_SMALL,
                    bg=bg or theme.BG, fg=theme.TEXT_DIM, anchor="w",
                    **kwargs)


def make_text_scroll_container(parent, bg=None, padx=0, pady=0,
                                width_px: int | None = None):
    """Create a Text-based scrollable container with trackpad-friendly scroll
    and native macOS compatibility. Callers get back a (container, text_widget)
    pair and can embed children via `text_widget.window_create("end", window=w)`.

    Handles the macOS Tk repaint bug where embedded widgets stay blank after
    being scrolled back into view — forces a redraw on each scroll tick.

    Forwards mousewheel events from any descendant widget back to the Text
    widget, so trackpad scrolling works even when the cursor is over an
    embedded child (button, entry, label, etc.).

    width_px: if set, pins the Text widget and container to this pixel width.
        Use when the scrollable should be a narrow sidebar rather than
        claiming the Text widget's default ~560px natural width.

    Does NOT block keyboard editing; callers should bind <Key> to return
    "break" if they want read-only scrolling.
    """
    bg = bg or theme.BG
    container = tk.Frame(parent, bg=bg)

    # If width_px is set, pin the container's horizontal size without locking
    # height. Approach: a spacer Frame at the top reserves the exact pixel
    # width, AND the Text widget is configured with width=1 (character columns)
    # so it requests minimal horizontal space. Since the container's width =
    # max(children widths), the spacer wins and the container stays at width_px.
    # The Text widget then gets fill="both" and stretches to fill the container.
    if width_px is not None:
        width_holder = tk.Frame(container, bg=bg, width=width_px, height=1)
        width_holder.pack(side="top", fill="x")

    text = tk.Text(container, bg=bg, bd=0, highlightthickness=0, wrap="none",
                   padx=padx, pady=pady, cursor="arrow",
                   takefocus=0, insertwidth=0,
                   insertontime=0, insertofftime=0,
                   width=1 if width_px is not None else 80)
    sb = ttk.Scrollbar(container, orient="vertical", command=text.yview)

    sb.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)

    def _scroll_cmd(*args):
        sb.set(*args)
        try:
            text.update_idletasks()
            for name in text.window_names():
                try:
                    w = text.nametowidget(name)
                    if w.winfo_exists():
                        w.update_idletasks()
                except (tk.TclError, KeyError):
                    pass
        except tk.TclError:
            pass
    text.configure(yscrollcommand=_scroll_cmd)

    # Mousewheel forwarding: re-fire events over descendants back at the
    # Text widget so scrolling works regardless of cursor position inside
    # the scrollable area. Uses event_generate (not yview_scroll) because
    # on macOS only the former actually scrolls the Text widget — see the
    # notes in the main _scrollable helper.
    def _forward_wheel(e):
        try:
            if text.winfo_exists():
                delta = getattr(e, "delta", 0)
                if delta != 0:
                    text.event_generate("<MouseWheel>", delta=delta)
                elif e.num == 4:
                    text.event_generate("<Button-4>")
                elif e.num == 5:
                    text.event_generate("<Button-5>")
        except tk.TclError:
            pass
        return "break"

    bound_widgets: set = set()
    def _bind_all_descendants(widget):
        try:
            wid = str(widget)
            # CRITICAL: never rebind the Text widget itself — event_generate
            # fires into the Text's bindtag, which would retrigger our own
            # handler and loop infinitely. Only rebind children.
            if widget is not text and wid not in bound_widgets:
                widget.bind("<MouseWheel>", _forward_wheel, add="+")
                widget.bind("<Button-4>",   _forward_wheel, add="+")
                widget.bind("<Button-5>",   _forward_wheel, add="+")
                bound_widgets.add(wid)
            for child in widget.winfo_children():
                _bind_all_descendants(child)
        except tk.TclError:
            pass

    # When content is added, rebind. <Configure> fires whenever the embedded
    # layout changes (new window_create, resize, etc.).
    def _on_configure(e):
        _bind_all_descendants(text)
    text.bind("<Configure>", _on_configure)
    # Also sweep once shortly after construction to catch initial children
    text.after(20, lambda: _bind_all_descendants(text))

    return container, text


# ── Student Picker widget (searchable dropdown) ───────────────────────────────

class _StudentPicker(tk.Frame):
    """
    A searchable dropdown for picking a student from a list.
    Usage:
        picker = _StudentPicker(parent, students_list)
        picker.pack(fill="x")
        ...
        sid = picker.get_selected_id()   # -> int or None
        picker.clear()

    Renders as: Entry (for typing to filter) + Listbox (showing matches).
    The listbox hides itself when a selection is made and reappears when
    the Entry gets focus or is typed in.
    """
    def __init__(self, parent, students: list):
        super().__init__(parent, bg=theme.PANEL)
        self._students = students
        self._selected_id: int | None = None

        self.var = tk.StringVar()
        self.entry = styled_entry(self, textvariable=self.var)
        self.entry.pack(fill="x")

        # Listbox container sits below the entry; shown/hidden as needed
        self._lb_frame = tk.Frame(self, bg=theme.BORDER, padx=1, pady=1)
        self.listbox = tk.Listbox(self._lb_frame, height=6,
                                  bg=theme.GHOST_BG, fg=theme.TEXT,
                                  selectbackground=theme.ACCENT,
                                  selectforeground=theme.ACCENT_TEXT,
                                  relief="flat", bd=0,
                                  font=theme.FONT_BODY,
                                  exportselection=False,
                                  activestyle="none")
        self.listbox.pack(fill="both", expand=True)

        # Event wiring
        self.var.trace_add("write", self._on_text_change)
        self.entry.bind("<FocusIn>",   lambda e: self._show_list())
        self.entry.bind("<Down>",      self._focus_list)
        self.entry.bind("<Return>",    self._pick_first)
        self.entry.bind("<Escape>",    lambda e: self._hide_list())
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self.listbox.bind("<Return>",  self._on_listbox_select)
        self.listbox.bind("<Escape>",  lambda e: (self._hide_list(),
                                                    self.entry.focus_set()))

        self._refresh_list()

    def _show_list(self):
        if not self._lb_frame.winfo_ismapped():
            self._lb_frame.pack(fill="x", pady=(2, 0))
            self._refresh_list()

    def _hide_list(self):
        if self._lb_frame.winfo_ismapped():
            self._lb_frame.pack_forget()

    def _on_text_change(self, *_):
        # Any typing invalidates a previous selection
        self._selected_id = None
        self._show_list()
        self._refresh_list()

    def _refresh_list(self):
        q = self.var.get().strip().lower()
        self.listbox.delete(0, "end")
        self._visible_students = []
        for s in self._students:
            label = s.get("display") or s["name"]
            if q and q not in label.lower():
                continue
            self.listbox.insert("end", label)
            self._visible_students.append(s)
        # Resize listbox to match content. Cap at 6 rows (then it scrolls);
        # min 1 row when there are no matches so the "no results" state
        # still has a visible height. Hide entirely if empty-text + no query.
        count = len(self._visible_students)
        if count == 0:
            # Show a "no matches" indicator by giving it minimum height
            self.listbox.configure(height=1)
            self.listbox.insert("end", "  (no matches)")
            # Grey out to indicate non-selectable
            self.listbox.itemconfigure(0, fg=theme.TEXT_MUTED)
        else:
            self.listbox.configure(height=min(6, count))

    def _focus_list(self, _e=None):
        if self.listbox.size() > 0:
            self.listbox.focus_set()
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _pick_first(self, _e=None):
        if self.listbox.size() > 0:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._on_listbox_select()

    def _on_listbox_select(self, _e=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._visible_students):
            return
        s = self._visible_students[idx]
        self._selected_id = s["id"]
        # Update the entry to show the selected name (without re-triggering
        # selection invalidation)
        self.var.trace_remove("write", self.var.trace_info()[0][1])
        self.var.set(s.get("display") or s["name"])
        self.var.trace_add("write", self._on_text_change)
        self._hide_list()
        self.entry.focus_set()

    def get_selected_id(self) -> int | None:
        """Return the currently-selected student id, or None if no selection."""
        return self._selected_id

    def clear(self):
        """Reset the picker to empty state."""
        self._selected_id = None
        self.var.trace_remove("write", self.var.trace_info()[0][1])
        self.var.set("")
        self.var.trace_add("write", self._on_text_change)
        self._hide_list()


# ── Spinner widget ────────────────────────────────────────────────────────────

class _Spinner(tk.Canvas):
    """
    Animated arc spinner. Draws 8 arc segments of decreasing opacity
    and rotates them every 80ms using after() callbacks.
    Purely Tkinter — no external dependencies.
    """
    SEGMENTS = 8
    STEP_DEG = 360 // 8   # 45°

    def __init__(self, parent, size: int = 40, color: str = "#4A7FCB",
                 bg: str = "#2D2D2D", **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg=bg, bd=0, highlightthickness=0, **kwargs)
        self._size    = size
        self._color   = color
        self._angle   = 0
        self._running = True
        self._after_id = None
        self._draw()

    def _hex_alpha(self, alpha: float) -> str:
        """Blend color toward background by alpha (0=transparent, 1=opaque)."""
        def _parse(h):
            h = h.lstrip("#")
            return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        bg_r, bg_g, bg_b = _parse(self.cget("bg"))
        fg_r, fg_g, fg_b = _parse(self._color)
        r = int(bg_r + (fg_r - bg_r) * alpha)
        g = int(bg_g + (fg_g - bg_g) * alpha)
        b = int(bg_b + (fg_b - bg_b) * alpha)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw(self):
        self.delete("all")
        s    = self._size
        pad  = s * 0.12
        x0, y0, x1, y1 = pad, pad, s - pad, s - pad
        w    = max(2, s // 8)

        for i in range(self.SEGMENTS):
            angle    = (self._angle + i * self.STEP_DEG) % 360
            alpha    = (i + 1) / self.SEGMENTS
            color    = self._hex_alpha(alpha)
            start_a  = angle
            self.create_arc(x0, y0, x1, y1,
                            start=start_a, extent=self.STEP_DEG - 4,
                            style="arc", outline=color, width=w)

        if self._running:
            self._angle    = (self._angle + self.STEP_DEG) % 360
            self._after_id = self.after(80, self._draw)

    def stop(self):
        self._running = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass


def _make_scrollable(parent):
    container = tk.Frame(parent, bg=theme.BG)
    container.pack(fill="both", expand=True)
    canvas = tk.Canvas(container, bg=theme.BG, bd=0, highlightthickness=0)
    sb     = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    frame  = tk.Frame(canvas, bg=theme.BG)
    frame.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=frame, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame


# ── Main Application ──────────────────────────────────────────────────────────

class SeatingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        db.init_db()
        theme.load_from_db()

        self.title("Seating Chart Manager")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self._current_nav = "home"
        self._page_cache  = {}
        self._build()
        # Pre-warm the cache on the main Tk event loop (idle callback).
        # Running this on a background thread causes SIGSEGV on macOS Tk
        # because sqlite3.Row objects and Tk internals don't play well
        # across threads. after_idle schedules _warm to run once Tk has
        # finished its startup layout, which is still very quick but safe.
        def _warm():
            try:
                if "classes" not in self._page_cache:
                    self._page_cache["classes"] = self._fetch_classes_data()
                if "layouts" not in self._page_cache:
                    self._page_cache["layouts"] = self._fetch_layouts_data()
            except Exception:
                pass  # Never let cache warming break startup
        self.after_idle(_warm)

    def _build(self):
        self.configure(bg=theme.BG)
        self._apply_ttk_style()

        # Sidebar
        self.sidebar = tk.Frame(self, bg=theme.SIDEBAR_BG, width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(self.sidebar, bg=theme.SIDEBAR_BG)
        logo.pack(fill="x", pady=(28, 20))
        tk.Label(logo, text="📋", font=("Helvetica", 32),
                 bg=theme.SIDEBAR_BG, fg=theme.SIDEBAR_TEXT).pack()
        tk.Label(logo, text="Seating\nManager",
                 font=(theme.FONT_HEAD[0], 14, "bold"),
                 bg=theme.SIDEBAR_BG, fg=theme.SIDEBAR_TEXT, justify="center").pack(pady=(4, 0))

        tk.Frame(self.sidebar, bg=theme.BORDER, height=1).pack(
            fill="x", padx=16, pady=(0, 8))

        self._nav_btns = {}
        for label, key in [("🏠   Home",     "home"),
                            ("🏫   Classes",  "classes"),
                            ("🪑   Layouts",  "layouts"),
                            ("⚙   Settings", "settings")]:
            btn = make_btn(self.sidebar, label,
                           command=lambda k=key: self._navigate(k),
                           style="nav", padx=20, pady=14,
                           anchor="w", width=18)
            btn.pack(fill="x")
            self._nav_btns[key] = btn

        self.content = tk.Frame(self, bg=theme.BG)
        self.content.pack(side="left", fill="both", expand=True)

        self._navigate(self._current_nav)

    def rebuild(self):
        """Tear down and rebuild everything with the current theme."""
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _apply_ttk_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview",
                        background=theme.PANEL, foreground=theme.TEXT,
                        rowheight=30, fieldbackground=theme.PANEL,
                        font=theme.FONT_BODY, borderwidth=0, relief="flat")
        style.configure("Treeview.Heading",
                        background=theme.SEP, foreground=theme.TEXT_DIM,
                        font=theme.FONT_BOLD, relief="flat")
        style.map("Treeview",
                  background=[("selected", theme.ACCENT)],
                  foreground=[("selected", theme.ACCENT_TEXT)])
        style.configure("Vertical.TScrollbar",
                        background=theme.GHOST_BG, troughcolor=theme.BG,
                        arrowcolor=theme.TEXT_DIM, borderwidth=0)
        style.configure("TCombobox",
                        fieldbackground=theme.GHOST_BG,
                        background=theme.GHOST_BG,
                        foreground=theme.TEXT,
                        selectbackground=theme.ACCENT,
                        arrowcolor=theme.TEXT)
        style.map("TCombobox",
                  fieldbackground=[("readonly", theme.GHOST_BG)],
                  foreground=[("readonly", theme.TEXT)])

    def _navigate(self, key):
        self._current_nav = key
        for k, btn in self._nav_btns.items():
            active = (k == key)
            bg = theme.SIDEBAR_ACT if active else theme.SIDEBAR_BG
            fg = theme.ACCENT if active else theme.SIDEBAR_TEXT
            btn.configure(bg=bg, fg=fg)
            btn._btn_bg    = bg
            btn._btn_hover = theme.SIDEBAR_ACT
        self._clear()
        {"home":     self._show_home,
         "classes":  self._show_classes,
         "layouts":  self._show_layouts,
         "settings": self._show_settings}[key]()
        # Safety net: force paint regardless of what the page builder did.
        # macOS Tk 9 on Python 3.14 defers widget paint until the next input
        # event unless we explicitly flush the event queue here.
        self._force_paint()

    # ── Page cache ────────────────────────────────────────────────────────────
    # Stores pre-fetched data so repeat navigation is instant.
    # Invalidated by mutations (add/edit/delete).

    def _get_cached(self, key: str):
        return getattr(self, "_page_cache", {}).get(key)

    def _set_cached(self, key: str, data):
        if not hasattr(self, "_page_cache"):
            self._page_cache = {}
        self._page_cache[key] = data

    def _invalidate_cache(self, *keys):
        cache = getattr(self, "_page_cache", {})
        for k in keys:
            cache.pop(k, None)

    def _fetch_classes_data(self) -> list:
        include_archived = bool(getattr(self, "_show_archived_classes", False))
        classes = db.get_all_classes(include_archived=include_archived)
        for cls in classes:
            cls["_students"] = db.get_students_for_class(cls["id"])
            cls["_rounds"]   = db.get_rounds_for_class(cls["id"])
        return classes

    def _fetch_layouts_data(self) -> list:
        layouts = db.get_all_layouts()
        for layout in layouts:
            layout["_tables"] = db.get_tables_for_layout(layout["id"])
            layout["_locked"] = db.layout_has_rounds(layout["id"])
            layout["_in_use"] = db.is_layout_in_use(layout["id"])
        return layouts

    # ── Incremental card renderer ─────────────────────────────────────────────
    # Builds one card per event-loop tick so the spinner stays alive and
    # the UI feels responsive even with many items.

    def _render_cards(self, items: list, build_card_fn, scroll_frame):
        """Build all cards synchronously. Fast enough to not need incremental."""
        for item in items:
            build_card_fn(scroll_frame, item)
        self._stop_spinner()

    def _stop_spinner(self):
        spinner = getattr(self, "_active_spinner", None)
        if spinner:
            try:
                spinner.stop()
            except Exception:
                pass
            self._active_spinner = None

    def _force_paint(self):
        """
        Force macOS Tkinter to actually paint the window NOW instead of
        waiting for the next input event. Without this, newly-created
        widgets on macOS sometimes don't render until the user moves
        the mouse or presses a key.
        """
        try:
            self.update_idletasks()
            self.update()
        except Exception:
            pass

    def _show_spinner(self):
        f = tk.Frame(self.content, bg=theme.BG)
        f.place(relx=0.5, rely=0.45, anchor="center")
        spinner = _Spinner(f, size=52, color=theme.ACCENT, bg=theme.BG)
        spinner.pack(pady=(0, 14))
        tk.Label(f, text="Loading…", font=theme.FONT_BODY,
                 bg=theme.BG, fg=theme.TEXT_MUTED).pack()
        self._active_spinner = spinner
        # Force the spinner to actually appear before anything else happens
        self.update()

    def _clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _page_header(self, title, btn_text=None, btn_cmd=None):
        bar = tk.Frame(self.content, bg=theme.BG, pady=18, padx=28)
        bar.pack(fill="x")
        tk.Label(bar, text=title, font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(side="left")
        if btn_text and btn_cmd:
            make_btn(bar, btn_text, btn_cmd, style="primary").pack(side="right")
        tk.Frame(self.content, bg=theme.SEP, height=1).pack(fill="x", padx=28)

    def _scrollable(self, parent):
        """
        Scrollable frame with auto-hiding scrollbar. Uses tk.Text as the
        scroll host for native macOS trackpad support.
        """
        container = tk.Frame(parent, bg=theme.BG)
        container.pack(fill="both", expand=True)

        text = tk.Text(container, bg=theme.BG, bd=0, highlightthickness=0,
                        wrap="none", padx=0, pady=0, cursor="arrow",
                        takefocus=0, insertwidth=0,
                        insertontime=0, insertofftime=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=text.yview)

        # Always show the scrollbar — dynamically packing/unpacking it
        # during Tk geometry passes has been implicated in macOS SIGSEGV
        # crashes when scrolling activates. A permanently visible bar is
        # a more stable trade.
        sb.pack(side="right", fill="y")

        def _yscroll_cmd(*args):
            sb.set(*args)
            # Force embedded widgets to repaint as they scroll into view
            try:
                text.update_idletasks()
                for name in text.window_names():
                    try:
                        w = text.nametowidget(name)
                        if w.winfo_exists():
                            w.update_idletasks()
                    except (tk.TclError, KeyError):
                        pass
            except tk.TclError:
                pass
        text.configure(yscrollcommand=_yscroll_cmd)
        text.pack(side="left", fill="both", expand=True)

        text.bind("<Key>", lambda e: "break")
        text.bind("<Button-2>", lambda e: "break")

        frame = tk.Frame(text, bg=theme.BG)
        text.window_create("end", window=frame, stretch=1)
        text.insert("end", "\n")
        frame._scroll_text = text

        def _forward_wheel(e):
            try:
                if text.winfo_exists():
                    delta = getattr(e, 'delta', 0)
                    if delta != 0:
                        text.event_generate("<MouseWheel>", delta=delta)
                    elif e.num == 4:
                        text.event_generate("<Button-4>")
                    elif e.num == 5:
                        text.event_generate("<Button-5>")
            except tk.TclError:
                pass
            return "break"

        bound_widgets: set = set()
        def _bind_all_descendants(widget):
            try:
                wid = str(widget)
                if wid not in bound_widgets:
                    widget.bind("<MouseWheel>", _forward_wheel, add="+")
                    widget.bind("<Button-4>",   _forward_wheel, add="+")
                    widget.bind("<Button-5>",   _forward_wheel, add="+")
                    bound_widgets.add(wid)
                for child in widget.winfo_children():
                    _bind_all_descendants(child)
            except tk.TclError:
                pass

        def _on_frame_configure(e):
            _bind_all_descendants(frame)

        frame.bind("<Configure>", _on_frame_configure)
        frame.after(10, lambda: _bind_all_descendants(frame))

        return frame

    # ── Home ──────────────────────────────────────────────────────────────────

    def _show_home(self):
        f = tk.Frame(self.content, bg=theme.BG)
        f.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(f, text="Welcome back.", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(pady=(0, 10))
        classes   = db.get_all_classes()
        count_txt = (f"{len(classes)} class{'es' if len(classes)!=1 else ''} on record."
                     if classes else "No classes yet.")
        tk.Label(f, text=count_txt, font=theme.FONT_BODY,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=(0, 4))
        tk.Label(f, text="Use the sidebar to manage classes and room layouts.",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_MUTED).pack(pady=(0, 28))

        row = tk.Frame(f, bg=theme.BG)
        row.pack()
        make_btn(row, "  Open Classes  ", lambda: self._navigate("classes"),
                 style="primary", padx=20, pady=10).pack(side="left", padx=6)
        make_btn(row, "  Manage Layouts  ", lambda: self._navigate("layouts"),
                 style="ghost", padx=20, pady=10).pack(side="left", padx=6)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _show_settings(self):
        self._page_header("Settings")

        # Use our known-working _scrollable helper. Classes, Home, and Layouts
        # already use this with working trackpad support. No tk.Text tricks.
        sf   = self._scrollable(self.content)
        body = tk.Frame(sf, bg=theme.BG, padx=40, pady=24)
        body.pack(fill="both", expand=True)

        # Theme labels (emoji + name). Preview colors are pulled from
        # theme.PRESETS so they stay in sync if a preset is tuned. If
        # you add a preset to theme.py, add its label here too.
        THEME_LABELS = {
            "Midnight":       "🌙 Midnight",
            "Chalk":          "🍀 Chalk",
            "Navy":           "⚓ Navy",
            "Forest":         "🌲 Forest",
            "High Contrast":  "◑ High Contrast",
            "Smith":          "⚔ Smith",
            "Flower":         "🌸 Flower",
            "Ocean":          "🌊 Ocean",
            "Autumn":         "🍂 Autumn",
            "Winter":         "❄ Winter",
            "Spring":         "🌷 Spring",
            "Summer":         "☀ Summer",
            "Notebook":       "📓 Notebook",
            "Blackboard":     "⬛ Blackboard",
            "Whiteboard":     "⬜ Whiteboard",
            "Library":        "📚 Library",
            "Lab":            "🧪 Lab",
            "Retro Terminal": "🖥 Retro Terminal",
        }
        THEME_PREVIEWS = {
            name: (theme.PRESETS[name]["BG"],
                   theme.PRESETS[name]["ACCENT"],
                   label)
            for name, label in THEME_LABELS.items()
            if name in theme.PRESETS
        }

        FONT_PREVIEWS = [
            ("Classic",  "Georgia",       "Aa — Elegant serif"),
            ("Modern",   "Trebuchet MS",  "Aa — Clean modern"),
            ("Friendly", "Arial",         "Aa — Rounded & warm"),
            ("Sharp",    "Courier New",   "Aa — Monospace"),
            ("System",   "TkDefaultFont", "Aa — System default"),
            ("Smith",    "Impact",        "Aa — Bold & punchy"),
        ]

        SWATCH_W  = 165
        SWATCH_H  = 84
        FONT_W    = 155
        FONT_H    = 72
        GAP       = 12

        # ── Colour theme section ──────────────────────────────────────────────
        section_label(body, "Colour Theme").pack(anchor="w")
        dim_label(body, "Choose a colour scheme for the entire application.").pack(
            anchor="w", pady=(2, 14))

        theme_container = tk.Frame(body, bg=theme.BG)
        theme_container.pack(fill="x", pady=(0, 28))

        def _build_theme_grid(available_w: int):
            for w in theme_container.winfo_children():
                w.destroy()
            cols = max(1, (available_w + GAP) // (SWATCH_W + GAP))
            for idx, (name, (pbg, pacc, lbl)) in enumerate(THEME_PREVIEWS.items()):
                r, c   = divmod(idx, cols)
                active = (name == theme.ACTIVE_PRESET)
                cell   = tk.Frame(theme_container, bg=pbg,
                                  width=SWATCH_W, height=SWATCH_H,
                                  highlightbackground=pacc if active else "#444444",
                                  highlightthickness=3 if active else 1,
                                  cursor="hand2")
                cell.grid(row=r, column=c, padx=GAP//2, pady=GAP//2)
                cell.grid_propagate(False)
                tk.Label(cell, text=lbl, bg=pbg, fg=pacc,
                         font=(theme.FONT_BOLD[0], 11, "bold")).place(
                             relx=0.5, rely=0.38, anchor="center")
                if active:
                    tk.Label(cell, text="✓ active", bg=pbg, fg=pacc,
                             font=(theme.FONT_BODY[0], 9)).place(
                                 relx=0.5, rely=0.74, anchor="center")
                cell.bind("<Button-1>", lambda e, n=name: self._apply_theme(n))
                for child in cell.winfo_children():
                    child.bind("<Button-1>", lambda e, n=name: self._apply_theme(n))

        # ── Font pairing section ──────────────────────────────────────────────
        tk.Frame(body, bg=theme.SEP, height=1).pack(fill="x", pady=(0, 20))
        section_label(body, "Font Pairing").pack(anchor="w")
        dim_label(body, "Choose a font style for labels and text throughout the app.").pack(
            anchor="w", pady=(2, 14))

        font_container = tk.Frame(body, bg=theme.BG)
        font_container.pack(fill="x", pady=(0, 28))

        def _build_font_grid(available_w: int):
            for w in font_container.winfo_children():
                w.destroy()
            cols = max(1, (available_w + GAP) // (FONT_W + GAP))
            for idx, (name, preview_font, lbl) in enumerate(FONT_PREVIEWS):
                r, c   = divmod(idx, cols)
                active = (name == theme.ACTIVE_FONT)
                cell   = tk.Frame(font_container, bg=theme.PANEL,
                                  width=FONT_W, height=FONT_H,
                                  highlightbackground=theme.ACCENT if active else theme.BORDER,
                                  highlightthickness=2 if active else 1,
                                  cursor="hand2")
                cell.grid(row=r, column=c, padx=GAP//2, pady=GAP//2)
                cell.grid_propagate(False)
                tk.Label(cell, text=lbl, bg=theme.PANEL,
                         fg=theme.ACCENT if active else theme.TEXT,
                         font=(preview_font, 11)).place(
                             relx=0.5, rely=0.36, anchor="center")
                tk.Label(cell, text=name, bg=theme.PANEL,
                         fg=theme.TEXT_DIM,
                         font=(theme.FONT_BODY[0], 9)).place(
                             relx=0.5, rely=0.72, anchor="center")
                cell.bind("<Button-1>", lambda e, n=name: self._apply_font(n))
                for child in cell.winfo_children():
                    child.bind("<Button-1>", lambda e, n=name: self._apply_font(n))

        # ── Text Size section ─────────────────────────────────────────────────
        tk.Frame(body, bg=theme.SEP, height=1).pack(fill="x", pady=(0, 20))
        section_label(body, "Text Size").pack(anchor="w")
        dim_label(body, "Scales all text throughout the app. "
                        "Useful for projectors or accessibility.").pack(
            anchor="w", pady=(2, 14))

        size_row = tk.Frame(body, bg=theme.BG)
        size_row.pack(anchor="w", pady=(0, 28))
        size_options = ["Small", "Medium", "Large", "XL"]
        for s in size_options:
            active = (s == theme.ACTIVE_FONT_SIZE)
            btn = tk.Frame(size_row,
                            bg=theme.ACCENT if active else theme.PANEL,
                            highlightbackground=theme.ACCENT if active else theme.BORDER,
                            highlightthickness=2 if active else 1,
                            cursor="hand2")
            btn.pack(side="left", padx=6)
            scale = theme.FONT_SIZES[s]
            preview = tk.Label(btn, text=s,
                                bg=theme.ACCENT if active else theme.PANEL,
                                fg=theme.ACCENT_TEXT if active else theme.TEXT,
                                font=(theme.FONT_BODY[0], int(11 * scale)),
                                padx=20, pady=10)
            preview.pack()
            for w in (btn, preview):
                w.bind("<Button-1>", lambda e, size=s: self._apply_font_size(size))

        # ── PDF Export section ────────────────────────────────────────────────
        tk.Frame(body, bg=theme.SEP, height=1).pack(fill="x", pady=(28, 20))
        section_label(body, "PDF Export").pack(anchor="w")
        dim_label(body, "Defaults applied when exporting a round to PDF.").pack(
            anchor="w", pady=(2, 14))

        pdf_section = tk.Frame(body, bg=theme.BG)
        pdf_section.pack(fill="x", pady=(0, 28), anchor="w")

        # (1) Default save folder — explicit + implicit remember last used
        folder_row = tk.Frame(pdf_section, bg=theme.BG)
        folder_row.pack(fill="x", pady=(0, 10), anchor="w")
        tk.Label(folder_row, text="Default save folder",
                 font=theme.FONT_BOLD, bg=theme.BG, fg=theme.TEXT,
                 anchor="w").pack(anchor="w")
        tk.Label(folder_row,
                 text="Where exported PDFs save by default. Leave as "
                      "'Remember last used' to let the app track it automatically.",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 anchor="w", justify="left", wraplength=600).pack(
                     anchor="w", pady=(0, 6), fill="x")
        folder_row2 = tk.Frame(folder_row, bg=theme.BG)
        folder_row2.pack(fill="x", anchor="w", padx=(0, 8))
        current_folder = db.get_setting("default_save_folder", "")
        folder_display = current_folder if current_folder else "Remember last used"
        # Pack buttons FIRST (right-aligned), then the label fills remaining
        # space. This order guarantees both buttons stay visible even when
        # the row is narrower than the label would like.
        clear_btn = make_btn(folder_row2, "Clear",
                              command=self._clear_default_save_folder,
                              style="ghost", padx=10, pady=6)
        clear_btn.pack(side="right", padx=(6, 0))
        browse_btn = make_btn(folder_row2, "Browse…",
                               command=self._pick_default_save_folder,
                               style="ghost", padx=10, pady=6)
        browse_btn.pack(side="right", padx=(8, 0))
        self._save_folder_lbl = tk.Label(
            folder_row2, text=folder_display,
            font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.TEXT,
            padx=10, pady=6, anchor="w",
            highlightbackground=theme.BORDER, highlightthickness=1)
        self._save_folder_lbl.pack(side="left", fill="x", expand=True)

        # (2) Default orientation
        orient_row = tk.Frame(pdf_section, bg=theme.BG)
        orient_row.pack(fill="x", pady=(10, 0), anchor="w")
        tk.Label(orient_row, text="Default orientation",
                 font=theme.FONT_BOLD, bg=theme.BG, fg=theme.TEXT,
                 anchor="w").pack(anchor="w")
        self._orient_pref_var = tk.StringVar(
            value=db.get_setting("default_pdf_orientation", "landscape"))
        orient_buttons = tk.Frame(orient_row, bg=theme.BG)
        orient_buttons.pack(anchor="w", pady=(4, 0))
        for value, label in [("landscape", "Landscape"), ("portrait", "Portrait")]:
            tk.Radiobutton(
                orient_buttons, text=label,
                variable=self._orient_pref_var, value=value,
                command=lambda v=value: db.set_setting("default_pdf_orientation", v),
                font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT,
                activebackground=theme.BG, activeforeground=theme.TEXT,
                selectcolor=theme.PANEL,
                highlightthickness=0, borderwidth=0).pack(side="left",
                                                            padx=(0, 14))

        # (3) Include pairing score on export
        score_row = tk.Frame(pdf_section, bg=theme.BG)
        score_row.pack(fill="x", pady=(10, 0), anchor="w")
        self._score_pref_var = tk.BooleanVar(
            value=db.get_setting("default_pdf_include_score", "0") == "1")
        def _toggle_score_pref():
            db.set_setting("default_pdf_include_score",
                            "1" if self._score_pref_var.get() else "0")
        tk.Checkbutton(
            score_row, text="Include pairing score in PDF",
            variable=self._score_pref_var, command=_toggle_score_pref,
            font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT,
            activebackground=theme.BG, activeforeground=theme.TEXT,
            selectcolor=theme.PANEL,
            highlightthickness=0, borderwidth=0).pack(anchor="w")

        # (4) Open PDF after export
        openafter_row = tk.Frame(pdf_section, bg=theme.BG)
        openafter_row.pack(fill="x", pady=(6, 0), anchor="w")
        self._openafter_var = tk.BooleanVar(
            value=db.get_setting("open_pdf_after_export", "1") == "1")
        def _toggle_openafter():
            db.set_setting("open_pdf_after_export",
                            "1" if self._openafter_var.get() else "0")
        tk.Checkbutton(
            openafter_row, text="Open PDF automatically after export",
            variable=self._openafter_var, command=_toggle_openafter,
            font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT,
            activebackground=theme.BG, activeforeground=theme.TEXT,
            selectcolor=theme.PANEL,
            highlightthickness=0, borderwidth=0).pack(anchor="w")

        # ── Optimizer section ─────────────────────────────────────────────────
        tk.Frame(body, bg=theme.SEP, height=1).pack(fill="x", pady=(0, 20))
        section_label(body, "Optimizer").pack(anchor="w")
        tk.Label(body,
                 text="How long the solver is allowed to run before giving "
                      "up. Most classes solve in seconds; very constrained "
                      "ones may benefit from a longer budget.",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 anchor="w", justify="left", wraplength=600).pack(
                     anchor="w", pady=(2, 14), fill="x")

        opt_row = tk.Frame(body, bg=theme.BG)
        opt_row.pack(anchor="w", pady=(0, 28))
        self._timeout_pref_var = tk.StringVar(
            value=db.get_setting("default_optimizer_timeout", "Standard"))
        # Label → seconds mapping. "Ridiculous" earns its name.
        TIMEOUT_PRESETS = [
            ("Fast",       10,  "10s"),
            ("Standard",   30,  "30s"),
            ("Thorough",   120, "2 min"),
            ("Ridiculous", 600, "10 min"),
        ]
        # Keep references to each button's widgets so the click handler can
        # restyle them in place without calling self.rebuild() (which would
        # jump the scroll position back to the top of the page).
        self._timeout_btn_widgets: dict = {}
        for name, _secs, sub in TIMEOUT_PRESETS:
            active = (name == self._timeout_pref_var.get())
            btn = tk.Frame(opt_row,
                            bg=theme.ACCENT if active else theme.PANEL,
                            highlightbackground=theme.ACCENT if active else theme.BORDER,
                            highlightthickness=2 if active else 1,
                            cursor="hand2")
            btn.pack(side="left", padx=6)
            inner_btn = tk.Frame(btn,
                                   bg=theme.ACCENT if active else theme.PANEL,
                                   padx=18, pady=10)
            inner_btn.pack()
            name_lbl = tk.Label(inner_btn, text=name,
                                  bg=theme.ACCENT if active else theme.PANEL,
                                  fg=theme.ACCENT_TEXT if active else theme.TEXT,
                                  font=theme.FONT_BOLD)
            name_lbl.pack()
            sub_lbl = tk.Label(inner_btn, text=sub,
                                 bg=theme.ACCENT if active else theme.PANEL,
                                 fg=theme.ACCENT_TEXT if active else theme.TEXT_DIM,
                                 font=theme.FONT_SMALL)
            sub_lbl.pack()
            self._timeout_btn_widgets[name] = {
                "btn": btn, "inner": inner_btn,
                "name_lbl": name_lbl, "sub_lbl": sub_lbl}
            for w in (btn, inner_btn, name_lbl, sub_lbl):
                w.bind("<Button-1>", lambda e, n=name: self._apply_timeout_preset(n))

        # ── Data (backups + import/export) ────────────────────────────────────
        self._build_data_section(body)

        # ── Reflow on resize ──────────────────────────────────────────────────
        # The content frame's <Configure> can fire with stale widths during
        # initial layout on macOS. The Text widget itself gets accurate
        # window-driven resize events, so we watch that and read its width.
        scroll_text = sf._scroll_text
        # Expose the scroll widget so apply-handlers can snapshot its scroll
        # fraction before rebuild() nukes it.
        self._settings_scroll_text = scroll_text

        def _on_resize(e=None):
            # Use the Text widget's width — the one driven by the actual
            # window layout. Subtract padding for the sidebar scrollbar
            # area (~20px) and the body's own 40px horizontal padding.
            w = scroll_text.winfo_width()
            available = w - 80 - 20
            if available < 1:
                return
            _build_theme_grid(available)
            _build_font_grid(available)

        scroll_text.bind("<Configure>", _on_resize)
        # Initial draw deferred so the Text widget has real dimensions
        scroll_text.after(50, _on_resize)

        # Restore pre-rebuild scroll position, if any. Handlers that trigger
        # a full rebuild (theme / font / text size) stash the prior scroll
        # fraction on self; we consume and clear it here so subsequent
        # natural opens of Settings start at the top as usual.
        #
        # The key to avoiding a visible "jump" is to do everything
        # synchronously inside this call stack, before Tk's draw cycle gets
        # a chance to paint the rebuilt page at scroll position 0. That
        # means:
        #   1. update_idletasks() to force layout now
        #   2. run the resize reflow synchronously (give content real width)
        #   3. update_idletasks() again so widget heights are final
        #   4. yview_moveto() to the saved fraction
        # Tk then paints ONCE, already at the correct scroll position.
        pending = getattr(self, "_pending_settings_scroll", None)
        if pending is not None:
            self._pending_settings_scroll = None
            try:
                if scroll_text.winfo_exists():
                    scroll_text.update_idletasks()
                    _on_resize()
                    scroll_text.update_idletasks()
                    scroll_text.yview_moveto(pending)
            except tk.TclError:
                pass

    def _rebuild_preserving_settings_scroll(self):
        """Rebuild the app (needed for theme/font changes to take effect)
        while preserving the user's scroll position on the Settings page.

        Snapshots the scroll fraction before rebuild; _show_settings
        restores it synchronously after rebuild, before Tk's next paint.
        """
        text = getattr(self, "_settings_scroll_text", None)
        if text is not None:
            try:
                if text.winfo_exists():
                    top_frac, _ = text.yview()
                    self._pending_settings_scroll = top_frac
            except tk.TclError:
                pass
        self.rebuild()

    def _apply_theme(self, preset_name: str):
        theme.apply(preset_name, theme.ACTIVE_FONT, theme.ACTIVE_FONT_SIZE)
        self._rebuild_preserving_settings_scroll()

    def _apply_font(self, font_name: str):
        theme.apply(theme.ACTIVE_PRESET, font_name, theme.ACTIVE_FONT_SIZE)
        self._rebuild_preserving_settings_scroll()

    def _apply_font_size(self, size_name: str):
        theme.apply(theme.ACTIVE_PRESET, theme.ACTIVE_FONT, size_name)
        self._rebuild_preserving_settings_scroll()

    def _pick_default_save_folder(self):
        """Open a folder picker, set the result as the default save folder."""
        from tkinter import filedialog
        current = db.get_setting("default_save_folder", "")
        folder = filedialog.askdirectory(
            parent=self, title="Default save folder",
            initialdir=current if current else os.path.expanduser("~"))
        if folder:
            db.set_setting("default_save_folder", folder)
            if hasattr(self, "_save_folder_lbl") and self._save_folder_lbl.winfo_exists():
                self._save_folder_lbl.configure(text=folder)

    def _clear_default_save_folder(self):
        """Clear the explicit default and fall back to 'remember last used'."""
        db.set_setting("default_save_folder", "")
        if hasattr(self, "_save_folder_lbl") and self._save_folder_lbl.winfo_exists():
            self._save_folder_lbl.configure(text="Remember last used")

    def _apply_timeout_preset(self, name: str):
        """Store the selected preset and update the button highlights in
        place. We deliberately avoid calling rebuild() here because this
        control lives near the bottom of the Settings page and a full
        rebuild would snap the scroll position back to the top.
        """
        db.set_setting("default_optimizer_timeout", name)
        self._timeout_pref_var.set(name)
        # Restyle each button to reflect the new selection
        widgets = getattr(self, "_timeout_btn_widgets", None)
        if not widgets:
            return
        for preset_name, w in widgets.items():
            active = (preset_name == name)
            bg = theme.ACCENT if active else theme.PANEL
            name_fg = theme.ACCENT_TEXT if active else theme.TEXT
            sub_fg  = theme.ACCENT_TEXT if active else theme.TEXT_DIM
            try:
                w["btn"].configure(
                    bg=bg,
                    highlightbackground=theme.ACCENT if active else theme.BORDER,
                    highlightthickness=2 if active else 1)
                w["inner"].configure(bg=bg)
                w["name_lbl"].configure(bg=bg, fg=name_fg)
                w["sub_lbl"].configure(bg=bg, fg=sub_fg)
            except tk.TclError:
                # Widgets already destroyed (e.g., user navigated away)
                pass

    # ── Data section (backups + import/export) ────────────────────────────────

    def _build_data_section(self, body):
        """Renders the 'Data' section at the bottom of Settings. Contains
        manual/automatic backups (list + create/restore/delete) and
        import/export controls. All actions route through backup.py —
        this method is pure UI."""
        import backup

        section_label(body, "Data").pack(anchor="w", pady=(0, 6))
        tk.Label(body,
                 text="Back up your data periodically, or move it between "
                      "computers with Export / Import. Automatic backups are "
                      "created before risky actions (imports and restores).",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 anchor="w", justify="left", wraplength=600).pack(
                     anchor="w", pady=(0, 14), fill="x")

        # Action buttons row: Create backup, Export, Import
        actions = tk.Frame(body, bg=theme.BG)
        actions.pack(anchor="w", fill="x", pady=(0, 18))
        make_btn(actions, "📦 Create backup…",
                 self._create_backup_dialog, style="primary",
                 padx=14, pady=8).pack(side="left", padx=(0, 8))
        make_btn(actions, "↗ Export data…",
                 self._export_data_dialog, style="ghost",
                 padx=14, pady=8).pack(side="left", padx=(0, 8))
        make_btn(actions, "↘ Import data…",
                 self._import_data_dialog, style="ghost",
                 padx=14, pady=8).pack(side="left")

        # Saved backups list
        tk.Label(body, text="Saved backups",
                 font=theme.FONT_BOLD, bg=theme.BG, fg=theme.TEXT,
                 anchor="w").pack(anchor="w", pady=(4, 4))

        self._backup_list_frame = tk.Frame(body, bg=theme.BG)
        self._backup_list_frame.pack(anchor="w", fill="x", pady=(0, 8))
        self._render_backup_list()

    def _render_backup_list(self):
        """Populate the backup list container. Called initially and
        after any operation that changes the backup folder contents.

        Preserves the settings-page scroll position across the rebuild
        of the backup card list. The trick: we snapshot an ABSOLUTE
        pixel offset (viewport top Y relative to the content frame's
        origin), not a fraction. Fractions fail when content below the
        viewport is removed because "87% of shorter page" lands at a
        different absolute position than "87% of longer page." Pixel
        offsets stay meaningful — Tk automatically clamps to the new
        content bounds, so if the user was at the bottom before, they
        stay at the bottom after.
        """
        import backup

        frame = getattr(self, "_backup_list_frame", None)
        if frame is None or not frame.winfo_exists():
            return

        # Snapshot the viewport's absolute pixel offset. Computed as
        # (top_fraction × total_content_height) before rebuild.
        scroll_text = getattr(self, "_settings_scroll_text", None)
        pixel_offset = None
        if scroll_text is not None:
            try:
                if scroll_text.winfo_exists():
                    scroll_text.update_idletasks()
                    top_frac, _ = scroll_text.yview()
                    # The content frame lives inside the Text widget; its
                    # full height (winfo_height on the Text's one embedded
                    # child frame) is the total scrollable content height.
                    # Fall back to the Text's own bbox if that's unavailable.
                    content_h = 0
                    for name in scroll_text.window_names():
                        try:
                            w = scroll_text.nametowidget(name)
                            if w.winfo_exists():
                                content_h = max(content_h, w.winfo_height())
                        except (tk.TclError, KeyError):
                            pass
                    if content_h > 0:
                        pixel_offset = int(top_frac * content_h)
            except tk.TclError:
                pixel_offset = None

        for w in frame.winfo_children():
            w.destroy()

        try:
            entries = backup.list_backups()
        except Exception as e:
            tk.Label(frame, text=f"Could not read backups folder: {e}",
                     font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_MUTED,
                     anchor="w").pack(anchor="w")
        else:
            if not entries:
                tk.Label(frame,
                         text="No backups yet. Create one above, or import/restore "
                              "from an existing file to auto-generate your first one.",
                         font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_MUTED,
                         anchor="w", justify="left", wraplength=600).pack(
                             anchor="w", pady=(2, 0), fill="x")
            else:
                for e in entries:
                    self._render_backup_row(frame, e)

        # Restore the pixel offset as a fraction of the NEW content
        # height. Scheduled via after_idle so Tk has finished laying
        # out the new content and `winfo_height()` returns the
        # post-reflow size. If the offset is past the new end, Tk's
        # yview_moveto clamps automatically — that's why "scrolled to
        # the bottom" stays at the bottom even after the page shrinks.
        if pixel_offset is not None and scroll_text is not None:
            def _restore():
                try:
                    if not scroll_text.winfo_exists():
                        return
                    scroll_text.update_idletasks()
                    new_h = 0
                    for name in scroll_text.window_names():
                        try:
                            w = scroll_text.nametowidget(name)
                            if w.winfo_exists():
                                new_h = max(new_h, w.winfo_height())
                        except (tk.TclError, KeyError):
                            pass
                    if new_h > 0:
                        new_frac = min(1.0, pixel_offset / new_h)
                        scroll_text.yview_moveto(new_frac)
                except tk.TclError:
                    pass
            scroll_text.after_idle(_restore)

    def _render_backup_row(self, parent, entry: dict):
        """Render one backup card. Entry dict comes from list_backups()."""
        import backup

        card = tk.Frame(parent, bg=theme.PANEL,
                         highlightbackground=theme.BORDER,
                         highlightthickness=1)
        card.pack(fill="x", pady=(0, 6))
        inner = tk.Frame(card, bg=theme.PANEL, padx=14, pady=10)
        inner.pack(fill="x")

        # Left column: icon + description
        left = tk.Frame(inner, bg=theme.PANEL)
        left.pack(side="left", fill="x", expand=True)

        title_row = tk.Frame(left, bg=theme.PANEL)
        title_row.pack(anchor="w", fill="x")
        icon = "📦" if entry["type"] == "manual" else "🕐"
        label = entry["label"] if entry["label"] else (
            "Automatic backup" if entry["type"] == "auto" else "Backup")
        # Convert slug back to readable form (hyphens → spaces) for display
        display_label = label.replace("-", " ") if entry["label"] else label
        tk.Label(title_row, text=f"{icon}  {display_label}",
                 font=theme.FONT_BOLD, bg=theme.PANEL,
                 fg=theme.TEXT, anchor="w").pack(side="left")

        # Meta row: type · timestamp · size
        kind = "Manual" if entry["type"] == "manual" else "Automatic"
        when = backup.format_timestamp(entry.get("timestamp"))
        size = backup.format_size(entry.get("size_bytes", 0))
        meta = f"{kind}  ·  {when}  ·  {size}"
        tk.Label(left, text=meta,
                 font=theme.FONT_SMALL, bg=theme.PANEL,
                 fg=theme.TEXT_DIM, anchor="w").pack(anchor="w", pady=(2, 2))

        # Preview row: contents (classes/rounds/students) or error
        preview = entry.get("preview", {})
        if "error" in preview:
            preview_text = f"⚠ {preview['error']}"
            preview_fg = theme.TEXT_MUTED
        else:
            c = preview.get("classes", 0)
            r = preview.get("rounds", 0)
            s = preview.get("students", 0)
            preview_text = (f"{c} class{'es' if c != 1 else ''}  ·  "
                             f"{r} round{'s' if r != 1 else ''}  ·  "
                             f"{s} student{'s' if s != 1 else ''}")
            preview_fg = theme.TEXT_DIM
        tk.Label(left, text=preview_text,
                 font=theme.FONT_SMALL, bg=theme.PANEL,
                 fg=preview_fg, anchor="w").pack(anchor="w")

        # Right column: action buttons. Only enable Restore if the
        # preview succeeded — a broken backup shouldn't look restorable.
        right = tk.Frame(inner, bg=theme.PANEL)
        right.pack(side="right")
        can_restore = "error" not in preview
        if can_restore:
            make_btn(right, "↺ Restore",
                     lambda fn=entry["filename"], lbl=display_label:
                         self._restore_backup_dialog(fn, lbl),
                     style="ghost", padx=12, pady=6).pack(side="left", padx=(0, 6))
        make_btn(right, "🗑 Delete",
                 lambda fn=entry["filename"], lbl=display_label:
                     self._delete_backup_dialog(fn, lbl),
                 style="ghost", padx=12, pady=6).pack(side="left")

    def _create_backup_dialog(self):
        """Prompt for an optional label, then snapshot the live DB."""
        import backup
        from tkinter import simpledialog
        label = simpledialog.askstring(
            "Create Backup",
            "Name this backup (optional):",
            parent=self)
        # simpledialog returns None if cancelled — skip; empty string is
        # also fine, just means no label.
        if label is None:
            return
        try:
            path = backup.create_manual_backup(label or "")
        except Exception as e:
            messagebox.showerror("Backup Failed", str(e), parent=self)
            return
        self._render_backup_list()
        messagebox.showinfo(
            "Backup Created",
            f"Backup saved as:\n{path.name}",
            parent=self)

    def _restore_backup_dialog(self, filename: str, display_label: str):
        """Confirm and execute a restore from the named backup."""
        import backup
        proceed = messagebox.askyesno(
            "Restore from Backup?",
            f"Restore from “{display_label}”?\n\n"
            "This will replace all your current data with the contents "
            "of this backup.\n\n"
            "A backup of your current data will be created automatically "
            "first, so you can undo this if needed.",
            parent=self)
        if not proceed:
            return
        try:
            auto_path = backup.restore_from_backup(filename)
        except Exception as e:
            messagebox.showerror("Restore Failed", str(e), parent=self)
            return
        # After the DB has been replaced, rebuild the whole app so every
        # view re-queries fresh. rebuild() destroys all widgets (including
        # any open Toplevels) and re-creates the root UI from scratch.
        self._invalidate_cache("classes", "layouts")
        messagebox.showinfo(
            "Restore Complete",
            f"Your data has been restored.\n\n"
            f"Your previous data was automatically saved as:\n"
            f"{auto_path.name if auto_path else '(no prior data to back up)'}",
            parent=self)
        self._rebuild_preserving_settings_scroll()

    def _delete_backup_dialog(self, filename: str, display_label: str):
        """Confirm and delete a backup."""
        import backup
        proceed = messagebox.askyesno(
            "Delete Backup?",
            f"Delete “{display_label}”?\n\nThis cannot be undone.",
            parent=self)
        if not proceed:
            return
        try:
            backup.delete_backup(filename)
        except Exception as e:
            messagebox.showerror("Delete Failed", str(e), parent=self)
            return
        self._render_backup_list()

    def _export_data_dialog(self):
        """Save the live DB to a user-chosen path."""
        import backup
        from tkinter import filedialog
        from datetime import datetime
        default_name = f"SeatingChartManager_backup_{datetime.now().strftime('%Y-%m-%d')}.db"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export data",
            defaultextension=".db",
            initialfile=default_name,
            filetypes=[("Seating Chart backup", "*.db"), ("All files", "*.*")])
        if not path:
            return
        try:
            from pathlib import Path
            backup.export_to_path(Path(path))
        except Exception as e:
            messagebox.showerror("Export Failed", str(e), parent=self)
            return
        messagebox.showinfo(
            "Export Complete",
            f"Data exported to:\n{path}",
            parent=self)

    def _import_data_dialog(self):
        """Let the user pick a .db file, validate it, and import it."""
        import backup
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self,
            title="Import data",
            filetypes=[("Seating Chart backup", "*.db"), ("All files", "*.*")])
        if not path:
            return
        # Same replace-everything confirmation as restore. Wording is
        # slightly different because the source is an external file the
        # user just picked, not a named saved backup.
        proceed = messagebox.askyesno(
            "Import Data?",
            "Replace your current data with the contents of the selected "
            "file?\n\n"
            "A backup of your current data will be created automatically "
            "first, so you can undo this if needed.",
            parent=self)
        if not proceed:
            return
        try:
            from pathlib import Path
            auto_path = backup.import_from_path(Path(path))
        except Exception as e:
            messagebox.showerror("Import Failed", str(e), parent=self)
            return
        self._invalidate_cache("classes", "layouts")
        messagebox.showinfo(
            "Import Complete",
            f"Data imported from:\n{path}\n\n"
            f"Your previous data was automatically saved as:\n"
            f"{auto_path.name if auto_path else '(no prior data to back up)'}",
            parent=self)
        self._rebuild_preserving_settings_scroll()

    # ── Classes ───────────────────────────────────────────────────────────────

    def _show_classes(self):
        # Toggle state affects what _fetch_classes_data returns. Since
        # cached data was fetched under the old toggle value, invalidate
        # whenever we can't guarantee the cache matches the current flag.
        # Simpler: always re-fetch. The fetch is cheap.
        self._show_spinner()
        data = self._fetch_classes_data()
        self._set_cached("classes", data)
        self._clear()
        self._build_classes_ui(data)
        self._force_paint()

    def _build_classes_ui(self, classes: list):
        self._page_header("Classes", "+ New Class", self._new_class_dialog)

        # View-mode toggle strip: Active (default) vs Show archived. Also
        # shows a count so the teacher knows how many archived classes
        # exist without flipping the toggle blindly.
        show_archived = bool(getattr(self, "_show_archived_classes", False))
        # Count archived classes (used for the toggle label)
        try:
            all_cls = db.get_all_classes(include_archived=True)
            archived_count = sum(1 for c in all_cls
                                   if c.get("archived"))
        except Exception:
            archived_count = 0

        toggle_row = tk.Frame(self.content, bg=theme.BG, padx=28)
        toggle_row.pack(fill="x", pady=(4, 0))
        if show_archived:
            lbl = "← Back to active classes"
        else:
            plural = "es" if archived_count != 1 else ""
            lbl = f"Show archived ({archived_count} class{plural})"
        # Only show the toggle if there's something useful to reveal, OR
        # we're currently viewing archived (so they can get back).
        if show_archived or archived_count > 0:
            make_btn(toggle_row, lbl,
                     command=self._toggle_show_archived,
                     style="ghost", padx=12, pady=5).pack(side="left")

        if not classes:
            self._stop_spinner()
            if show_archived:
                msg = "No archived classes."
            else:
                msg = "No classes yet — click '+ New Class' to create one."
            tk.Label(self.content,
                     text=msg,
                     font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=40)
            return
        sf = self._scrollable(self.content)
        self._render_cards(classes, self._class_card, sf)

    def _toggle_show_archived(self):
        self._show_archived_classes = not bool(
            getattr(self, "_show_archived_classes", False))
        self._invalidate_cache("classes")
        self._show_classes()

    def _class_card(self, parent, cls):
        is_archived = bool(cls.get("archived"))
        # Archived cards use muted styling so they're visually distinct
        # from active classes.
        panel_bg = theme.GHOST_BG if is_archived else theme.PANEL
        title_fg = theme.TEXT_MUTED if is_archived else theme.TEXT

        card = tk.Frame(parent, bg=panel_bg,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        card.pack(fill="x", padx=28, pady=5)
        inner = tk.Frame(card, bg=panel_bg, padx=18, pady=14)
        inner.pack(fill="x")

        info = tk.Frame(inner, bg=panel_bg)
        info.pack(side="left", fill="x", expand=True)
        title_text = cls["name"] + ("   (archived)" if is_archived else "")
        tk.Label(info, text=title_text, font=theme.FONT_BOLD,
                 bg=panel_bg, fg=title_fg).pack(anchor="w")
        dim_label(info, f"Layout: {cls['layout_name'] or 'None assigned'}",
                  bg=panel_bg).pack(anchor="w")
        students = cls.get("_students") if cls.get("_students") is not None else db.get_students_for_class(cls["id"])
        rounds   = cls.get("_rounds")   if cls.get("_rounds")   is not None else db.get_rounds_for_class(cls["id"])
        dim_label(info, f"{len(students)} students · {len(rounds)} rounds",
                  bg=panel_bg).pack(anchor="w")

        btns = tk.Frame(inner, bg=panel_bg)
        btns.pack(side="right")
        make_btn(btns, "Open",
                 lambda c=cls: self._open_class(c["id"]),
                 style="primary").pack(side="left", padx=3)
        if is_archived:
            # Archived: offer Unarchive (soft restore) and Delete (permanent).
            # Delete lives here, behind the archive wall, so one errant
            # click on an active class doesn't destroy a year of data.
            make_btn(btns, "Unarchive",
                     lambda c=cls: self._unarchive_class(c["id"]),
                     style="ghost").pack(side="left", padx=3)
            make_btn(btns, "Delete",
                     lambda c=cls: self._delete_class(c["id"]),
                     style="danger").pack(side="left", padx=3)
        else:
            # Active: normal editing actions + Archive (replaces direct
            # Delete to prevent accidental destruction).
            make_btn(btns, "Edit",
                     lambda c=cls: self._edit_class_dialog(c["id"]),
                     style="ghost").pack(side="left", padx=3)
            make_btn(btns, "Duplicate",
                     lambda c=cls: self._duplicate_class(c["id"]),
                     style="ghost").pack(side="left", padx=3)
            make_btn(btns, "Archive",
                     lambda c=cls: self._archive_class(c["id"]),
                     style="ghost").pack(side="left", padx=3)

    def _archive_class(self, class_id):
        """Archive an active class — hides it from the default classes
        list. All data is preserved; the class can be unarchived later."""
        cls = db.get_class(class_id)
        if not cls:
            return
        if messagebox.askyesno(
                "Archive Class",
                f"Archive '{cls['name']}'?\n\n"
                f"The class and all its data will be preserved, but it "
                f"will be hidden from your active classes list. You can "
                f"restore it later via 'Show archived'.",
                parent=self):
            db.set_class_archived(class_id, True)
            self._invalidate_cache("classes")
            self._show_classes()

    def _unarchive_class(self, class_id):
        """Restore an archived class to active status."""
        db.set_class_archived(class_id, False)
        self._invalidate_cache("classes")
        self._show_classes()

    def _new_class_dialog(self):
        dlg = _ClassDialog(self, "New Class")
        self.wait_window(dlg)
        if dlg.result:
            try:
                db.create_class(*dlg.result)
                # A new class references a layout, changing that
                # layout's in-use status (and thus its deletability).
                self._invalidate_cache("classes", "layouts")
                self._show_classes()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _edit_class_dialog(self, class_id):
        cls = db.get_class(class_id)
        if not cls:
            return
        dlg = _ClassDialog(self, "Edit Class", existing=cls)
        self.wait_window(dlg)
        if dlg.result:
            try:
                # Edit dialog doesn't expose the mode picker — only name
                # and layout. Unpack just those two.
                name, layout_id, _mode = dlg.result
                db.update_class(class_id, name, layout_id)
                # Changing a class's layout changes in-use status on
                # both the old and new layout.
                self._invalidate_cache("classes", "layouts")
                self._show_classes()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _delete_class(self, class_id):
        cls = db.get_class(class_id)
        if not cls:
            return
        if messagebox.askyesno(
                "Delete Class",
                f"Permanently delete '{cls['name']}' and all its data?\n\n"
                f"This removes the class, all its students, all its rounds, "
                f"and all its pair history. This cannot be undone.\n\n"
                f"If you want to keep the data but hide the class, use "
                f"'Unarchive' and then 'Archive' instead.",
                parent=self):
            db.delete_class(class_id)
            # Deleting a class cascades its rounds + assignments, which
            # may unlock a layout (has_rounds False) or free a layout
            # from being in-use. Invalidate layouts cache so the Layouts
            # page re-reads lock state.
            self._invalidate_cache("classes", "layouts")
            self._show_classes()

    def _duplicate_class(self, class_id):
        src = db.get_class(class_id)
        if not src:
            return
        # Prompt for a new name. Default: "X (Copy)"
        new_name = simpledialog.askstring(
            "Duplicate Class",
            f"Name for the new class\n\n"
            f"Copies the roster, pins, never-together rules, and layout.\n"
            f"Starts with fresh pair history (no rounds).",
            initialvalue=f"{src['name']} (Copy)",
            parent=self
        )
        if not new_name or not new_name.strip():
            return
        try:
            db.duplicate_class(class_id, new_name.strip())
            # The copy references the source's layout, changing its
            # in-use status.
            self._invalidate_cache("classes", "layouts")
            self._show_classes()
        except Exception as e:
            messagebox.showerror("Duplicate Failed", str(e), parent=self)

    # ── Class detail ──────────────────────────────────────────────────────────

    @staticmethod
    def _saturation_descriptor(pct: float) -> str | None:
        """Return a short, warmly-framed label for how 'mixed' the class is,
        given the current pair-coverage percentage. The intent: reassure
        teachers that diminishing returns at high coverage are a success
        state, not a failure. A teacher seeing '0 new pairings last round'
        alongside 'Richly saturated' reads it as 'done', not 'stuck'.

        Returns None for the 100% case — the main coverage headline already
        has a ✓ treatment there, and the descriptor would be redundant.
        """
        if pct >= 100:
            return None
        if pct >= 96:
            return "Richly saturated"
        if pct >= 90:
            return "Highly saturated"
        if pct >= 75:
            return "Well saturated"
        if pct >= 50:
            return "Lightly saturated"
        if pct >= 25:
            return "Building up"
        return "Just getting started"

    def _set_name_display(self, class_id: int, mode: str, tab_parent):
        """Change how student names render in this class. Takes effect
        immediately across every display surface (roster, room view,
        PDFs, dialogs, stats) by rebuilding the roster tab. Other pages
        pick up the change through their normal fetch paths."""
        try:
            db.set_class_name_display(class_id, mode)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)
            return
        # Cache invalidation: the classes page caches student summaries,
        # but those use raw names. The roster view re-fetches via
        # _refresh_roster, which is the surface that actually renders
        # names.
        self._invalidate_cache("classes")
        self._refresh_roster(class_id, tab_parent)

    def _switch_mode_dialog(self, class_id: int, cls: dict):
        """Confirm and switch a class's seating mode.

        Per your design: changing the mode only affects NEW rounds. Existing
        rounds keep their stamped mode — they'll still render the way they
        were generated. Pair history is shared across modes, so no data is
        lost or duplicated on a switch.
        """
        current_mode = cls.get("seating_mode", "per_table")
        new_mode = "per_seat" if current_mode == "per_table" else "per_table"
        current_label = "Per-seat (Advanced)" if current_mode == "per_seat" else "Per-table (Basic)"
        new_label     = "Per-seat (Advanced)" if new_mode     == "per_seat" else "Per-table (Basic)"

        if new_mode == "per_seat":
            explainer = (
                "Advanced mode assigns students to specific seats within each "
                "table. Use this when seat position matters (group work, labs). "
                "The Room View and PDF export will show individual seat positions.")
        else:
            explainer = (
                "Basic mode assigns students to tables only — seat positions "
                "within a table don't matter. Faster to solve, simpler to view, "
                "and sufficient for most classroom rotations.")

        msg = (
            f"Currently: {current_label}\n"
            f"Switch to: {new_label}\n\n"
            f"{explainer}\n\n"
            f"Existing rounds will stay as they were generated. Only new "
            f"rounds will use the switched mode. Your pair history is preserved "
            f"across the switch.\n\n"
            f"Student pins are also preserved. Seat-level pins reactivate "
            f"automatically if you later switch back to per-seat mode.\n\n"
            f"Continue?")
        if not messagebox.askyesno("Switch Seating Mode", msg, parent=self):
            return
        try:
            db.set_class_seating_mode(class_id, new_mode)
            # Validate/clean any inconsistent seat pins (e.g., seat pin
            # whose underlying table no longer matches pinned_table_id).
            # The schema's ON DELETE SET NULL handles deleted seats; this
            # cleans up the cross-consistency case. Safe to call in any
            # mode — it only touches genuinely broken records.
            try:
                db.reconcile_pins_for_layout(class_id)
            except Exception:
                pass
            self._invalidate_cache("classes")
            # Redraw the class page so the badge updates. Preserve the tab
            # the user was on — bouncing back to Roster after a mode switch
            # is jarring, especially since the switch was triggered from
            # the header and doesn't conceptually reset navigation.
            current_tab = getattr(self, "_active_class_tab", "roster")
            self._open_class(class_id, initial_tab=current_tab)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _open_class(self, class_id, initial_tab: str = "roster"):
        self._clear()
        cls = db.get_class(class_id)
        if not cls:
            return

        # Header row 1: breadcrumb + class name.
        hdr = tk.Frame(self.content, bg=theme.BG, padx=28)
        hdr.pack(fill="x", pady=(14, 2))
        make_btn(hdr, "← Classes", self._show_classes,
                 style="link", padx=0, pady=0).pack(side="left")
        tk.Label(hdr, text="  /  ", font=theme.FONT_BODY,
                 bg=theme.BG, fg=theme.TEXT_MUTED).pack(side="left")
        tk.Label(hdr, text=cls["name"], font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(side="left")

        # Header row 2: layout + mode badge + switcher. Separated from
        # row 1 so the right-aligned mode group never gets clipped by
        # long class names or wider fonts (e.g. the monospace themes).
        meta = tk.Frame(self.content, bg=theme.BG, padx=28)
        meta.pack(fill="x", pady=(0, 6))
        tk.Label(meta, text=f"[{cls['layout_name'] or 'No layout'}]",
                 font=theme.FONT_BODY, bg=theme.BG,
                 fg=theme.TEXT_DIM).pack(side="left")

        # Seating mode badge + switcher (right side of meta row)
        mode = cls.get("seating_mode", "per_table")
        mode_label = "Per-seat (Advanced)" if mode == "per_seat" else "Per-table (Basic)"
        mode_frame = tk.Frame(meta, bg=theme.BG)
        mode_frame.pack(side="right")
        tk.Label(mode_frame, text=f"Mode: {mode_label}",
                 font=theme.FONT_SMALL, bg=theme.BG,
                 fg=theme.TEXT_DIM).pack(side="left", padx=(0, 8))
        make_btn(mode_frame, "Switch…",
                 command=lambda: self._switch_mode_dialog(class_id, cls),
                 style="link", padx=0, pady=0).pack(side="left")

        tab_bar = tk.Frame(self.content, bg=theme.BG)
        tab_bar.pack(fill="x", padx=28, pady=(8, 0))
        self._tab_btns    = {}
        self._tab_content = tk.Frame(self.content, bg=theme.BG)
        self._tab_content.pack(fill="both", expand=True)

        def switch_tab(key):
            # Remember the active tab so operations that have to rebuild the
            # page (e.g., mode switch) can restore it instead of snapping
            # back to Roster.
            self._active_class_tab = key
            for k, b in self._tab_btns.items():
                active = (k == key)
                b.configure(bg=theme.ACCENT if active else theme.BG,
                            fg=theme.ACCENT_TEXT if active else theme.TEXT_DIM)
                b._btn_bg    = theme.ACCENT if active else theme.BG
                b._btn_hover = theme.ACCENT_DARK if active else theme.SEP
            for w in self._tab_content.winfo_children():
                w.destroy()
            {"roster":  lambda: self._roster_tab(self._tab_content, class_id),
             "rounds":  lambda: self._rounds_tab(self._tab_content, class_id, cls),
             "history": lambda: self._history_tab(self._tab_content, class_id)}[key]()
            self._force_paint()

        for label, key in [("Roster", "roster"),
                            ("Seating Chart Rounds", "rounds"),
                            ("Pair History", "history")]:
            b = make_btn(tab_bar, f"  {label}  ",
                         command=lambda k=key: switch_tab(k),
                         style="tab", padx=16, pady=8)
            b.pack(side="left")
            self._tab_btns[key] = b

        tk.Frame(self.content, bg=theme.SEP, height=1).pack(fill="x", padx=28)
        # Honour caller-requested initial tab; fall back to roster if an
        # unrecognised key slips through.
        first_tab = initial_tab if initial_tab in self._tab_btns else "roster"
        switch_tab(first_tab)

    # ── Roster tab ────────────────────────────────────────────────────────────

    def _roster_tab(self, parent, class_id):
        top = tk.Frame(parent, bg=theme.BG, pady=14, padx=28)
        top.pack(fill="x")
        section_label(top, "Students").pack(side="left")
        btn_row = tk.Frame(top, bg=theme.BG)
        btn_row.pack(side="right")
        make_btn(btn_row, "🚫 Pair Rules",
                 lambda: self._constraints_dialog(class_id, parent),
                 style="ghost").pack(side="left", padx=(0, 6))
        make_btn(btn_row, "📋 Bulk Import",
                 lambda: self._bulk_import_dialog(class_id, parent),
                 style="ghost").pack(side="left", padx=(0, 6))
        make_btn(btn_row, "+ Add Student",
                 lambda: self._add_student_dialog(class_id, parent),
                 style="primary").pack(side="left")

        # Name-display picker strip. Affects every surface that shows
        # student names for this class (roster, room view, PDF, stats,
        # dialogs). Stored value lives on classes.name_display.
        cls_for_mode = db.get_class(class_id) or {}
        current_mode = cls_for_mode.get("name_display", "full")
        display_strip = tk.Frame(parent, bg=theme.BG, padx=28)
        display_strip.pack(fill="x", pady=(0, 6))
        tk.Label(display_strip, text="Show names as:",
                 font=theme.FONT_SMALL, bg=theme.BG,
                 fg=theme.TEXT_DIM).pack(side="left", padx=(0, 10))
        mode_labels = [
            ("full",          "Full"),
            ("first_initial", "First + L."),
            ("first_only",    "First only"),
        ]
        for mode_key, label in mode_labels:
            active = (mode_key == current_mode)
            b = make_btn(
                display_strip, label,
                command=lambda mk=mode_key: self._set_name_display(
                    class_id, mk, parent),
                style="primary" if active else "ghost",
                padx=10, pady=4)
            b.pack(side="left", padx=3)

        students = db.get_students_for_class(class_id)
        if not students:
            tk.Label(parent, text="No students yet — add one above, or use Bulk Import to paste a list.",
                     font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=30)
            return

        # ── Search bar ────────────────────────────────────────────────────────
        search_row = tk.Frame(parent, bg=theme.BG, padx=28)
        search_row.pack(fill="x", pady=(0, 6))
        tk.Label(search_row, text="🔍", font=theme.FONT_BODY,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 6))
        search_var = tk.StringVar()
        search_entry = styled_entry(search_row, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True)
        count_lbl = tk.Label(search_row, text="", font=theme.FONT_SMALL,
                             bg=theme.BG, fg=theme.TEXT_MUTED)
        count_lbl.pack(side="right", padx=(8, 0))

        # ── Floating action bar (above the tree) ──────────────────────────────
        # Always visible so users don't have to scroll to find actions.
        # Operates on the currently selected student. Buttons disable when
        # nothing is selected.
        action_bar = tk.Frame(parent, bg=theme.PANEL, padx=16, pady=10,
                              highlightbackground=theme.BORDER, highlightthickness=1)
        action_bar.pack(fill="x", padx=28, pady=(4, 6))

        selected_lbl = tk.Label(action_bar, text="No student selected — click a row below to edit",
                                font=theme.FONT_BODY, bg=theme.PANEL, fg=theme.TEXT_DIM)
        selected_lbl.pack(side="left")

        action_btns = tk.Frame(action_bar, bg=theme.PANEL)
        action_btns.pack(side="right")
        pin_btn = make_btn(action_btns, "📌 Pin",
                           lambda: None, style="ghost", padx=12, pady=5)
        pin_btn.pack(side="left", padx=3)
        # unpin_btn is packed/unpacked dynamically based on whether the
        # selected student currently has a pin. When a pin exists, both
        # 'Edit pin' and 'Remove pin' show so teachers can remove without
        # opening the dialog.
        unpin_btn = make_btn(action_btns, "📌 Remove pin",
                              lambda: None, style="ghost", padx=12, pady=5)
        # NOT packed yet — pack is handled by _set_buttons_enabled
        toggle_btn = make_btn(action_btns, "Deactivate",
                              lambda: None, style="ghost", padx=12, pady=5)
        toggle_btn.pack(side="left", padx=3)
        rename_btn = make_btn(action_btns, "Rename",
                              lambda: None, style="ghost", padx=12, pady=5)
        rename_btn.pack(side="left", padx=3)
        remove_btn = make_btn(action_btns, "✕ Remove",
                              lambda: None, style="danger", padx=12, pady=5)
        remove_btn.pack(side="left", padx=3)

        # Disabled visual state for the action buttons
        def _set_buttons_enabled(enabled: bool, selected_student: dict = None):
            if not enabled or not selected_student:
                for b in (pin_btn, toggle_btn, rename_btn, remove_btn):
                    b.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED, cursor="")
                    b._btn_bg    = theme.GHOST_BG
                    b._btn_hover = theme.GHOST_BG
                    b._command   = lambda: None
                # No selection: hide unpin_btn entirely
                try:
                    unpin_btn.pack_forget()
                except tk.TclError:
                    pass
                selected_lbl.configure(
                    text="No student selected — click a row below to edit",
                    fg=theme.TEXT_DIM)
                return

            s = selected_student
            is_active = bool(s["active"])
            sid       = s["id"]
            name      = s["name"]                    # stored (for handlers)
            display   = s.get("display") or s["name"]  # rendered
            pin_tid   = s.get("pinned_table_id")
            status    = "Active" if is_active else "Inactive"
            selected_lbl.configure(text=f"Selected: {display}   ({status})",
                                   fg=theme.TEXT)

            # Pin button: "Edit pin" when already pinned (opens dialog for
            # changes), "Pin" when not (opens dialog to create).
            pin_text = "📌 Edit pin" if pin_tid else "📌 Pin"
            pin_btn.configure(text=pin_text, bg=theme.BG, fg=theme.TEXT,
                              cursor="hand2")
            pin_btn._btn_bg    = theme.BG
            pin_btn._btn_hover = theme.SEP
            pin_btn._command   = (
                lambda: self._do_pin_student(sid, name, pin_tid, class_id, parent))

            # Unpin button: visible only when a pin exists. Direct removal,
            # no dialog detour.
            if pin_tid:
                # Pack right after pin_btn so it sits visually adjacent
                unpin_btn.pack(side="left", padx=3, after=pin_btn)
                unpin_btn.configure(bg=theme.BG, fg=theme.TEXT, cursor="hand2")
                unpin_btn._btn_bg    = theme.BG
                unpin_btn._btn_hover = theme.SEP
                unpin_btn._command   = (
                    lambda: self._do_remove_pin(sid, class_id, parent))
            else:
                try:
                    unpin_btn.pack_forget()
                except tk.TclError:
                    pass

            toggle_text = "Deactivate" if is_active else "Activate"
            toggle_btn.configure(text=toggle_text, bg=theme.BG, fg=theme.TEXT,
                                 cursor="hand2")
            toggle_btn._btn_bg    = theme.BG
            toggle_btn._btn_hover = theme.SEP
            toggle_btn._command   = (
                lambda: self._do_toggle_student(sid, name, not is_active,
                                                class_id, parent))

            rename_btn.configure(bg=theme.BG, fg=theme.TEXT, cursor="hand2")
            rename_btn._btn_bg    = theme.BG
            rename_btn._btn_hover = theme.SEP
            rename_btn._command   = (
                lambda: self._do_rename_student(sid, name, is_active,
                                                class_id, parent))

            remove_btn.configure(bg=theme.DANGER, fg=theme.ACCENT_TEXT,
                                 cursor="hand2")
            remove_btn._btn_bg    = theme.DANGER
            remove_btn._btn_hover = theme.DANGER_DARK
            remove_btn._command   = (
                lambda: self._do_remove_student(sid, name, class_id, parent))

        _set_buttons_enabled(False)

        # ── Treeview (native scroll works perfectly on macOS trackpad) ────────
        tree_container = tk.Frame(parent, bg=theme.BG, padx=28, pady=4)
        # fill="x" (not "both") so the container only takes the vertical space
        # the tree requests. The tree's height attribute controls how tall
        # it actually is; container hugs it instead of stretching to fill.
        tree_container.pack(fill="x", anchor="n")

        # Preload table labels + seat-number lookup for pin display.
        # We assign seat a 1-based index per table, stable by seat id, so
        # we can say "Seat 2" instead of the raw DB id.
        cls = db.get_class(class_id)
        table_label_by_id: dict = {}
        seat_number_by_id:  dict = {}
        if cls and cls.get("layout_id"):
            for t in db.get_tables_for_layout(cls["layout_id"]):
                table_label_by_id[t["id"]] = t["label"]
            # Group seats by table, then number them per-table by id order
            seats = db.get_seats_for_layout(cls["layout_id"])
            from collections import defaultdict
            by_tbl: dict = defaultdict(list)
            for s in seats:
                by_tbl[s["table_id"]].append(s)
            for tid, lst in by_tbl.items():
                for idx, s in enumerate(sorted(lst, key=lambda x: x["id"])):
                    seat_number_by_id[s["id"]] = idx + 1
        # Per-class mode influences how pins are displayed: in per-table
        # mode we show only the table (even for students with dormant seat
        # pins), matching user expectation that seats don't matter in this
        # mode. In per-seat mode we show seat detail when available.
        class_mode = (cls or {}).get("seating_mode", "per_table")

        cols = ("name", "status", "pinned")
        # Scale tree height to number of students (capped at 20 rows max).
        tree_height = min(20, max(4, len(students)))
        tree = ttk.Treeview(tree_container, columns=cols, show="headings",
                            height=tree_height, selectmode="browse")
        tree.column("name",   width=280, anchor="w")
        tree.column("status", width=100, anchor="center")
        tree.column("pinned", width=140, anchor="center")
        tree.tag_configure("inactive", foreground=theme.TEXT_MUTED)
        tree.pack(fill="x")

        # Sort state survives across roster rebuilds (e.g., after edits)
        # by being stored on the app instance keyed by class_id.
        if not hasattr(self, "_roster_sort"):
            self._roster_sort: dict = {}
        # Current sort is (col_key, ascending_bool) or None for default.
        current_sort = self._roster_sort.get(class_id)

        def _sort_key(s: dict, col: str):
            """Return a tuple usable as a sort key for a student by column.
            Designed so sort_by='pinned' clusters pinned students together
            (sorted by table + seat), with unpinned at the end."""
            disp = (s.get("display") or s.get("name") or "").lower()
            if col == "name":
                return disp
            if col == "status":
                # Active first in ascending order
                return (0 if s.get("active") else 1, disp)
            if col == "pinned":
                pin_tid = s.get("pinned_table_id")
                pin_sid = s.get("pinned_seat_id")
                if pin_tid is None:
                    # Unpinned sorts last. Secondary by display so ties are
                    # still alphabetical.
                    return (1, "", 0, disp)
                tbl = table_label_by_id.get(pin_tid, "")
                seat_n = seat_number_by_id.get(pin_sid, 0) if pin_sid else 0
                return (0, tbl.lower(), seat_n, disp)
            return disp

        def _update_heading_arrows():
            """Update column headings to show sort direction glyph."""
            labels = {"name": "Name", "status": "Status", "pinned": "Pinned To"}
            for col, default_label in labels.items():
                if current_sort and current_sort[0] == col:
                    arrow = "  ↑" if current_sort[1] else "  ↓"
                    tree.heading(col, text=default_label + arrow)
                else:
                    tree.heading(col, text=default_label)

        def _on_heading_click(col: str):
            """Cycle: click a column → sort asc. Click again → sort desc.
            Click a different column → sort it asc."""
            nonlocal current_sort
            if current_sort and current_sort[0] == col:
                # Toggle direction
                current_sort = (col, not current_sort[1])
            else:
                current_sort = (col, True)
            self._roster_sort[class_id] = current_sort
            _update_heading_arrows()
            _populate()

        tree.heading("name",   text="Name",
                     command=lambda: _on_heading_click("name"))
        tree.heading("status", text="Status",
                     command=lambda: _on_heading_click("status"))
        tree.heading("pinned", text="Pinned To",
                     command=lambda: _on_heading_click("pinned"))
        _update_heading_arrows()

        # Map of tree iid → student dict for O(1) lookup on selection
        student_by_iid: dict = {}

        def _populate(*_):
            student_by_iid.clear()
            for row in tree.get_children():
                tree.delete(row)
            q = search_var.get().strip().lower()
            # Filter on the display form (what the user sees). Falling
            # back to the stored name keeps legacy rows searchable even
            # if display ever ends up blank.
            def _match(s):
                label = (s.get("display") or s["name"]).lower()
                return not q or q in label
            filtered = [s for s in students if _match(s)]
            if current_sort:
                col, asc = current_sort
                filtered.sort(key=lambda s: _sort_key(s, col),
                               reverse=not asc)
            shown = 0
            for s in filtered:
                iid = str(s["id"])
                pin_tid  = s.get("pinned_table_id")
                pin_sid  = s.get("pinned_seat_id")
                if pin_tid is None:
                    pin_label = "—"
                else:
                    tbl_name = table_label_by_id.get(pin_tid, "?")
                    if class_mode == "per_seat" and pin_sid is not None:
                        seat_n = seat_number_by_id.get(pin_sid)
                        if seat_n is not None:
                            pin_label = f"📌 {tbl_name}, Seat {seat_n}"
                        else:
                            pin_label = f"📌 {tbl_name}"
                    else:
                        pin_label = f"📌 {tbl_name}"
                display = s.get("display") or s["name"]
                tree.insert("", "end", iid=iid,
                            values=(display,
                                    "Active" if s["active"] else "Inactive",
                                    pin_label),
                            tags=() if s["active"] else ("inactive",))
                student_by_iid[iid] = s
                shown += 1
            if q:
                count_lbl.configure(text=f"{shown} of {len(students)} matching")
            else:
                count_lbl.configure(text=f"{len(students)} students")
            # Clear selection state when list is refreshed (e.g. search changes)
            _set_buttons_enabled(False)

        def _on_select(*_):
            sel = tree.selection()
            if not sel:
                _set_buttons_enabled(False)
                return
            s = student_by_iid.get(sel[0])
            _set_buttons_enabled(bool(s), s)

        tree.bind("<<TreeviewSelect>>", _on_select)
        search_var.trace_add("write", _populate)
        _populate()

    def _refresh_roster(self, class_id: int, tab_parent):
        """Rebuild the roster tab from scratch."""
        self._invalidate_cache("classes")
        for w in tab_parent.winfo_children():
            w.destroy()
        self._roster_tab(tab_parent, class_id)
        self._force_paint()

    def _do_toggle_student(self, sid: int, name: str, new_active: bool,
                            class_id: int, tab_parent):
        db.update_student(sid, name, new_active)
        self._refresh_roster(class_id, tab_parent)

    def _do_rename_student(self, sid: int, current_name: str, active: bool,
                            class_id: int, tab_parent):
        dlg = _StudentNameDialog(self, "Rename Student",
                                   "New name",
                                   initial=current_name,
                                   ok_label="Save")
        self.wait_window(dlg)
        if dlg.result:
            db.update_student(sid, dlg.result["display"], active,
                                first_name=dlg.result["first_name"],
                                last_name=dlg.result["last_name"])
            self._refresh_roster(class_id, tab_parent)

    def _do_remove_student(self, sid: int, name: str, class_id: int, tab_parent):
        if messagebox.askyesno("Remove Student",
                               f"Remove '{name}'? Their assignment history will also be deleted."):
            db.delete_student(sid)
            self._refresh_roster(class_id, tab_parent)

    def _do_pin_student(self, sid: int, name: str, current_pin: int | None,
                         class_id: int, tab_parent):
        cls = db.get_class(class_id)
        if not cls or not cls.get("layout_id"):
            messagebox.showinfo("No Layout",
                                "Assign a layout to this class first, then you can pin students.",
                                parent=self)
            return
        # Fetch the student's full pin state (table + seat) so the dialog
        # shows accurate current state in per-seat mode.
        student = next((s for s in db.get_students_for_class(class_id,
                                                                active_only=False)
                         if s["id"] == sid), None)
        current_seat = student.get("pinned_seat_id") if student else None
        # Use the display form in the dialog title so the user sees the
        # name in their chosen format ('Alice S.' / 'Alice').
        display_name = (student.get("display") if student else None) or name
        mode = cls.get("seating_mode", "per_table")
        dlg = _PinStudentDialog(self, display_name, cls["layout_id"],
                                  current_pin, current_seat, mode,
                                  class_id=class_id, student_id=sid)
        self.wait_window(dlg)
        if dlg.saved:
            db.set_student_pin_full(sid, dlg.new_pin, dlg.new_seat_pin)
            self._refresh_roster(class_id, tab_parent)

    def _do_remove_pin(self, sid: int, class_id: int, tab_parent):
        """Direct removal of a student's pin — no dialog. Clears both
        the table pin and the seat pin (set_student_pin(None) handles
        both in one call)."""
        try:
            db.set_student_pin(sid, None)
            self._refresh_roster(class_id, tab_parent)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _constraints_dialog(self, class_id: int, tab_parent):
        dlg = _ConstraintsDialog(self, class_id)
        self.wait_window(dlg)
        if dlg.changed:
            self._refresh_roster(class_id, tab_parent)

    def _add_student_dialog(self, class_id, parent):
        dlg = _StudentNameDialog(self, "Add Student",
                                   "Student name",
                                   ok_label="Add")
        self.wait_window(dlg)
        if dlg.result:
            db.add_student(class_id, dlg.result["display"],
                             first_name=dlg.result["first_name"],
                             last_name=dlg.result["last_name"])
            self._refresh_roster(class_id, parent)

    def _bulk_import_dialog(self, class_id: int, parent):
        dlg = _BulkImportDialog(self, class_id)
        self.wait_window(dlg)
        if dlg.imported_count > 0:
            self._refresh_roster(class_id, parent)



    # ── Rounds tab ────────────────────────────────────────────────────────────

    def _rounds_tab(self, parent, class_id, cls):
        top = tk.Frame(parent, bg=theme.BG, pady=14, padx=28)
        top.pack(fill="x")
        section_label(top, "Seating Chart Rounds").pack(side="left")
        make_btn(top, "⚙  Generate New Round",
                 lambda: self._generate_round_dialog(class_id, cls, parent),
                 style="primary").pack(side="right")

        rounds = db.get_rounds_for_class(class_id)
        if not rounds:
            tk.Label(parent, text="No rounds yet — generate the first seating arrangement.",
                     font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=30)
            return

        # L1 stats strip — visible summary of pairing coverage.
        # Wrap in try/except so a stats computation failure doesn't prevent
        # the round cards from rendering.
        try:
            self._build_stats_strip(parent, class_id, cls)
        except Exception as e:
            import traceback
            traceback.print_exc()
            tk.Label(parent,
                     text=f"(Stats unavailable: {e})",
                     font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_MUTED).pack(anchor="w", padx=28, pady=(0, 8))

        sf = self._scrollable(parent)
        for rnd in rounds:
            self._round_card(sf, rnd, class_id, cls, parent)

    def _build_stats_strip(self, parent, class_id, cls):
        """
        Inline stats strip shown above the round cards.
        Gives a quick glance at coverage + most-repeated pair, and a button
        to open the full stats dashboard.
        """
        stats = db.get_pair_stats(class_id)
        strip = tk.Frame(parent, bg=theme.PANEL,
                          highlightbackground=theme.BORDER, highlightthickness=1)
        strip.pack(fill="x", padx=28, pady=(0, 10))
        inner = tk.Frame(strip, bg=theme.PANEL, padx=18, pady=10)
        inner.pack(fill="x")

        # Left cluster: coverage + most repeated
        left = tk.Frame(inner, bg=theme.PANEL)
        left.pack(side="left", fill="x", expand=True)

        total  = stats["total_possible_pairs"]
        unique = stats["unique_pairs_seen"]
        pct    = (unique / total * 100) if total else 0

        if total == 0:
            headline = "📊  Not enough students to compute coverage"
        elif unique == total:
            headline = f"📊  ✓ Every pair has sat together  ({unique}/{total})"
        else:
            headline = f"📊  {unique}/{total} unique pairings  ({pct:.0f}% coverage)"
        tk.Label(left, text=headline, font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT, anchor="w").pack(anchor="w")

        # Sub-line: most repeated + saturation descriptor + momentum.
        # The descriptor does the emotional work: paired with the numeric
        # "0 new pairings last round", it reframes apparent stagnation as
        # success at high coverage ("Richly saturated. 0 new pairings last
        # round" reads as 'done', not 'stuck'). At low coverage, the same
        # descriptor ("Just getting started. 5 new pairings last round")
        # tells the teacher the rotation is in the early-growth phase.
        subparts = []
        mr = stats["most_repeated"]
        if mr and mr["count"] > 1:
            subparts.append(f"Most repeated: {mr['name_a']} + {mr['name_b']} ({mr['count']}×)")

        # Saturation label — only if we have enough students for it to be
        # meaningful. Suppressed at 100% (the headline already celebrates).
        if total > 0:
            descriptor = self._saturation_descriptor(pct)
            if descriptor:
                subparts.append(descriptor)

        rounds_for_class = db.get_rounds_for_class(class_id)
        if rounds_for_class:
            last_rid = rounds_for_class[0]["id"]
            try:
                new_pairs = db.count_new_pairs_in_round(class_id, last_rid)
            except Exception:
                new_pairs = None
            if new_pairs is not None:
                plural = "s" if new_pairs != 1 else ""
                subparts.append(f"{new_pairs} new pairing{plural} last round")

        if subparts:
            tk.Label(left, text="   ·   ".join(subparts),
                     font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.TEXT_DIM,
                     anchor="w").pack(anchor="w", pady=(2, 0))

        # Right: full stats button
        make_btn(inner, "📊 Full Stats",
                 lambda: self._open_stats_window(class_id, cls),
                 style="ghost", padx=12, pady=6).pack(side="right")

    def _open_stats_window(self, class_id, cls):
        _StatsWindow(self, class_id, cls)

    def _round_card(self, parent, rnd, class_id, cls, tab_parent):
        card = tk.Frame(parent, bg=theme.PANEL,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        card.pack(fill="x", padx=28, pady=5)
        inner = tk.Frame(card, bg=theme.PANEL, padx=18, pady=12)
        inner.pack(fill="x")

        info = tk.Frame(inner, bg=theme.PANEL)
        info.pack(side="left", fill="x", expand=True)

        # Label row: title + small rename icon. Either is clickable to rename.
        label_row = tk.Frame(info, bg=theme.PANEL)
        label_row.pack(anchor="w")
        label_lbl = tk.Label(label_row, text=rnd["label"], font=theme.FONT_BOLD,
                              bg=theme.PANEL, fg=theme.TEXT, cursor="hand2")
        label_lbl.pack(side="left")
        rename_icon = tk.Label(label_row, text="  ✎", font=theme.FONT_SMALL,
                                bg=theme.PANEL, fg=theme.TEXT_MUTED,
                                cursor="hand2")
        rename_icon.pack(side="left")
        def _rename_this_round(_e=None, r=rnd, cid=class_id, c=cls, tp=tab_parent):
            self._rename_round_dialog(r, cid, c, tp)
        label_lbl.bind("<Button-1>", _rename_this_round)
        rename_icon.bind("<Button-1>", _rename_this_round)

        score = rnd.get("repeat_score", 0)
        dt    = rnd["created_at"][:16].replace("T", " ")
        # Compute true table-repeat count for this round (excluding itself
        # from its own history comparison). One DB query per card — cheap
        # for realistic round lists.
        try:
            round_assigns = db.get_assignments_for_round(rnd["id"])
            assigns_tuples = [(a["student_id"], a.get("seat_id"), a["table_id"])
                               for a in round_assigns]
            true_repeats = db.count_repeat_pairs(class_id, assigns_tuples,
                                                   exclude_round_id=rnd["id"])
        except Exception:
            true_repeats = None

        # Primary line: the human-meaningful metric if available, else pairing score
        if true_repeats is None:
            primary = f"Pairing score: {score}"
            primary_clr = theme.ACCENT
        elif true_repeats == 0:
            primary = "✓  No repeated tablemates"
            primary_clr = theme.SUCCESS
        else:
            primary = (f"{true_repeats} repeated tablemate "
                       f"pair{'s' if true_repeats != 1 else ''}")
            primary_clr = theme.ACCENT if true_repeats <= 6 else theme.DANGER

        tk.Label(info, text=f"{dt}   ·   {primary}",
                 font=theme.FONT_SMALL, bg=theme.PANEL, fg=primary_clr).pack(anchor="w")
        if true_repeats is not None:
            tk.Label(info, text=f"Pairing score: {score}",
                     font=theme.FONT_SMALL, bg=theme.PANEL,
                     fg=theme.TEXT_DIM).pack(anchor="w")
        if rnd.get("edited"):
            tk.Label(info, text="✎ Edited manually after generation",
                     font=theme.FONT_SMALL, bg=theme.PANEL,
                     fg=theme.TEXT_DIM).pack(anchor="w")
        if rnd["excluded_tables"]:
            tk.Label(info, text=f"⚠  {len(rnd['excluded_tables'])} table(s) excluded this round",
                     font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.ACCENT).pack(anchor="w")
        notes = (rnd.get("notes") or "").strip()
        if notes:
            # Truncate long notes to one line on the card
            preview = notes.replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "…"
            tk.Label(info, text=f"📝  {preview}", font=theme.FONT_SMALL,
                     bg=theme.PANEL, fg=theme.TEXT_DIM).pack(anchor="w", pady=(2, 0))

        btns = tk.Frame(inner, bg=theme.PANEL)
        btns.pack(side="right")
        make_btn(btns, "View",
                 lambda r=rnd: self._view_round(r, cls), style="ghost").pack(side="left", padx=3)
        make_btn(btns, "📝",
                 lambda r=rnd: self._quick_edit_notes(r, class_id, cls, tab_parent),
                 style="ghost").pack(side="left", padx=3)
        make_btn(btns, "⬇ Export PDF",
                 lambda r=rnd: self._export_pdf_dialog(r, cls),
                 style="primary").pack(side="left", padx=3)
        make_btn(btns, "Delete",
                 lambda r=rnd: self._delete_round(r["id"], class_id, cls, tab_parent),
                 style="danger").pack(side="left", padx=3)

    def _quick_edit_notes(self, rnd: dict, class_id: int, cls: dict, tab_parent):
        """Open notes editor from round card. Refreshes rounds tab on save."""
        dlg = _NotesEditorDialog(self, rnd)
        self.wait_window(dlg)
        if dlg.saved:
            rnd["notes"] = dlg.new_notes
            self._invalidate_cache("classes")
            # Rebuild rounds tab so the card's note preview updates
            if tab_parent is not None:
                for w in tab_parent.winfo_children():
                    w.destroy()
                self._rounds_tab(tab_parent, class_id, cls)

    def _rename_round_dialog(self, rnd: dict, class_id: int, cls: dict, tab_parent):
        """Prompt for a new label and update it."""
        new_label = simpledialog.askstring(
            "Rename Round",
            "New label for this round:",
            initialvalue=rnd["label"],
            parent=self
        )
        if not new_label or not new_label.strip():
            return
        new_label = new_label.strip()
        if new_label == rnd["label"]:
            return
        db.update_round_label(rnd["id"], new_label)
        rnd["label"] = new_label
        self._invalidate_cache("classes")
        if tab_parent is not None:
            for w in tab_parent.winfo_children():
                w.destroy()
            self._rounds_tab(tab_parent, class_id, cls)

    def _generate_round_dialog(self, class_id, cls, parent):
        cls_fresh = db.get_class(class_id)
        if not cls_fresh or not cls_fresh["layout_id"]:
            messagebox.showwarning("No Layout",
                                   "This class has no layout assigned.\n"
                                   "Edit the class to assign a layout first.")
            return
        tables   = db.get_tables_for_layout(cls_fresh["layout_id"])
        students = db.get_students_for_class(class_id, active_only=True)
        if not tables:
            messagebox.showwarning("No Tables", "The assigned layout has no tables defined.")
            return
        if not students:
            messagebox.showwarning("No Students", "No active students in this class.")
            return
        dlg = _GenerateRoundDialog(self, students, tables, class_id, cls_fresh)
        self.wait_window(dlg)
        if dlg.committed:
            # A new round was saved — if this was the first round for
            # this layout, the layout has just transitioned to locked.
            # Invalidate layouts cache so the Layouts page reflects it.
            self._invalidate_cache("classes", "layouts")
            for w in parent.winfo_children():
                w.destroy()
            self._rounds_tab(parent, class_id, cls_fresh)

    def _view_round(self, rnd, cls):
        cls_fresh = db.get_class(cls["id"])
        if not cls_fresh:
            return
        assignments_raw = db.get_assignments_for_round(rnd["id"])
        win = tk.Toplevel(self)
        win.title(f"{cls_fresh['name']} — {rnd['label']}")
        win.geometry("800x600")
        win.configure(bg=theme.BG)

        hdr = tk.Frame(win, bg=theme.BG, padx=24, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text=rnd["label"], font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
        score = rnd.get("repeat_score", 0)
        # Compute true table-repeat count for this round (user-meaningful).
        # Exclude this round from its own history comparison.
        try:
            round_assigns = db.get_assignments_for_round(rnd["id"])
            # Convert to (student_id, seat_id, table_id) tuples expected by helper
            assigns_tuples = [(a["student_id"],
                                a.get("seat_id"),
                                a["table_id"]) for a in round_assigns]
            true_repeats = db.count_repeat_pairs(class_id, assigns_tuples,
                                                   exclude_round_id=rnd["id"])
        except Exception:
            true_repeats = None

        if true_repeats is None:
            headline = f"Pairing score: {score}"
            sc = theme.ACCENT
        elif true_repeats == 0:
            headline = "✓  No repeated tablemates"
            sc = theme.SUCCESS
        elif true_repeats <= 6:
            headline = f"{true_repeats} repeated tablemate pair{'s' if true_repeats != 1 else ''}"
            sc = theme.ACCENT
        else:
            headline = f"{true_repeats} repeated tablemate pair{'s' if true_repeats != 1 else ''}"
            sc = theme.DANGER
        score_row = tk.Frame(hdr, bg=theme.BG)
        score_row.pack(anchor="w")
        tk.Label(score_row, text=headline, font=theme.FONT_BOLD,
                 bg=theme.BG, fg=sc).pack(side="left")
        if rnd.get("edited"):
            tk.Label(score_row, text="   ✎ Edited", font=theme.FONT_SMALL,
                     bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left")
        if true_repeats is not None:
            tk.Label(hdr, text=f"Pairing score: {score}  (optimizer's weighted score)",
                     font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM).pack(anchor="w")
        tk.Label(hdr, text=rnd["created_at"][:16].replace("T", " "),
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_MUTED).pack(anchor="w")

        # Create notes_frame first so lambdas below can reference it
        tk.Frame(win, bg=theme.SEP, height=1).pack(fill="x", padx=24)
        notes_frame = tk.Frame(win, bg=theme.BG, padx=24)
        notes_frame.pack(fill="x", pady=(10, 0))

        btn_bar = tk.Frame(hdr, bg=theme.BG)
        btn_bar.pack(side="right")
        make_btn(btn_bar, "✎ Edit Assignments",
                 lambda: self._edit_assignments_dialog(rnd, cls_fresh, win),
                 style="ghost").pack(side="left", padx=(0, 6))
        make_btn(btn_bar, "📝 Edit Notes",
                 lambda: self._edit_notes_dialog(rnd, notes_frame, tab_parent=None),
                 style="ghost").pack(side="left", padx=(0, 6))
        make_btn(btn_bar, "⬇ Export PDF",
                 lambda: self._export_pdf_dialog(rnd, cls_fresh),
                 style="primary").pack(side="left", padx=4)

        self._render_notes_display(notes_frame, rnd)

        by_table_id:  dict = defaultdict(list)
        by_table_lbl: dict = defaultdict(list)   # kept for legacy/export paths
        by_seat_id:   dict = {}
        table_label_for_id: dict = {}
        for a in assignments_raw:
            disp = a.get("student_display") or a["student_name"]
            by_table_id[a["table_id"]].append(disp)
            by_table_lbl[a["table_label"]].append(disp)
            table_label_for_id[a["table_id"]] = a["table_label"]
            if a.get("seat_id") is not None:
                by_seat_id[a["seat_id"]] = disp

        # Build the dict that the list view will render. Keyed by table_id
        # with a display label that disambiguates duplicates.
        by_table_display: dict = {}
        # Count how many tables share each label, and assign suffixes if >1
        label_counts = defaultdict(int)
        for tid, lbl in table_label_for_id.items():
            label_counts[lbl] += 1
        label_suffix_counter = defaultdict(int)
        for tid in sorted(table_label_for_id.keys()):
            lbl = table_label_for_id[tid]
            if label_counts[lbl] > 1:
                label_suffix_counter[lbl] += 1
                display_label = f"{lbl} #{label_suffix_counter[lbl]}"
            else:
                display_label = lbl
            by_table_display[tid] = (display_label, by_table_id[tid])

        tab_bar     = tk.Frame(win, bg=theme.BG)
        tab_bar.pack(fill="x", padx=24, pady=(8, 0))
        tab_btns    = {}
        tab_content = tk.Frame(win, bg=theme.BG)
        tab_content.pack(fill="both", expand=True)

        def switch(key):
            for k, b in tab_btns.items():
                active = (k == key)
                b.configure(bg=theme.ACCENT if active else theme.BG,
                            fg=theme.ACCENT_TEXT if active else theme.TEXT_DIM)
                b._btn_bg    = theme.ACCENT if active else theme.BG
                b._btn_hover = theme.ACCENT_DARK if active else theme.SEP
            for w in tab_content.winfo_children():
                w.destroy()
            if key == "list":
                self._view_round_list(tab_content, by_table_display)
            else:
                self._view_round_room(tab_content, cls_fresh, by_seat_id,
                                       rnd=rnd, by_table_id=by_table_id)
            win.update_idletasks()
            win.update()

        for label, key in [("  Table List  ", "list"), ("  Room View  ", "room")]:
            b = make_btn(tab_bar, label, command=lambda k=key: switch(k),
                         style="tab", padx=14, pady=7)
            b.pack(side="left")
            tab_btns[key] = b

        tk.Frame(win, bg=theme.SEP, height=1).pack(fill="x", padx=24)
        # Settle window geometry before first switch so the reflow grid
        # has a real width to measure against.
        win.update_idletasks()
        win.update()
        switch("list")

    def _render_notes_display(self, parent, rnd: dict):
        """Render the notes content inside a container frame. Clears first."""
        for w in parent.winfo_children():
            w.destroy()
        notes = (rnd.get("notes") or "").strip()
        if notes:
            tk.Label(parent, text="Notes", font=theme.FONT_BOLD,
                     bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
            tk.Label(parent, text=notes, font=theme.FONT_BODY,
                     bg=theme.BG, fg=theme.TEXT_DIM, justify="left",
                     wraplength=720).pack(anchor="w", pady=(2, 6))
        else:
            tk.Label(parent, text="No notes for this round. Click 📝 Edit Notes to add one.",
                     font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_MUTED).pack(anchor="w")

    def _edit_notes_dialog(self, rnd: dict, notes_frame, tab_parent=None):
        """Open the notes editor. Refreshes notes_frame after save."""
        dlg = _NotesEditorDialog(self, rnd)
        self.wait_window(dlg)
        if dlg.saved:
            # Update the round dict in-place so subsequent refreshes see it
            rnd["notes"] = dlg.new_notes
            self._render_notes_display(notes_frame, rnd)
            # Invalidate classes cache so round cards re-render with new notes
            self._invalidate_cache("classes")

    def _edit_assignments_dialog(self, rnd: dict, cls: dict, viewer_win):
        """
        Open the right assignment editor based on the round's seating_mode.
        After a successful save, updates rnd in-place (edited flag,
        repeat_score) and closes+reopens the viewer to reflect the changes.

        Mode selection uses the ROUND's stamped mode, not the class's
        current mode — so editing an old per-seat round still opens the
        per-seat editor even if the class has since switched to per-table.
        """
        round_mode = rnd.get("seating_mode", "per_seat")
        if round_mode == "per_table":
            dlg = _AssignmentEditorDialogTableMode(self, rnd, cls)
        else:
            dlg = _AssignmentEditorDialog(self, rnd, cls)
        self.wait_window(dlg)
        if dlg.saved:
            # Invalidate cache so stats and round cards reflect the change
            self._invalidate_cache("classes")
            # Update the passed-in rnd dict so callers see the new state
            rnd["edited"] = 1
            rnd["repeat_score"] = dlg.new_repeat_score
            # Close and reopen the viewer to rebuild with fresh data
            try:
                viewer_win.destroy()
            except tk.TclError:
                pass
            # Re-fetch rnd from DB to get authoritative state
            fresh_rounds = db.get_rounds_for_class(cls["id"])
            fresh_rnd = next((r for r in fresh_rounds if r["id"] == rnd["id"]), rnd)
            self._view_round(fresh_rnd, cls)

    def _view_round_list(self, parent, by_table_display: dict):
        """by_table_display: {table_id: (display_label, [student_name, ...])}"""
        self._render_table_list(parent, by_table_display)

    def _render_table_list(self, parent, by_table_display: dict):
        """
        Responsive reflow grid of fixed-width table cards.
        Accepts {table_id: (display_label, [names])} so tables with the same
        label still render as separate cards.
        """
        CARD_W = 220
        GAP    = 12

        container = tk.Frame(parent, bg=theme.BG, padx=16, pady=12)
        container.pack(fill="both", expand=True, anchor="nw")

        # Sort by display label for stable, alphabetical layout
        entries = sorted(by_table_display.items(), key=lambda kv: kv[1][0])

        state = {"cols": 0}

        def _build(cols: int):
            # Safety: this can fire from a late <Configure> event after the
            # user has switched tabs or closed the round viewer, leaving
            # `container` destroyed. Bail rather than crash.
            try:
                if not container.winfo_exists():
                    return
            except tk.TclError:
                return
            if cols == state["cols"]:
                return
            state["cols"] = cols
            for w in container.winfo_children():
                w.destroy()
            for idx, (tid, (display_label, names)) in enumerate(entries):
                r, c   = divmod(idx, cols)
                bg_c, fg_c = theme.TABLE_COLORS[idx % len(theme.TABLE_COLORS)]
                cell = tk.Frame(container, bg=bg_c, width=CARD_W,
                                highlightbackground=fg_c, highlightthickness=1)
                cell.grid(row=r, column=c, padx=GAP//2, pady=GAP//2, sticky="nw")
                cell.grid_propagate(False)
                inner = tk.Frame(cell, bg=bg_c, padx=14, pady=10)
                inner.pack(fill="both", expand=True)
                tk.Label(inner, text=f"🪑  {display_label}", font=theme.FONT_BOLD,
                         bg=bg_c, fg=fg_c, anchor="w").pack(fill="x", pady=(0, 4))
                for name in sorted(names):
                    tk.Label(inner, text=name, font=theme.FONT_BODY,
                             bg=bg_c, fg=theme.TEXT, anchor="w").pack(fill="x")
                cell.update_idletasks()
                cell.configure(height=inner.winfo_reqheight())

        def _on_resize(e):
            available = e.width - 32
            if available < 1:
                return
            cols = max(1, (available + GAP) // (CARD_W + GAP))
            _build(cols)

        # Bind on `container` rather than `parent`. When the tab content is
        # destroyed (user switches to Room View / closes the round viewer),
        # container's bindings die with it. Binding on `parent` previously
        # caused the callback to survive and touch zombie widgets, producing
        # "bad window path name" TclErrors.
        container.bind("<Configure>", _on_resize)
        # Force layout and do initial draw synchronously. parent has real
        # geometry by now because the caller already called win.update() on
        # the containing window before switching to this tab.
        parent.update_idletasks()
        initial_w = parent.winfo_width()
        if initial_w > 1:
            cols = max(1, (initial_w - 32 + GAP) // (CARD_W + GAP))
            _build(cols)
        else:
            # Fallback for the rare case parent still has no geometry:
            # build with a sensible default; <Configure> will refine later.
            _build(max(1, (800 - 32 + GAP) // (CARD_W + GAP)))

    def _view_round_room(self, parent, cls_fresh: dict, by_seat_id: dict,
                           rnd: dict | None = None,
                           by_table_id: dict | None = None):
        if not cls_fresh.get("layout_id"):
            tk.Label(parent, text="No layout assigned to this class.",
                     font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=30)
            return
        cf = tk.Frame(parent, bg=theme.CANVAS_BG)
        cf.pack(fill="both", expand=True, padx=24, pady=12)

        # Per-table rounds use view_roster mode (names stacked inside tables).
        # Per-seat rounds use view mode (names in individual seat circles).
        # Default to per_seat for rounds without a stamped mode (old data).
        round_mode = (rnd or {}).get("seating_mode", "per_seat")
        if round_mode == "per_table":
            room = rc.RoomCanvas(cf, layout_id=cls_fresh["layout_id"],
                                  mode="view_roster",
                                  table_roster=dict(by_table_id or {}))
        else:
            room = rc.RoomCanvas(cf, layout_id=cls_fresh["layout_id"],
                                  mode="view", assignments=dict(by_seat_id))
        room.pack(fill="both", expand=True)
        room.after(50, room.load)

    def _delete_round(self, round_id, class_id, cls, parent):
        if messagebox.askyesno("Delete Round",
                               "Delete this round? It will be removed from pair history."):
            db.delete_round(round_id)
            # Deleting a round may unlock its class's layout (if this was
            # the last remaining round for that layout). Invalidate
            # layouts cache so the lock state re-reads.
            self._invalidate_cache("classes", "layouts")
            for w in parent.winfo_children():
                w.destroy()
            self._rounds_tab(parent, class_id, cls)
            self._force_paint()

    def _export_pdf_dialog(self, rnd: dict, cls: dict):
        cls_fresh = db.get_class(cls["id"]) if "layout_name" not in cls else cls
        if not cls_fresh or not cls_fresh.get("layout_id"):
            messagebox.showwarning("No Layout",
                                   "This class has no layout assigned — cannot export.")
            return
        dlg = _ExportDialog(self, rnd, cls_fresh)
        self.wait_window(dlg)

    # ── Pair History tab ──────────────────────────────────────────────────────

    def _history_tab(self, parent, class_id):
        top = tk.Frame(parent, bg=theme.BG, pady=14, padx=28)
        top.pack(fill="x")
        section_label(top, "Pair History").pack(anchor="w")
        dim_label(top, "Times each pair of students has shared a table.").pack(anchor="w")

        history    = db.get_pair_history(class_id)
        id_to_name = {s["id"]: (s.get("display") or s["name"])
                       for s in db.get_students_for_class(class_id)}

        if not history:
            tk.Label(parent, text="No rounds recorded yet.",
                     font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=30)
            return

        pairs = sorted(
            [((id_to_name.get(a, f"#{a}"), id_to_name.get(b, f"#{b}")), c)
             for (a, b), c in history.items()],
            key=lambda x: -x[1])

        # ── Search bar ────────────────────────────────────────────────────────
        search_row = tk.Frame(parent, bg=theme.BG, padx=28)
        search_row.pack(fill="x", pady=(8, 4))
        tk.Label(search_row, text="🔍", font=theme.FONT_BODY,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 6))
        search_var = tk.StringVar()
        search_entry = styled_entry(search_row, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True)
        count_lbl = tk.Label(search_row, text="", font=theme.FONT_SMALL,
                             bg=theme.BG, fg=theme.TEXT_MUTED)
        count_lbl.pack(side="right", padx=(8, 0))
        dim_label(parent, "    Search matches either student in the pair.",
                  bg=theme.BG).pack(anchor="w", padx=28)

        cols = ("pair", "count")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        tree.heading("pair",  text="Student Pair")
        tree.heading("count", text="Times Together")
        tree.column("pair",  width=420, anchor="w")
        tree.column("count", width=140, anchor="center")
        tree.pack(fill="both", expand=True, padx=28, pady=8)

        def _refresh_tree(*_):
            q = search_var.get().strip().lower()
            for row in tree.get_children():
                tree.delete(row)
            shown = 0
            for (names, count) in pairs:
                if q and q not in names[0].lower() and q not in names[1].lower():
                    continue
                tree.insert("", "end", values=(f"{names[0]}  &  {names[1]}", count))
                shown += 1
            if q:
                count_lbl.configure(text=f"{shown} of {len(pairs)} matching")
            else:
                count_lbl.configure(text=f"{len(pairs)} pairs")

        search_var.trace_add("write", _refresh_tree)
        _refresh_tree()

    # ── Layouts ───────────────────────────────────────────────────────────────

    def _show_layouts(self):
        cached = self._get_cached("layouts")
        if cached is not None:
            self._clear()
            self._build_layouts_ui(cached)
            self._force_paint()
            return
        self._show_spinner()
        data = self._fetch_layouts_data()
        self._set_cached("layouts", data)
        self._clear()
        self._build_layouts_ui(data)
        self._force_paint()

    def _build_layouts_ui(self, layouts: list):
        self._page_header("Room Layouts", "+ New Layout", self._new_layout_dialog)
        if not layouts:
            self._stop_spinner()
            tk.Label(self.content,
                     text="No layouts yet — click '+ New Layout' to create one.",
                     font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT_DIM).pack(pady=40)
            return
        sf = self._scrollable(self.content)
        self._render_cards(layouts, self._layout_card, sf)

    def _layout_card(self, parent, layout):
        # Use pre-fetched data if available, otherwise query
        tables      = layout.get("_tables") or db.get_tables_for_layout(layout["id"])
        locked      = layout.get("_locked", db.layout_has_rounds(layout["id"]))
        total_seats = sum(t["capacity"] for t in tables)

        card = tk.Frame(parent, bg=theme.PANEL,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        card.pack(fill="x", padx=28, pady=5)
        inner = tk.Frame(card, bg=theme.PANEL, padx=18, pady=14)
        inner.pack(fill="x")

        info = tk.Frame(inner, bg=theme.PANEL)
        info.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(info, bg=theme.PANEL)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=layout["name"], font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT).pack(side="left")
        if locked:
            tk.Label(name_row, text="  🔒 locked", font=theme.FONT_SMALL,
                     bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left")
        dim_label(info, f"{len(tables)} tables · {total_seats} total seats",
                  bg=theme.PANEL).pack(anchor="w")

        btns = tk.Frame(inner, bg=theme.PANEL)
        btns.pack(side="right")
        if locked:
            make_btn(btns, "View",
                     lambda l=layout: self._open_layout_editor(l["id"], read_only=True),
                     style="ghost").pack(side="left", padx=3)
        else:
            make_btn(btns, "Edit",
                     lambda l=layout: self._open_layout_editor(l["id"]),
                     style="primary").pack(side="left", padx=3)
        make_btn(btns, "Duplicate",
                 lambda l=layout: self._duplicate_layout(l["id"]),
                 style="ghost").pack(side="left", padx=3)
        if not locked and not layout.get("_in_use", db.is_layout_in_use(layout["id"])):
            make_btn(btns, "Delete",
                     lambda l=layout: self._delete_layout(l["id"]),
                     style="danger").pack(side="left", padx=3)

    def _new_layout_dialog(self):
        name = simpledialog.askstring("New Layout", "Layout name:", parent=self)
        if name and name.strip():
            try:
                lid = db.create_layout(name.strip())
                self._invalidate_cache("layouts", "classes")
                self._open_layout_editor(lid)
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _duplicate_layout(self, layout_id):
        layout = db.get_layout(layout_id)
        new_name = simpledialog.askstring("Duplicate Layout", "Name for duplicate:",
                                          initialvalue=f"{layout['name']} (copy)",
                                          parent=self)
        if new_name and new_name.strip():
            try:
                db.duplicate_layout(layout_id, new_name.strip())
                self._invalidate_cache("layouts")
                self._show_layouts()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _delete_layout(self, layout_id):
        layout = db.get_layout(layout_id)
        if messagebox.askyesno("Delete Layout", f"Delete '{layout['name']}'?"):
            db.delete_layout(layout_id)
            self._invalidate_cache("layouts")
            self._show_layouts()

    def _open_layout_editor(self, layout_id, read_only=False):
        win = _LayoutEditorWindow(self, layout_id, read_only=read_only)
        self.wait_window(win)
        # Always invalidate layouts (positions may have changed).
        # Only invalidate classes if structural changes happened (tracked by the window).
        self._invalidate_cache("layouts")
        if getattr(win, "structural_change", False):
            self._invalidate_cache("classes")
        self._show_layouts()


# ── Actions Panel ─────────────────────────────────────────────────────────────

class _ActionsPanel(tk.Frame):
    """Selection-aware right sidebar inside the layout editor.

    Holds a reference to the parent `_LayoutEditorWindow` so it can call the
    existing context-action methods (_ctx_rotate, _ctx_delete_table, etc.)
    without duplicating logic. Rebuilds its button set whenever the selection
    changes.

    Selection is a list of (kind, id) tuples coming either from the canvas
    (via on_selection_change callback) or from the List View's Treeview
    selection. Both surfaces share this panel.
    """

    PANEL_WIDTH = 220

    def __init__(self, parent, editor):
        super().__init__(parent,
                         bg=theme.PANEL,
                         highlightbackground=theme.BORDER,
                         highlightthickness=1)
        self.editor    = editor
        self.selection = []

        scroll_container, self._scroll_text = make_text_scroll_container(
            self, bg=theme.PANEL, padx=0, pady=0,
            width_px=self.PANEL_WIDTH)
        scroll_container.pack(fill="both", expand=True)
        self._scroll_text.configure(bg=theme.PANEL)
        self._scroll_text.bind("<Key>", lambda e: "break")
        self._scroll_text.bind("<Button-2>", lambda e: "break")

        self._content = tk.Frame(self._scroll_text, bg=theme.PANEL)
        self._scroll_text.window_create("end", window=self._content, stretch=1)
        self._scroll_text.insert("end", "\n")

        self._build_empty()

    # ── External API ──────────────────────────────────────────────────────────

    def set_selection(self, selection: list):
        """selection: list of (kind, id) tuples. Rebuilds the panel contents."""
        self.selection = list(selection)
        # Destroy previous content children (inside self._content), not the
        # outer panel structure.
        for w in self._content.winfo_children():
            w.destroy()
        if not self.selection:
            self._build_empty()
        else:
            tables = [eid for (k, eid) in self.selection if k == "table"]
            seats  = [eid for (k, eid) in self.selection if k == "seat"]
            if tables and seats:
                sys.stderr.write(f"[actions-panel]   → mixed ({len(tables)} tbl, {len(seats)} seat)\n")
                self._build_mixed(tables, seats)
            elif tables and len(tables) == 1:
                self._build_single_table(tables[0])
            elif tables and len(tables) > 1:
                self._build_multi_tables(tables)
            elif seats and len(seats) == 1:
                self._build_single_seat(seats[0])
            else:
                self._build_multi_seats(seats)

    # ── View builders ─────────────────────────────────────────────────────────

    def _header(self, text: str):
        lbl = tk.Label(self._content, text=text, font=theme.FONT_BOLD,
                        bg=theme.PANEL, fg=theme.TEXT,
                        padx=14, pady=12, anchor="w")
        lbl.pack(fill="x")
        tk.Frame(self._content, bg=theme.SEP, height=1).pack(fill="x", padx=14)

    def _subtext(self, text: str):
        lbl = tk.Label(self._content, text=text, font=theme.FONT_SMALL,
                        bg=theme.PANEL, fg=theme.TEXT_DIM,
                        padx=14, pady=6, anchor="w",
                        wraplength=self.PANEL_WIDTH - 28, justify="left")
        lbl.pack(fill="x")

    def _action_btn(self, text: str, command, style: str = "ghost",
                    danger: bool = False):
        btn_frame = tk.Frame(self._content, bg=theme.PANEL, padx=14, pady=3)
        btn_frame.pack(fill="x")
        style_use = "danger" if danger else style
        make_btn(btn_frame, text, command, style=style_use,
                 padx=12, pady=7).pack(fill="x")

    def _spacer(self, pady: int = 8):
        tk.Frame(self._content, bg=theme.PANEL, height=pady).pack(fill="x")

    def _build_empty(self):
        if self.editor.read_only:
            self._header("Actions")
            self._subtext("This layout is read-only.")
            return
        self._header("Actions")
        self._action_btn("+ Add Table", self.editor._add_table_dialog,
                          style="primary")
        self._spacer(12)
        self._subtext(
            "Click a table or seat to edit it. "
            "Cmd/Shift-click to add to selection. "
            "Drag on empty canvas to box-select.")

    def _build_single_table(self, table_id: int):
        t = next((x for x in db.get_tables_for_layout(self.editor.layout_id)
                   if x["id"] == table_id), None)
        if t is None:
            self._build_empty()
            return
        self._header(t.get("label") or "Table")
        shape_name = "Round" if t.get("shape") == "round" else "Rectangle"
        decor_txt  = "  (decorative)" if t.get("decorative") else ""
        cap_txt    = "" if t.get("decorative") else f"  ·  {t.get('capacity', 0)} seats"
        self._subtext(f"{shape_name}{cap_txt}{decor_txt}")

        if self.editor.read_only:
            return

        self._action_btn("Rename…",
                          lambda tid=table_id: self._rename_table(tid))
        self._action_btn("Resize…",
                          lambda tid=table_id: self._resize_table(tid))
        self._spacer(6)
        self._action_btn("Rotate 15°",
                          lambda tid=table_id: self.editor._ctx_rotate(tid, 15))
        self._action_btn("Rotate 90°",
                          lambda tid=table_id: self.editor._ctx_rotate(tid, 90))
        self._action_btn("Reset rotation",
                          lambda tid=table_id: self.editor._ctx_set_rotation(tid, 0))
        self._spacer(6)
        other_shape = "Round" if t.get("shape") == "rect" else "Rectangle"
        self._action_btn(f"Change to {other_shape}",
                          lambda tid=table_id: self.editor._ctx_toggle_shape(tid))
        if t.get("decorative"):
            self._action_btn("Make non-decorative",
                              lambda tid=table_id: self.editor._ctx_toggle_decorative(tid))
        else:
            self._action_btn("Mark as decorative",
                              lambda tid=table_id: self.editor._ctx_toggle_decorative(tid))
        self._action_btn("Add seat",
                          lambda tid=table_id: self._add_seat_at_center(tid))
        self._spacer(10)
        self._action_btn("Duplicate table",
                          lambda tid=table_id: self.editor._ctx_duplicate_table(tid))
        self._action_btn("Delete table",
                          lambda tid=table_id: self.editor._ctx_delete_table(tid),
                          danger=True)

    def _build_multi_tables(self, table_ids: list):
        self._header(f"{len(table_ids)} tables selected")
        self._subtext("Some options are only available when a single table is selected.")
        if self.editor.read_only:
            return
        self._action_btn("Rotate all 15°",
                          lambda ids=tuple(table_ids): self._bulk_rotate(ids, 15))
        self._action_btn("Rotate all 90°",
                          lambda ids=tuple(table_ids): self._bulk_rotate(ids, 90))
        self._action_btn("Reset rotation",
                          lambda ids=tuple(table_ids): self._bulk_reset_rot(ids))
        self._spacer(10)
        self._action_btn("Duplicate all",
                          lambda ids=tuple(table_ids): self._bulk_duplicate_tables(ids))
        self._action_btn("Delete all",
                          lambda ids=tuple(table_ids): self._bulk_delete_tables(ids),
                          danger=True)

    def _build_single_seat(self, seat_id: int):
        self._header("Seat")
        self._subtext("Drag the seat to reposition it on its table.")
        if self.editor.read_only:
            return
        self._action_btn("Delete seat",
                          lambda sid=seat_id: self.editor._ctx_delete_seat(sid),
                          danger=True)

    def _build_multi_seats(self, seat_ids: list):
        self._header(f"{len(seat_ids)} seats selected")
        if self.editor.read_only:
            return
        self._action_btn("Delete all seats",
                          lambda ids=tuple(seat_ids): self._bulk_delete_seats(ids),
                          danger=True)

    def _build_mixed(self, tables: list, seats: list):
        self._header(f"{len(tables)} tables, {len(seats)} seats")
        self._subtext("Mixed selection. Select only tables or only seats for more actions.")
        if self.editor.read_only:
            return
        self._action_btn(
            "Delete all",
            lambda t=tuple(tables), s=tuple(seats): self._bulk_delete_mixed(t, s),
            danger=True)

    # ── Action helpers ────────────────────────────────────────────────────────

    def _rename_table(self, table_id: int):
        t = next((x for x in db.get_tables_for_layout(self.editor.layout_id)
                   if x["id"] == table_id), None)
        if t is None:
            return
        new_label = simpledialog.askstring(
            "Rename Table", "New name:",
            initialvalue=t.get("label", ""), parent=self.editor)
        if not new_label or not new_label.strip():
            return
        old_label = t["label"]
        db.update_table(table_id, new_label.strip(), t["capacity"])
        self.editor._push_undo(
            lambda tid=table_id, lbl=old_label, cap=t["capacity"]:
                db.update_table(tid, lbl, cap),
            f"Rename {old_label}")
        self.editor.structural_change = True
        if self.editor._room_canvas:
            self.editor._room_canvas.reload_all()
        if hasattr(self.editor, "tree"):
            try:
                if self.editor.tree.winfo_exists():
                    self.editor._refresh_tree()
            except tk.TclError:
                pass
        self.set_selection(self.selection)  # refresh panel header

    def _resize_table(self, table_id: int):
        t = next((x for x in db.get_tables_for_layout(self.editor.layout_id)
                   if x["id"] == table_id), None)
        if t is None:
            return
        dlg = _TableResizeDialog(self.editor, t)
        self.editor.wait_window(dlg)
        if not dlg.result:
            return
        new_w, new_h = dlg.result
        old_w = t.get("width",  140)
        old_h = t.get("height", 90)
        if (new_w, new_h) == (old_w, old_h):
            return
        db.update_table_shape(table_id, t.get("shape") or "rect", new_w, new_h)
        self.editor._push_undo(
            lambda tid=table_id, sh=t.get("shape") or "rect", w=old_w, h=old_h:
                db.update_table_shape(tid, sh, w, h),
            f"Resize {t.get('label','Table')}")
        self.editor.structural_change = True
        if self.editor._room_canvas:
            self.editor._room_canvas.reload_all()
        if hasattr(self.editor, "tree"):
            try:
                if self.editor.tree.winfo_exists():
                    self.editor._refresh_tree()
            except tk.TclError:
                pass

    def _add_seat_at_center(self, table_id: int):
        """Drop a seat near the table center with a small offset so it's
        visible without overlapping existing seats. Offset cycles with count."""
        existing = db.get_seats_for_table(table_id)
        n = len(existing)
        # Spiral the new seat out from center
        import math
        r = 30 + (n // 8) * 20
        a = (n % 8) * (math.pi / 4)
        lx = r * math.cos(a)
        ly = r * math.sin(a)
        new_seat_id = db.add_seat(table_id, lx, ly)
        self.editor._push_undo(
            lambda sid=new_seat_id: db.delete_seat(sid),
            "Add seat")
        self.editor.structural_change = True
        if self.editor._room_canvas:
            self.editor._room_canvas.reload_all()
        if hasattr(self.editor, "tree"):
            try:
                if self.editor.tree.winfo_exists():
                    self.editor._refresh_tree()
            except tk.TclError:
                pass
        self.set_selection(self.selection)  # refresh capacity display

    def _bulk_rotate(self, table_ids: tuple, delta: float):
        # Capture old rotations for single undo entry
        tables = [t for t in db.get_tables_for_layout(self.editor.layout_id)
                   if t["id"] in table_ids]
        old_rots = [(t["id"], t.get("rotation") or 0) for t in tables]
        for t in tables:
            new_rot = ((t.get("rotation") or 0) + delta) % 360
            db.update_table_rotation(t["id"], new_rot)

        def _restore():
            for tid, r in old_rots:
                db.update_table_rotation(tid, r)

        self.editor._push_undo(_restore, f"Rotate {len(tables)} tables")
        if self.editor._room_canvas:
            self.editor._room_canvas.reload_all()

    def _bulk_reset_rot(self, table_ids: tuple):
        tables = [t for t in db.get_tables_for_layout(self.editor.layout_id)
                   if t["id"] in table_ids]
        old_rots = [(t["id"], t.get("rotation") or 0) for t in tables]
        for t in tables:
            db.update_table_rotation(t["id"], 0)

        def _restore():
            for tid, r in old_rots:
                db.update_table_rotation(tid, r)

        self.editor._push_undo(_restore, f"Reset rotation on {len(tables)} tables")
        if self.editor._room_canvas:
            self.editor._room_canvas.reload_all()

    def _bulk_duplicate_tables(self, table_ids: tuple):
        """Duplicate each selected table individually. Each gets its own
        undo entry so users can peel them back one at a time."""
        for tid in table_ids:
            self.editor._ctx_duplicate_table(tid)

    def _bulk_delete_tables(self, table_ids: tuple):
        n = len(table_ids)
        if not messagebox.askyesno("Delete Tables",
                                    f"Delete {n} table{'s' if n != 1 else ''}? "
                                    "All their seats will be deleted too.",
                                    parent=self.editor):
            return
        # Capture enough state to restore each table and its seats
        snapshots = []
        for tid in table_ids:
            t = next((x for x in db.get_tables_for_layout(self.editor.layout_id)
                       if x["id"] == tid), None)
            if t is None:
                continue
            seats = db.get_seats_for_table(tid)
            snapshots.append({
                "layout_id": self.editor.layout_id,
                "label": t["label"],
                "shape": t.get("shape", "rect"),
                "capacity": t["capacity"],
                "width": t.get("width", 140),
                "height": t.get("height", 90),
                "pos_x": t.get("pos_x"),
                "pos_y": t.get("pos_y"),
                "decorative": t.get("decorative", 0),
                "rotation": t.get("rotation", 0),
                "seats": [(s["x_offset"], s["y_offset"]) for s in seats],
            })

        def _restore():
            for snap in snapshots:
                new_id = db.add_preset_table(
                    snap["layout_id"], snap["label"], snap["shape"],
                    snap["capacity"], snap["width"], snap["height"],
                    x=snap["pos_x"] or 0, y=snap["pos_y"] or 0,
                    decorative=snap["decorative"])
                for s in db.get_seats_for_table(new_id):
                    db.delete_seat(s["id"])
                for (lx, ly) in snap["seats"]:
                    db.add_seat(new_id, lx, ly)
                if snap["rotation"]:
                    db.update_table_rotation(new_id, snap["rotation"])

        for tid in table_ids:
            db.delete_table(tid)

        self.editor._push_undo(_restore, f"Delete {n} tables")
        self.editor.structural_change = True
        if self.editor._room_canvas:
            self.editor._room_canvas.clear_selection()
            self.editor._room_canvas.reload_all()
        if hasattr(self.editor, "tree"):
            try:
                if self.editor.tree.winfo_exists():
                    self.editor._refresh_tree()
            except tk.TclError:
                pass

    def _bulk_delete_seats(self, seat_ids: tuple):
        if not messagebox.askyesno(
            "Delete Seats",
            f"Delete {len(seat_ids)} seat{'s' if len(seat_ids) != 1 else ''}?",
            parent=self.editor):
            return
        # Capture for undo
        all_seats = db.get_seats_for_layout(self.editor.layout_id)
        snaps = [(s["table_id"], s["x_offset"], s["y_offset"])
                  for s in all_seats if s["id"] in seat_ids]

        def _restore():
            for tid, lx, ly in snaps:
                db.add_seat(tid, lx, ly)

        for sid in seat_ids:
            db.delete_seat(sid)
        self.editor._push_undo(_restore, f"Delete {len(seat_ids)} seats")
        self.editor.structural_change = True
        if self.editor._room_canvas:
            self.editor._room_canvas.clear_selection()
            self.editor._room_canvas.reload_all()
        if hasattr(self.editor, "tree"):
            try:
                if self.editor.tree.winfo_exists():
                    self.editor._refresh_tree()
            except tk.TclError:
                pass

    def _bulk_delete_mixed(self, tables: tuple, seats: tuple):
        n = len(tables) + len(seats)
        if not messagebox.askyesno(
            "Delete Selected",
            f"Delete {len(tables)} table{'s' if len(tables) != 1 else ''} "
            f"and {len(seats)} seat{'s' if len(seats) != 1 else ''}?",
            parent=self.editor):
            return
        # Handle seats first, then tables (deleting a table also removes its
        # seats, so don't double-restore)
        # Capture seat state that isn't already covered by table deletion
        table_set = set(tables)
        standalone_seats = []
        for s in db.get_seats_for_layout(self.editor.layout_id):
            if s["id"] in seats and s["table_id"] not in table_set:
                standalone_seats.append(
                    (s["table_id"], s["x_offset"], s["y_offset"]))
        # Capture tables for restore
        snapshots = []
        for tid in tables:
            t = next((x for x in db.get_tables_for_layout(self.editor.layout_id)
                       if x["id"] == tid), None)
            if t is None:
                continue
            tseats = db.get_seats_for_table(tid)
            snapshots.append({
                "layout_id": self.editor.layout_id,
                "label": t["label"],
                "shape": t.get("shape", "rect"),
                "capacity": t["capacity"],
                "width": t.get("width", 140),
                "height": t.get("height", 90),
                "pos_x": t.get("pos_x"), "pos_y": t.get("pos_y"),
                "decorative": t.get("decorative", 0),
                "rotation": t.get("rotation", 0),
                "seats": [(s["x_offset"], s["y_offset"]) for s in tseats],
            })

        def _restore():
            for snap in snapshots:
                new_id = db.add_preset_table(
                    snap["layout_id"], snap["label"], snap["shape"],
                    snap["capacity"], snap["width"], snap["height"],
                    x=snap["pos_x"] or 0, y=snap["pos_y"] or 0,
                    decorative=snap["decorative"])
                for s in db.get_seats_for_table(new_id):
                    db.delete_seat(s["id"])
                for (lx, ly) in snap["seats"]:
                    db.add_seat(new_id, lx, ly)
                if snap["rotation"]:
                    db.update_table_rotation(new_id, snap["rotation"])
            for tid, lx, ly in standalone_seats:
                db.add_seat(tid, lx, ly)

        for sid in seats:
            if any(s["id"] == sid and s["table_id"] not in table_set
                    for s in db.get_seats_for_layout(self.editor.layout_id)):
                db.delete_seat(sid)
        for tid in tables:
            db.delete_table(tid)
        self.editor._push_undo(_restore, f"Delete {n} items")
        self.editor.structural_change = True
        if self.editor._room_canvas:
            self.editor._room_canvas.clear_selection()
            self.editor._room_canvas.reload_all()
        if hasattr(self.editor, "tree"):
            try:
                if self.editor.tree.winfo_exists():
                    self.editor._refresh_tree()
            except tk.TclError:
                pass


# ── Layout Editor Window ──────────────────────────────────────────────────────

class _LayoutEditorWindow(tk.Toplevel):
    def __init__(self, parent, layout_id, read_only=False):
        super().__init__(parent)
        self.layout_id        = layout_id
        self.read_only        = read_only
        self.structural_change = False   # set True when tables added/removed/resized
        # Undo stack: each entry is a callable that reverses a change.
        # Last-in, first-out. Capped to prevent unbounded memory growth.
        self._undo_stack: list = []
        self._UNDO_CAP = 50
        layout = db.get_layout(layout_id)
        self.title(f"{'View' if read_only else 'Edit'} Layout: {layout['name']}")
        self.geometry("680x560")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        self._build()
        # Keyboard shortcut: Cmd+Z on macOS, Ctrl+Z elsewhere
        if not self.read_only:
            self.bind_all("<Command-z>", lambda e: self._undo())
            self.bind_all("<Control-z>", lambda e: self._undo())
            # Clean up the global bindings when window closes
            self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event):
        # Only fire when the Toplevel itself is being destroyed, not children
        if event.widget is self:
            try:
                self.unbind_all("<Command-z>")
                self.unbind_all("<Control-z>")
            except tk.TclError:
                pass

    def _push_undo(self, reverse_fn, description: str = ""):
        """Register a reversal function for the most recent change."""
        self._undo_stack.append((reverse_fn, description))
        if len(self._undo_stack) > self._UNDO_CAP:
            self._undo_stack.pop(0)
        self._update_undo_button()

    def _undo(self):
        if not self._undo_stack or self.read_only:
            return
        reverse_fn, description = self._undo_stack.pop()
        try:
            reverse_fn()
        except Exception as e:
            messagebox.showerror("Undo Failed",
                                 f"Could not undo '{description}': {e}",
                                 parent=self)
        self._update_undo_button()
        self.structural_change = True
        # Only refresh widgets that still exist. When the user is viewing
        # Room View, the List View's tree has been destroyed (and vice
        # versa). Tk raises TclError if we call methods on dead widgets.
        if hasattr(self, "tree"):
            try:
                if self.tree.winfo_exists():
                    self._refresh_tree()
            except tk.TclError:
                pass
        if hasattr(self, "_room_canvas") and self._room_canvas:
            try:
                if self._room_canvas.winfo_exists():
                    self._room_canvas.load()
            except tk.TclError:
                pass

    def _update_undo_button(self):
        if not hasattr(self, "_undo_btn") or not self._undo_btn.winfo_exists():
            return
        if self._undo_stack:
            last_desc = self._undo_stack[-1][1]
            self._undo_btn.configure(bg=theme.BG, fg=theme.TEXT, cursor="hand2",
                                      text=f"↶ Undo: {last_desc}")
            self._undo_btn._btn_bg    = theme.BG
            self._undo_btn._btn_hover = theme.SEP
            self._undo_btn._command   = self._undo
        else:
            self._undo_btn.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED,
                                      cursor="", text="↶ Undo")
            self._undo_btn._btn_bg    = theme.GHOST_BG
            self._undo_btn._btn_hover = theme.GHOST_BG
            self._undo_btn._command   = lambda: None

    def _build(self):
        layout = db.get_layout(self.layout_id)
        hdr = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text=layout["name"], font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(side="left")
        if self.read_only:
            tk.Label(hdr, text="   🔒 read-only", font=theme.FONT_SMALL,
                     bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left")
        # Save/Close button on the right. All edits auto-persist to DB as
        # they happen, so this is really just "close the window" — but
        # labeling it "Save & Close" makes that fact obvious to users
        # who expect a save button.
        btn_label = "Close" if self.read_only else "✓  Save & Close"
        btn_style = "ghost" if self.read_only else "primary"
        make_btn(hdr, btn_label, self.destroy,
                 style=btn_style, padx=16, pady=7).pack(side="right")
        # Undo button (edit mode only) — disabled when stack is empty
        if not self.read_only:
            self._undo_btn = make_btn(hdr, "↶ Undo", lambda: None,
                                       style="ghost", padx=12, pady=7)
            self._undo_btn.pack(side="right", padx=(0, 8))
            self._update_undo_button()
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        tab_bar = tk.Frame(self, bg=theme.BG)
        tab_bar.pack(fill="x", padx=24, pady=(8, 0))
        self._tab_btns    = {}
        self._tab_content = tk.Frame(self, bg=theme.BG)
        self._tab_content.pack(fill="both", expand=True)

        def switch(key):
            for k, b in self._tab_btns.items():
                active = (k == key)
                b.configure(bg=theme.ACCENT if active else theme.BG,
                            fg=theme.ACCENT_TEXT if active else theme.TEXT_DIM)
                b._btn_bg    = theme.ACCENT if active else theme.BG
                b._btn_hover = theme.ACCENT_DARK if active else theme.SEP
            for w in self._tab_content.winfo_children():
                w.destroy()
            if key == "list":
                self._build_list_view(self._tab_content)
            else:
                self._build_room_view(self._tab_content)
            self.update_idletasks()
            self.update()

        for label, key in [("  List View  ", "list"), ("  Room View  ", "room")]:
            b = make_btn(tab_bar, label, command=lambda k=key: switch(k),
                         style="tab", padx=14, pady=7)
            b.pack(side="left")
            self._tab_btns[key] = b

        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)
        switch("list")

    def _build_list_view(self, parent):
        if not self.read_only:
            bar = tk.Frame(parent, bg=theme.BG, padx=24, pady=10)
            bar.pack(fill="x")
            make_btn(bar, "+ Add Table", self._add_table_dialog,
                     style="primary").pack(side="left")
            make_btn(bar, "Rename Layout", self._rename_layout_dialog,
                     style="ghost").pack(side="left", padx=10)

        # Body: list (left) + actions panel (right)
        body = tk.Frame(parent, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=(8, 12))

        # Actions panel first (packed right), then tree fills remainder
        panel_frame = tk.Frame(body, bg=theme.BG)
        panel_frame.pack(side="right", fill="y", padx=(12, 0))
        self._list_panel = _ActionsPanel(panel_frame, self)
        self._list_panel.pack(fill="y", expand=False)

        # Treeview (left side)
        cols = ("label", "shape", "capacity")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
        self.tree.heading("label",    text="Table Name")
        self.tree.heading("shape",    text="Shape")
        self.tree.heading("capacity", text="Seats")
        self.tree.column("label",    width=260, anchor="w")
        self.tree.column("shape",    width=110, anchor="center")
        self.tree.column("capacity", width=90,  anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        # Right-click context menu. macOS delivers right-click as Button-2
        # for the physical right button and ButtonPress-3 on external mice.
        # Bind both, plus Ctrl-click for single-button setups.
        self.tree.bind("<Button-2>",         self._on_tree_right_click)
        self.tree.bind("<Button-3>",         self._on_tree_right_click)
        self.tree.bind("<Control-Button-1>", self._on_tree_right_click)

        self._refresh_tree()
        # Initialize panel to empty selection
        self._list_panel.set_selection([])

    def _on_tree_right_click(self, event):
        """Open a context menu for the table row under the cursor. If the
        row isn't already selected, select it first so the menu action
        targets the right table."""
        if self.read_only:
            return
        row_iid = self.tree.identify_row(event.y)
        if not row_iid:
            return
        try:
            table_id = int(row_iid)
        except (TypeError, ValueError):
            return
        # Update selection to include the clicked row if it wasn't selected
        if row_iid not in self.tree.selection():
            self.tree.selection_set(row_iid)
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == table_id), None)
        if t is None:
            return
        menu = tk.Menu(self, tearoff=0, bg=theme.PANEL, fg=theme.TEXT,
                       activebackground=theme.ACCENT,
                       activeforeground=theme.ACCENT_TEXT)
        menu.add_command(label="Rename…",
                          command=lambda: self._list_panel._rename_table(table_id))
        menu.add_command(label="Resize…",
                          command=lambda: self._list_panel._resize_table(table_id))
        menu.add_separator()
        menu.add_command(label="Rotate 15°",
                          command=lambda: self._ctx_rotate(table_id, 15))
        menu.add_command(label="Rotate 90°",
                          command=lambda: self._ctx_rotate(table_id, 90))
        menu.add_command(label="Reset rotation",
                          command=lambda: self._ctx_set_rotation(table_id, 0))
        menu.add_separator()
        cur_shape = t.get("shape", "rect")
        other = "round" if cur_shape == "rect" else "rect"
        menu.add_command(label=f"Change shape to {other.capitalize()}",
                          command=lambda: self._ctx_toggle_shape(table_id))
        if t.get("decorative"):
            menu.add_command(label="Make non-decorative",
                              command=lambda: self._ctx_toggle_decorative(table_id))
        else:
            menu.add_command(label="Mark as decorative",
                              command=lambda: self._ctx_toggle_decorative(table_id))
        menu.add_separator()
        menu.add_command(label="Duplicate table",
                          command=lambda: self._ctx_duplicate_table(table_id))
        menu.add_command(label="Delete table",
                          command=lambda: self._ctx_delete_table(table_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_tree_select(self, event=None):
        """Forward tree selection changes to the actions panel."""
        if not hasattr(self, "_list_panel"):
            return
        sel = self.tree.selection()
        sel_list = [("table", int(iid)) for iid in sel]
        self._list_panel.set_selection(sel_list)

    def _build_room_view(self, parent):
        bar = tk.Frame(parent, bg=theme.BG, padx=24, pady=8)
        bar.pack(fill="x")

        if not self.read_only:
            make_btn(bar, "+ Add Table", self._add_table_dialog,
                     style="primary").pack(side="left")
            tk.Label(bar,
                     text="  Drag to arrange. Click to select. "
                          "Cmd/Shift-click to add to selection.",
                     font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM).pack(side="left")
        else:
            tk.Label(bar, text="Read-only layout.",
                     font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM).pack(side="left")

        make_btn(bar, "↺ Reset Layout", self._reset_room_layout,
                 style="ghost").pack(side="right")

        self._snap_var = tk.BooleanVar(value=getattr(self, "_snap_enabled", True))
        def _toggle_snap():
            enabled = self._snap_var.get()
            self._snap_enabled = enabled
            if hasattr(self, "_room_canvas") and self._room_canvas:
                self._room_canvas.set_snap(enabled)
        snap_cb = tk.Checkbutton(
            bar, text="Snap to grid",
            variable=self._snap_var, command=_toggle_snap,
            bg=theme.BG, fg=theme.TEXT, font=theme.FONT_SMALL,
            activebackground=theme.BG, activeforeground=theme.TEXT,
            selectcolor=theme.PANEL,
            borderwidth=0, highlightthickness=0)
        snap_cb.pack(side="right", padx=(0, 10))

        # Body: canvas (left) + actions panel (right)
        body = tk.Frame(parent, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        panel_frame = tk.Frame(body, bg=theme.BG)
        panel_frame.pack(side="right", fill="y", padx=(12, 0))
        self._room_panel = _ActionsPanel(panel_frame, self)
        self._room_panel.pack(fill="y", expand=False)

        cf = tk.Frame(body, bg=theme.CANVAS_BG)
        cf.pack(side="left", fill="both", expand=True)
        snap = getattr(self, "_snap_enabled", True)
        # In read-only mode the canvas uses view mode — no drag bindings,
        # no selection, no context menu. Nothing the user does can
        # mutate the layout. In edit mode the canvas wires up the full
        # editing interaction set.
        canvas_mode = "view" if self.read_only else "edit"
        self._room_canvas = rc.RoomCanvas(
            cf, self.layout_id, mode=canvas_mode,
            on_move=None if self.read_only else self._on_canvas_moved,
            on_context=None if self.read_only else self._on_canvas_context,
            on_selection_change=(None if self.read_only
                                  else self._on_room_selection_change),
            snap_enabled=snap)
        self._room_canvas.pack(fill="both", expand=True)
        self._room_canvas.after(50, self._room_canvas.load)
        if not self.read_only:
            self._room_panel.set_selection([])

    def _on_room_selection_change(self, selection):
        """Called by the canvas whenever its selection set changes."""
        if hasattr(self, "_room_panel") and self._room_panel.winfo_exists():
            self._room_panel.set_selection(selection)

    def _on_canvas_context(self, kind, entity_id, event):
        """Show a context menu based on what the user right-clicked."""
        menu = tk.Menu(self, tearoff=0,
                        bg=theme.PANEL, fg=theme.TEXT,
                        activebackground=theme.ACCENT,
                        activeforeground=theme.ACCENT_TEXT,
                        font=theme.FONT_BODY, bd=1)

        if kind == "seat":
            menu.add_command(label="Delete seat",
                              command=lambda: self._ctx_delete_seat(entity_id))
        elif kind == "table":
            # Table commands
            t = next((x for x in db.get_tables_for_layout(self.layout_id)
                      if x["id"] == entity_id), None)
            if t is None:
                return
            menu.add_command(label="Add seat here",
                              command=lambda: self._ctx_add_seat_at(entity_id,
                                                                      event.x, event.y))
            menu.add_separator()
            menu.add_command(label="Rotate 15°",
                              command=lambda: self._ctx_rotate(entity_id, 15))
            menu.add_command(label="Rotate 90°",
                              command=lambda: self._ctx_rotate(entity_id, 90))
            menu.add_command(label="Reset rotation",
                              command=lambda: self._ctx_set_rotation(entity_id, 0))
            menu.add_separator()
            # Shape toggle
            cur_shape = t.get("shape", "rect")
            other = "round" if cur_shape == "rect" else "rect"
            menu.add_command(label=f"Change shape to {other.capitalize()}",
                              command=lambda: self._ctx_toggle_shape(entity_id))
            # Decorative toggle
            if t.get("decorative"):
                menu.add_command(label="Make non-decorative",
                                  command=lambda: self._ctx_toggle_decorative(entity_id))
            else:
                menu.add_command(label="Mark as decorative",
                                  command=lambda: self._ctx_toggle_decorative(entity_id))
            menu.add_separator()
            menu.add_command(label="Duplicate table",
                              command=lambda: self._ctx_duplicate_table(entity_id))
            menu.add_command(label="Delete table",
                              command=lambda: self._ctx_delete_table(entity_id))
        else:
            return

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── Context menu action handlers ─────────────────────────────────────────

    def _ctx_add_seat_at(self, table_id: int, canvas_x: int, canvas_y: int):
        """Add a seat at the canvas coordinates, converted to table-local."""
        lx, ly = self._room_canvas.canvas_to_table_local(table_id, canvas_x, canvas_y)
        new_seat_id = db.add_seat(table_id, lx, ly)
        self._push_undo(
            lambda sid=new_seat_id: db.delete_seat(sid),
            "Add seat"
        )
        self.structural_change = True
        self._room_canvas.reload_all()
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self._refresh_tree()

    def _ctx_delete_seat(self, seat_id: int):
        # Capture info for undo
        seats = [s for s in self._room_canvas._seats if s["id"] == seat_id]
        if not seats:
            return
        s = seats[0]
        old_tid = s["table_id"]
        old_x   = s["x_offset"]
        old_y   = s["y_offset"]

        def _restore():
            db.add_seat(old_tid, old_x, old_y)

        db.delete_seat(seat_id)
        self._push_undo(_restore, "Delete seat")
        self.structural_change = True
        self._room_canvas.reload_all()
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self._refresh_tree()

    def _ctx_rotate(self, table_id: int, delta_deg: float):
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == table_id), None)
        if t is None:
            return
        old_rot = t.get("rotation") or 0
        new_rot = (old_rot + delta_deg) % 360
        db.update_table_rotation(table_id, new_rot)
        self._push_undo(
            lambda tid=table_id, r=old_rot: db.update_table_rotation(tid, r),
            f"Rotate {t['label']}"
        )
        self._room_canvas.reload_all()

    def _ctx_set_rotation(self, table_id: int, rotation: float):
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == table_id), None)
        if t is None:
            return
        old_rot = t.get("rotation") or 0
        db.update_table_rotation(table_id, rotation)
        self._push_undo(
            lambda tid=table_id, r=old_rot: db.update_table_rotation(tid, r),
            f"Reset rotation on {t['label']}"
        )
        self._room_canvas.reload_all()

    def _ctx_toggle_shape(self, table_id: int):
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == table_id), None)
        if t is None:
            return
        old_shape = t.get("shape", "rect")
        new_shape = "round" if old_shape == "rect" else "rect"
        old_w = t.get("width", 140)
        old_h = t.get("height", 90)
        # For round, keep aspect approximately square; for rect, leave as-is.
        new_w, new_h = old_w, old_h
        if new_shape == "round":
            s = max(old_w, old_h)
            new_w, new_h = s, s
        db.update_table_shape(table_id, new_shape, new_w, new_h)
        self._push_undo(
            lambda tid=table_id, sh=old_shape, w=old_w, h=old_h:
                db.update_table_shape(tid, sh, w, h),
            f"Change shape: {t['label']}"
        )
        self.structural_change = True
        self._room_canvas.reload_all()
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self._refresh_tree()

    def _ctx_toggle_decorative(self, table_id: int):
        import sqlite3
        with db.get_connection() as conn:
            cur = conn.execute("SELECT decorative FROM tables WHERE id=?",
                                (table_id,)).fetchone()
            if not cur:
                return
            old_val = cur[0]
            new_val = 0 if old_val else 1
            conn.execute("UPDATE tables SET decorative=? WHERE id=?",
                          (new_val, table_id))

        def _restore():
            with db.get_connection() as conn:
                conn.execute("UPDATE tables SET decorative=? WHERE id=?",
                              (old_val, table_id))
            self._room_canvas.reload_all()

        self._push_undo(_restore, "Toggle decorative")
        self.structural_change = True
        self._room_canvas.reload_all()
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self._refresh_tree()

    def _ctx_duplicate_table(self, table_id: int):
        """Create a copy of the given table, offset slightly so it's visible.
        Preserves shape, size, rotation, decorative flag, and seat layout."""
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == table_id), None)
        if t is None:
            return
        offset = 30
        orig_seats = db.get_seats_for_table(table_id)
        new_id = db.add_preset_table(
            self.layout_id,
            label=t["label"],
            shape=t.get("shape", "rect"),
            capacity=t["capacity"],
            width=t.get("width", 140),
            height=t.get("height", 90),
            x=(t.get("pos_x") or 0) + offset,
            y=(t.get("pos_y") or 0) + offset,
            decorative=t.get("decorative", 0))
        # add_preset_table seeds default seats; replace them with the
        # source's actual seat positions
        for s in db.get_seats_for_table(new_id):
            db.delete_seat(s["id"])
        for s in orig_seats:
            db.add_seat(new_id, s["x_offset"], s["y_offset"])
        if t.get("rotation"):
            db.update_table_rotation(new_id, t["rotation"])

        self._push_undo(
            lambda tid=new_id: db.delete_table(tid),
            f"Duplicate {t['label']}")
        self.structural_change = True
        self._room_canvas.reload_all()
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self._refresh_tree()

    def _ctx_delete_table(self, table_id: int):
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == table_id), None)
        if t is None:
            return
        if not messagebox.askyesno("Delete Table",
                                    f"Delete '{t['label']}' and all its seats?",
                                    parent=self):
            return
        old_label = t["label"]
        old_cap   = t["capacity"]
        old_px    = t.get("pos_x")
        old_py    = t.get("pos_y")
        old_shape = t.get("shape", "rect")
        old_w     = t.get("width",  140)
        old_h     = t.get("height", 90)
        old_dec   = t.get("decorative", 0)
        old_rot   = t.get("rotation", 0)
        old_seats = db.get_seats_for_table(table_id)

        def _restore():
            new_id = db.add_preset_table(
                self.layout_id, old_label, old_shape, old_cap,
                old_w, old_h, x=old_px or 0, y=old_py or 0,
                decorative=old_dec)
            # add_preset_table seeds default seats — delete them, use originals
            for s in db.get_seats_for_table(new_id):
                db.delete_seat(s["id"])
            for s in old_seats:
                db.add_seat(new_id, s["x_offset"], s["y_offset"])
            if old_rot:
                db.update_table_rotation(new_id, old_rot)

        db.delete_table(table_id)
        self._push_undo(_restore, f"Delete {old_label}")
        self.structural_change = True
        self._room_canvas.reload_all()
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self._refresh_tree()

    def _on_canvas_moved(self, kind: str, entity_id: int, old_state, new_state):
        """Record a drag (table OR seat) as an undoable action."""
        if kind == "table_move":
            t = next((x for x in db.get_tables_for_layout(self.layout_id)
                      if x["id"] == entity_id), None)
            desc = f"Move {t['label']}" if t else "Move table"
            old_x, old_y = old_state

            def _restore():
                db.update_table_position(entity_id, old_x, old_y)
                if self._room_canvas:
                    for tbl in self._room_canvas._tables:
                        if tbl["id"] == entity_id:
                            tbl["pos_x"] = old_x
                            tbl["pos_y"] = old_y
                            break

            self._push_undo(_restore, desc)
        elif kind == "seat_move":
            old_x, old_y = old_state

            def _restore():
                db.update_seat_position(entity_id, old_x, old_y)
                if self._room_canvas:
                    for seat in self._room_canvas._seats:
                        if seat["id"] == entity_id:
                            seat["x_offset"] = old_x
                            seat["y_offset"] = old_y
                            break

            self._push_undo(_restore, "Move seat")
        # Position drags don't count as structural — purely visual.

    def _reset_room_layout(self):
        if hasattr(self, "_room_canvas"):
            self._room_canvas.reset_positions()

    def _refresh_tree(self):
        # The tree may not exist (user is on Room View, never opened List View)
        # or may have been destroyed (List View was replaced by tab switch).
        # Either case: quietly no-op.
        if not hasattr(self, "tree"):
            return
        try:
            if not self.tree.winfo_exists():
                return
        except tk.TclError:
            return
        for row in self.tree.get_children():
            self.tree.delete(row)
        for t in db.get_tables_for_layout(self.layout_id):
            shape_label = {
                "round": "⬤ Round",
                "rect":  "▭ Rectangle",
            }.get(t.get("shape", "rect"), t.get("shape", "?"))
            if t.get("decorative"):
                shape_label += " (décor)"
            cap_display = t["capacity"] if not t.get("decorative") else "—"
            self.tree.insert("", "end", iid=str(t["id"]),
                             values=(t["label"], shape_label, cap_display))

    def _add_table_dialog(self):
        """Show a palette of preset shapes. Picking one stamps it on the layout."""
        dlg = _TablePresetDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        preset = dlg.result
        # Place at a reasonable starting position (center-ish of canvas)
        start_x, start_y = 250, 250
        new_id = db.add_preset_table(
            self.layout_id,
            label=preset["label"],
            shape=preset["shape"],
            capacity=preset["capacity"],
            width=preset["width"],
            height=preset["height"],
            x=start_x, y=start_y,
            decorative=preset.get("decorative", 0)
        )
        self._push_undo(
            lambda tid=new_id: db.delete_table(tid),
            f"Add {preset['label']}"
        )
        self.structural_change = True
        self._refresh_tree()
        # If room view is active, reload canvas
        if hasattr(self, "_room_canvas") and self._room_canvas:
            try:
                if self._room_canvas.winfo_exists():
                    self._room_canvas.reload_all()
            except tk.TclError:
                pass

    def _edit_table_dialog(self):
        """Rename selected table. (Capacity is now determined by seats, not editable
        from the list view. Add/remove seats via the Room View in a future pass.)"""
        sel = self.tree.selection()
        if not sel:
            return
        tid = int(sel[0])
        t   = next((x for x in db.get_tables_for_layout(self.layout_id)
                    if x["id"] == tid), None)
        if not t:
            return
        new_label = simpledialog.askstring(
            "Rename Table", f"New name for '{t['label']}':",
            initialvalue=t["label"], parent=self)
        if not new_label or not new_label.strip():
            return
        old_label = t["label"]
        db.update_table(tid, new_label.strip(), t["capacity"])
        self._push_undo(
            lambda t_id=tid, lbl=old_label, cap=t["capacity"]:
                db.update_table(t_id, lbl, cap),
            f"Rename {old_label}"
        )
        self.structural_change = True
        self._refresh_tree()
        if hasattr(self, "_room_canvas") and self._room_canvas:
            try:
                if self._room_canvas.winfo_exists():
                    self._room_canvas.reload_all()
            except tk.TclError:
                pass

    def _remove_table(self):
        sel = self.tree.selection()
        if not sel:
            return
        tid = int(sel[0])
        t = next((x for x in db.get_tables_for_layout(self.layout_id)
                  if x["id"] == tid), None)
        if not t:
            return
        if messagebox.askyesno("Remove Table", "Remove this table from the layout?",
                               parent=self):
            # Capture everything needed to restore
            old_label = t["label"]
            old_cap   = t["capacity"]
            old_px    = t.get("pos_x")
            old_py    = t.get("pos_y")
            old_shape = t.get("shape", "rect")
            old_w     = t.get("width",  140)
            old_h     = t.get("height", 90)
            old_dec   = t.get("decorative", 0)
            old_seats = db.get_seats_for_table(tid)

            def _restore():
                new_id = db.add_preset_table(
                    self.layout_id, old_label, old_shape, old_cap,
                    old_w, old_h, x=old_px or 0, y=old_py or 0,
                    decorative=old_dec
                )
                # add_preset_table seeds default seats; replace them with
                # the captured originals so positions are preserved.
                for s in db.get_seats_for_table(new_id):
                    db.delete_seat(s["id"])
                for s in old_seats:
                    db.add_seat(new_id, s["x_offset"], s["y_offset"])

            db.delete_table(tid)
            self._push_undo(_restore, f"Remove {old_label}")
            self.structural_change = True
            self._refresh_tree()
            if hasattr(self, "_room_canvas") and self._room_canvas:
                try:
                    if self._room_canvas.winfo_exists():
                        self._room_canvas.reload_all()
                except tk.TclError:
                    pass

    def _rename_layout_dialog(self):
        layout = db.get_layout(self.layout_id)
        new_name = simpledialog.askstring("Rename", "New name:",
                                          initialvalue=layout["name"], parent=self)
        if new_name and new_name.strip():
            try:
                db.rename_layout(self.layout_id, new_name.strip())
                self.title(f"Edit Layout: {new_name.strip()}")
            except Exception as e:
                messagebox.showerror("Error", str(e))


# ── Generate Round Dialog ─────────────────────────────────────────────────────

class _GenerateRoundDialog(tk.Toplevel):
    def __init__(self, parent, students, tables, class_id, cls):
        super().__init__(parent)
        self.students  = students
        self.tables    = tables
        self.class_id  = class_id
        self.cls       = cls
        self.committed = False
        self.title("Generate Seating Round")
        self.geometry("560x540")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        self._build()

    def _build(self):
        tk.Label(self, text="Generate New Round", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # ── Bottom-fixed controls: buttons + status ──────────────────────────
        # Pack these on the dialog itself (not inside body) so they're always
        # visible regardless of content size or window resize.
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")

        self.status_lbl = tk.Label(bottom, text="", font=theme.FONT_BODY,
                                   bg=theme.BG, fg=theme.TEXT_DIM)
        self.status_lbl.pack(side="bottom", anchor="w", pady=(10, 0), fill="x")

        btn_row = tk.Frame(bottom, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "Generate & Save", self._run,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)

        # ── Body: unified scrollable area using a tk.Text widget ─────────────
        # tk.Text is a native macOS widget with working trackpad scroll. We
        # embed all content into it via window_create for smooth scrolling.
        body_container, body_text = make_text_scroll_container(
            self, padx=24, pady=12)
        body_container.pack(fill="both", expand=True)

        # Helper: embed a widget as a "paragraph" block inside the Text
        def add_block(widget, pady_after: int = 0):
            body_text.window_create("end", window=widget, stretch=1)
            body_text.insert("end", "\n")
            if pady_after:
                # Create an empty spacer frame for consistent vertical spacing
                spacer = tk.Frame(body_text, bg=theme.BG, height=pady_after)
                body_text.window_create("end", window=spacer)
                body_text.insert("end", "\n")

        # Round label
        lbl1 = tk.Label(body_text, text="Round label", font=theme.FONT_BOLD,
                        bg=theme.BG, fg=theme.TEXT, anchor="w")
        add_block(lbl1)
        self.label_var = tk.StringVar(
            value=f"Week of {datetime.now().strftime('%b %d, %Y')}")
        entry_frame = tk.Frame(body_text, bg=theme.BG)
        styled_entry(entry_frame, textvariable=self.label_var).pack(
            fill="x", anchor="w")
        add_block(entry_frame, pady_after=14)

        # Absent students
        lbl2 = tk.Label(body_text, text="Absent students", font=theme.FONT_BOLD,
                        bg=theme.BG, fg=theme.TEXT, anchor="w")
        add_block(lbl2)
        hint1 = tk.Label(body_text,
                         text="Click a student to mark them absent this round.",
                         font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                         anchor="w")
        add_block(hint1, pady_after=6)

        style = ttk.Style()
        style.configure("Generate.Treeview", rowheight=28,
                        font=theme.FONT_BODY)

        absent_container = tk.Frame(body_text, bg=theme.BG,
                                     highlightbackground=theme.BORDER,
                                     highlightthickness=1)
        absent_tree = ttk.Treeview(absent_container, columns=("check", "name"),
                                    show="tree",
                                    style="Generate.Treeview",
                                    # Show ALL rows — the outer Text widget
                                    # handles scrolling for the whole page
                                    height=len(self.students),
                                    selectmode="none")
        absent_tree.column("#0", width=0, stretch=False)
        absent_tree.column("check", width=44, anchor="center", stretch=False)
        absent_tree.column("name", anchor="w")
        absent_tree.pack(fill="x")
        absent_tree.tag_configure("checked", background=theme.ACCENT,
                                   foreground=theme.ACCENT_TEXT)
        add_block(absent_container, pady_after=14)

        self.absent_ids: set = set()
        for s in self.students:
            absent_tree.insert("", "end", iid=f"s{s['id']}",
                               values=("  ☐  ",
                                       s.get("display") or s["name"]))

        def _toggle_absent(event):
            iid = absent_tree.identify_row(event.y)
            if not iid:
                return
            sid = int(iid[1:])
            if sid in self.absent_ids:
                self.absent_ids.discard(sid)
                absent_tree.set(iid, "check", "  ☐  ")
                absent_tree.item(iid, tags=())
            else:
                self.absent_ids.add(sid)
                absent_tree.set(iid, "check", "  ☑  ")
                absent_tree.item(iid, tags=("checked",))
        absent_tree.bind("<Button-1>", _toggle_absent)

        # Exclude tables
        lbl3 = tk.Label(body_text, text="Exclude tables (this round only)",
                        font=theme.FONT_BOLD, bg=theme.BG, fg=theme.TEXT,
                        anchor="w")
        add_block(lbl3)
        hint2 = tk.Label(body_text,
                         text="Click a table to exclude it from this round only.",
                         font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                         anchor="w")
        add_block(hint2, pady_after=6)

        table_container = tk.Frame(body_text, bg=theme.BG,
                                    highlightbackground=theme.BORDER,
                                    highlightthickness=1)
        table_tree = ttk.Treeview(table_container, columns=("check", "label"),
                                   show="tree",
                                   style="Generate.Treeview",
                                   height=len(self.tables),
                                   selectmode="none")
        table_tree.column("#0", width=0, stretch=False)
        table_tree.column("check", width=44, anchor="center", stretch=False)
        table_tree.column("label", anchor="w")
        table_tree.pack(fill="x")
        table_tree.tag_configure("checked", background=theme.ACCENT,
                                  foreground=theme.ACCENT_TEXT)
        add_block(table_container, pady_after=8)

        self.excluded_tids: set = set()
        for t in self.tables:
            table_tree.insert("", "end", iid=f"t{t['id']}",
                              values=("  ☐  ",
                                      f"{t['label']}  (capacity {t['capacity']})"))

        def _toggle_table(event):
            iid = table_tree.identify_row(event.y)
            if not iid:
                return
            tid = int(iid[1:])
            if tid in self.excluded_tids:
                self.excluded_tids.discard(tid)
                table_tree.set(iid, "check", "  ☐  ")
                table_tree.item(iid, tags=())
            else:
                self.excluded_tids.add(tid)
                table_tree.set(iid, "check", "  ☑  ")
                table_tree.item(iid, tags=("checked",))
        table_tree.bind("<Button-1>", _toggle_table)

        # ── Advanced: solver timeout ─────────────────────────────────────────
        # Long histories + large classes can cause CBC to run long. 30s is a
        # comfortable default for most classroom rotations; teachers who want
        # the optimizer to keep searching on hard rounds can raise it.
        adv_label = tk.Label(body_text, text="Advanced", font=theme.FONT_BOLD,
                              bg=theme.BG, fg=theme.TEXT, anchor="w")
        add_block(adv_label, pady_after=4)
        timeout_hint = tk.Label(body_text,
            text=("Solver timeout (seconds). 30 works for most classes; raise "
                  "to 60–300 if the optimizer times out on later rounds."),
            font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
            anchor="w", justify="left", wraplength=560)
        add_block(timeout_hint, pady_after=4)

        # Timeout default reads from user settings (Fast/Standard/Thorough/
        # Ridiculous). Falls back to 30s if no preset is configured.
        _TIMEOUT_SECS_BY_PRESET = {
            "Fast": 10, "Standard": 30, "Thorough": 120, "Ridiculous": 600
        }
        preset_name = db.get_setting("default_optimizer_timeout", "Standard")
        default_secs = _TIMEOUT_SECS_BY_PRESET.get(preset_name, 30)
        self.timeout_var = tk.StringVar(value=str(default_secs))
        timeout_row = tk.Frame(body_text, bg=theme.BG)
        styled_entry(timeout_row, textvariable=self.timeout_var,
                      width=8).pack(side="left")
        tk.Label(timeout_row, text="  seconds",
                  font=theme.FONT_BODY, bg=theme.BG,
                  fg=theme.TEXT_DIM).pack(side="left")
        add_block(timeout_row, pady_after=8)

        # Disable text editing / cursor blinking but keep scrolling.
        # state="disabled" would also block trackpad scroll on some macOS Tk
        # builds, so we just make the Text non-editable via key bindings.
        def _block_edits(e):
            return "break"
        body_text.bind("<Key>", _block_edits)
        body_text.bind("<Button-2>", _block_edits)  # middle-click paste

    def _run(self):
        label = self.label_var.get().strip()
        if not label:
            messagebox.showwarning("Missing Label", "Please enter a label.", parent=self)
            return

        # Parse timeout. Fall back to default 30s on bad input.
        try:
            timeout_seconds = int(self.timeout_var.get().strip())
            if timeout_seconds < 5:
                messagebox.showwarning("Invalid Timeout",
                                        "Timeout must be at least 5 seconds.",
                                        parent=self)
                return
        except (ValueError, TypeError):
            messagebox.showwarning("Invalid Timeout",
                                    "Please enter a number of seconds.",
                                    parent=self)
            return
        self._timeout_seconds = timeout_seconds

        absent_ids    = set(self.absent_ids)
        excluded_tids = set(self.excluded_tids)
        present       = [s for s in self.students if s["id"] not in absent_ids]
        active_tables = [t for t in self.tables   if t["id"] not in excluded_tids]

        if not present:
            messagebox.showwarning("No Students", "All students are marked absent.", parent=self)
            return
        if not active_tables:
            messagebox.showwarning("No Tables", "All tables are excluded.", parent=self)
            return
        total_seats = sum(t["capacity"] for t in active_tables)
        if total_seats < len(present):
            messagebox.showwarning("Not Enough Seats",
                                   f"{len(present)} students but only {total_seats} seats.",
                                   parent=self)
            return

        self.status_lbl.configure(
            text=f"⏳  Running optimiser (up to {self._timeout_seconds}s)…",
            fg=theme.ACCENT)
        self.update()

        pair_history = db.get_pair_history(self.class_id)
        seat_history = db.get_seat_history(self.class_id)

        # Gather seats for all active (non-excluded, non-decorative) tables.
        # Seats carry absolute world coordinates for adjacency calculation.
        active_tid_set = {t["id"] for t in active_tables}
        all_seats_raw = db.get_seats_for_layout(self.cls["layout_id"])
        opt_seats = []
        for s in all_seats_raw:
            if s["table_id"] not in active_tid_set:
                continue
            # Compute absolute world coordinate. Ignoring rotation for
            # adjacency — seats at the same table stay the same relative
            # distance regardless of table rotation.
            abs_x = (s.get("table_x") or 0) + s["x_offset"]
            abs_y = (s.get("table_y") or 0) + s["y_offset"]
            opt_seats.append(opt.Seat(
                id=s["id"], table_id=s["table_id"],
                x=abs_x, y=abs_y
            ))

        # Build Student objects with pin info. If pinned table or seat isn't
        # in the active set, drop the pin for this round.
        active_seat_ids = {k.id for k in opt_seats}
        opt_students = []
        for s in present:
            pin_seat  = s.get("pinned_seat_id")
            pin_table = s.get("pinned_table_id")
            if pin_seat is not None and pin_seat not in active_seat_ids:
                pin_seat = None
            if pin_table is not None and pin_table not in active_tid_set:
                pin_table = None
            opt_students.append(opt.Student(
                id=s["id"], name=s["name"],
                pinned_seat_id=pin_seat,
                pinned_table_id=pin_table))

        forbidden = [(c["student_a"], c["student_b"])
                     for c in db.get_pair_constraints(self.class_id)]

        # Dispatch to the right optimizer based on the class's seating mode.
        # The result shape is the same in both cases (a list of (student_id,
        # seat_id, table_id) tuples) — per-table mode leaves seat_id=None.
        mode = self.cls.get("seating_mode", "per_table")
        if mode == "per_seat":
            result = opt.optimise_seating(
                opt_students, opt_seats, pair_history,
                forbidden_pairs=forbidden,
                seat_history=seat_history,
                time_limit_seconds=self._timeout_seconds)
        else:
            # Per-table mode: build a simpler Student/Table list and call
            # the per-table optimizer. Seat-level info is ignored.
            tbl_students = [opt_table.Student(
                id=s.id, name=s.name,
                pinned_table_id=s.pinned_table_id) for s in opt_students]
            tbl_tables = [opt_table.Table(
                id=t["id"], capacity=t["capacity"]) for t in active_tables]
            result = opt_table.optimise_seating(
                tbl_students, tbl_tables, pair_history,
                forbidden_pairs=forbidden,
                time_limit_seconds=self._timeout_seconds)

        if "Infeasible" in result.status:
            self.status_lbl.configure(text=f"✗  {result.status}", fg=theme.DANGER)
            return

        round_id = db.create_round(self.class_id, label, datetime.now().isoformat(),
                                   list(excluded_tids), result.total_repeat_score,
                                   seating_mode=mode)
        db.save_assignments(round_id, result.assignments)
        # Compute true table-repeat count (the human-meaningful metric,
        # as opposed to the weighted pairing score reported by the optimizer)
        true_repeats = db.count_repeat_pairs(self.class_id,
                                              result.assignments,
                                              exclude_round_id=round_id)
        status_parts = [f"✓  {result.status}",
                        f"pairing score: {result.total_repeat_score}",
                        f"table repeats: {true_repeats}"]
        self.status_lbl.configure(
            text="  ·  ".join(status_parts),
            fg=theme.SUCCESS)
        self.committed = True
        assignments = db.get_assignments_for_round(round_id)
        self.after(500, lambda: self._show_result(assignments, label,
                                                   result.total_repeat_score,
                                                   true_repeats))

    def _show_result(self, assignments, label, repeat_score=0, true_repeats=0):
        # Grab reference to the main app BEFORE destroying self, so we can
        # parent the result window to it. Creating a Toplevel with no parent
        # produces an orphan window on macOS whose geometry/event loop
        # integration is broken — the first tab switch inside it renders
        # into a zero-width container.
        app = self.master
        self.destroy()
        win = tk.Toplevel(app)
        win.title(f"Result: {label}")
        win.geometry("800x600")
        win.configure(bg=theme.BG)

        hdr = tk.Frame(win, bg=theme.BG, padx=24, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text=label, font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
        # Color headline by the TRUE table-repeat count, which is the
        # metric users actually care about. Pairing score can be 0 while
        # still having table repeats (pruning drops tiny penalties).
        if true_repeats == 0:
            sc = theme.SUCCESS
            sm = "✓  No repeated tablemates!"
        elif true_repeats <= 6:
            sc = theme.ACCENT
            sm = f"{true_repeats} repeated tablemate pair{'s' if true_repeats != 1 else ''}"
        else:
            sc = theme.DANGER
            sm = f"{true_repeats} repeated tablemate pair{'s' if true_repeats != 1 else ''}"
        tk.Label(hdr, text=sm, font=theme.FONT_BOLD, bg=theme.BG, fg=sc).pack(anchor="w")
        # Secondary line: pairing score (the optimizer's weighted signal) for
        # users who want the deeper metric
        tk.Label(hdr, text=f"Pairing score: {repeat_score}  (optimizer's weighted adjacency score)",
                 font=theme.FONT_SMALL, bg=theme.BG,
                 fg=theme.TEXT_DIM).pack(anchor="w")
        tk.Frame(win, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        by_table_id:  dict = defaultdict(list)
        by_seat_id:   dict = {}
        table_label_for_id: dict = {}
        for a in assignments:
            disp = a.get("student_display") or a["student_name"]
            by_table_id[a["table_id"]].append(disp)
            table_label_for_id[a["table_id"]] = a["table_label"]
            if a.get("seat_id") is not None:
                by_seat_id[a["seat_id"]] = disp

        # Disambiguate same-label tables
        by_table_display: dict = {}
        label_counts = defaultdict(int)
        for tid, lbl in table_label_for_id.items():
            label_counts[lbl] += 1
        label_suffix_counter = defaultdict(int)
        for tid in sorted(table_label_for_id.keys()):
            lbl = table_label_for_id[tid]
            if label_counts[lbl] > 1:
                label_suffix_counter[lbl] += 1
                display_label = f"{lbl} #{label_suffix_counter[lbl]}"
            else:
                display_label = lbl
            by_table_display[tid] = (display_label, by_table_id[tid])

        tab_bar     = tk.Frame(win, bg=theme.BG)
        tab_bar.pack(fill="x", padx=24, pady=(8, 0))
        tab_btns    = {}
        tab_content = tk.Frame(win, bg=theme.BG)
        tab_content.pack(fill="both", expand=True)
        layout_id = self.cls.get("layout_id")
        # Capture the class's seating mode to dispatch the canvas render.
        # The result window shows a round we just generated, so the class's
        # current mode is the right source (matches the round's stamped mode).
        round_mode = self.cls.get("seating_mode", "per_table")

        def switch(key):
            for k, b in tab_btns.items():
                active = (k == key)
                b.configure(bg=theme.ACCENT if active else theme.BG,
                            fg=theme.ACCENT_TEXT if active else theme.TEXT_DIM)
                b._btn_bg    = theme.ACCENT if active else theme.BG
                b._btn_hover = theme.ACCENT_DARK if active else theme.SEP
            for w in tab_content.winfo_children():
                w.destroy()
            if key == "list":
                app._render_table_list(tab_content, by_table_display)
            else:
                if not layout_id:
                    tk.Label(tab_content, text="No layout assigned.",
                             font=theme.FONT_BODY, bg=theme.BG,
                             fg=theme.TEXT_DIM).pack(pady=30)
                    return
                cf = tk.Frame(tab_content, bg=theme.CANVAS_BG)
                cf.pack(fill="both", expand=True, padx=24, pady=12)
                if round_mode == "per_table":
                    room = rc.RoomCanvas(cf, layout_id=layout_id,
                                          mode="view_roster",
                                          table_roster=dict(by_table_id))
                else:
                    room = rc.RoomCanvas(cf, layout_id=layout_id, mode="view",
                                          assignments=dict(by_seat_id))
                room.pack(fill="both", expand=True)
                room.after(50, room.load)
            win.update_idletasks()
            win.update()

        for lbl, key in [("  Table List  ", "list"), ("  Room View  ", "room")]:
            b = make_btn(tab_bar, lbl, command=lambda k=key: switch(k),
                         style="tab", padx=14, pady=7)
            b.pack(side="left")
            tab_btns[key] = b

        tk.Frame(win, bg=theme.SEP, height=1).pack(fill="x", padx=24)
        switch("list")


# ── Export Dialog ─────────────────────────────────────────────────────────────

class _ExportDialog(tk.Toplevel):
    def __init__(self, parent, rnd: dict, cls: dict):
        super().__init__(parent)
        self.rnd = rnd
        self.cls = cls
        self.title("Export Seating Chart PDF")
        self.geometry("460x340")
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Export PDF", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        # Label
        tk.Label(body, text="Chart label", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
        self.label_var = tk.StringVar(value=self.rnd["label"])
        styled_entry(body, textvariable=self.label_var, width=40).pack(
            anchor="w", pady=(4, 14))

        # Orientation — default pulled from user settings
        tk.Label(body, text="Page orientation", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
        default_orient = db.get_setting("default_pdf_orientation", "landscape")
        self.orient_var = tk.StringVar(value=default_orient)
        orient_row = tk.Frame(body, bg=theme.BG)
        orient_row.pack(anchor="w", pady=(4, 14))
        for text, val in [("Landscape", "landscape"), ("Portrait", "portrait")]:
            tk.Radiobutton(orient_row, text=text, variable=self.orient_var, value=val,
                           bg=theme.BG, fg=theme.TEXT,
                           activebackground=theme.BG, activeforeground=theme.TEXT,
                           selectcolor=theme.GHOST_BG,
                           font=theme.FONT_BODY).pack(side="left", padx=(0, 16))

        # Show score — default pulled from user settings
        default_score = db.get_setting("default_pdf_include_score", "0") == "1"
        self.score_var = tk.BooleanVar(value=default_score)
        tk.Checkbutton(body, text="Include pairing score on export",
                       variable=self.score_var,
                       bg=theme.BG, fg=theme.TEXT,
                       activebackground=theme.BG, activeforeground=theme.TEXT,
                       selectcolor=theme.GHOST_BG,
                       font=theme.FONT_BODY).pack(anchor="w", pady=(0, 20))

        # Buttons
        btn_row = tk.Frame(body, bg=theme.BG)
        btn_row.pack(fill="x")
        make_btn(btn_row, "Save PDF", self._save,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)

        self.status_lbl = tk.Label(body, text="", font=theme.FONT_SMALL,
                                   bg=theme.BG, fg=theme.TEXT_DIM)
        self.status_lbl.pack(anchor="w", pady=(10, 0))

    def _save(self):
        from tkinter import filedialog
        label = self.label_var.get().strip() or self.rnd["label"]

        # Default folder resolution:
        #   1. Explicit default_save_folder, if set and still exists
        #   2. last_save_folder (implicit memory), if set and still exists
        #   3. ~/Documents fallback baked into default_save_path()
        default_path = exporter.default_save_path(
            self.cls.get("name", "Class"), label)
        init_dir = os.path.dirname(default_path)
        explicit = db.get_setting("default_save_folder", "")
        if explicit and os.path.isdir(explicit):
            init_dir = explicit
        else:
            last_used = db.get_setting("last_save_folder", "")
            if last_used and os.path.isdir(last_used):
                init_dir = last_used

        out_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Seating Chart PDF",
            initialfile=os.path.basename(default_path),
            initialdir=init_dir,
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if not out_path:
            return

        self.status_lbl.configure(text="⏳ Generating PDF…", fg=theme.ACCENT)
        self.update()

        try:
            exporter.export_pdf(
                round_id     = self.rnd["id"],
                class_name   = self.cls.get("name", ""),
                layout_id    = self.cls["layout_id"],
                output_path  = out_path,
                label        = label,
                orientation  = self.orient_var.get(),
                show_score   = self.score_var.get(),
                repeat_score = self.rnd.get("repeat_score", 0),
                created_at   = self.rnd.get("created_at", ""),
                seating_mode = self.rnd.get("seating_mode", "per_seat"),
            )
            # Remember where the user saved, for next time.
            try:
                db.set_setting("last_save_folder", os.path.dirname(out_path))
            except Exception:
                pass
            self.status_lbl.configure(
                text=f"✓ Saved to {os.path.basename(out_path)}", fg=theme.SUCCESS)
            # Honour user preference for auto-open. Default on preserves the
            # original behaviour for existing users.
            if db.get_setting("open_pdf_after_export", "1") == "1":
                import subprocess, sys
                if sys.platform == "darwin":
                    subprocess.run(["open", out_path])
                elif sys.platform == "win32":
                    os.startfile(out_path)
                else:
                    subprocess.run(["xdg-open", out_path])
            self.after(1500, self.destroy)
        except Exception as e:
            self.status_lbl.configure(text=f"✗ Error: {e}", fg=theme.DANGER)


# ── Small Dialogs ─────────────────────────────────────────────────────────────

class _TableDialog(tk.Toplevel):
    def __init__(self, parent, title, existing_label="", existing_cap=4):
        super().__init__(parent)
        self.title(title)
        self.geometry("340x200")
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self.result = None
        self._build(existing_label, existing_cap)
        self.grab_set()

    def _build(self, label, cap):
        f = tk.Frame(self, bg=theme.BG, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="Table name", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).grid(row=0, column=0, sticky="w", pady=6)
        self.label_var = tk.StringVar(value=label)
        styled_entry(f, textvariable=self.label_var, width=22).grid(
            row=0, column=1, sticky="w", padx=10)
        tk.Label(f, text="Capacity", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).grid(row=1, column=0, sticky="w", pady=6)
        self.cap_var = tk.IntVar(value=cap)
        tk.Spinbox(f, from_=1, to=30, textvariable=self.cap_var, width=6,
                   font=theme.FONT_BODY, bg=theme.GHOST_BG, fg=theme.TEXT,
                   buttonbackground=theme.GHOST_BG, relief="flat",
                   highlightthickness=1, highlightbackground=theme.BORDER).grid(
            row=1, column=1, sticky="w", padx=10)
        btn_row = tk.Frame(f, bg=theme.BG)
        btn_row.grid(row=2, column=0, columnspan=2, pady=14)
        make_btn(btn_row, "Save",   self._save,    style="primary").pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,  style="ghost").pack(side="left", padx=10)

    def _save(self):
        label = self.label_var.get().strip()
        cap   = self.cap_var.get()
        if not label:
            messagebox.showwarning("Missing Name", "Enter a table name.", parent=self)
            return
        if cap < 1:
            messagebox.showwarning("Invalid Capacity", "Capacity must be at least 1.", parent=self)
            return
        self.result = (label, cap)
        self.destroy()


class _TablePresetDialog(tk.Toplevel):
    """Configurable add-table dialog. Lets the user set shape, size, and
    seat count with a live preview before adding to the layout. After a
    table is added, seats can be repositioned / added / removed directly
    on the canvas via the context menu."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Add Table")
        self.geometry("540x560")
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self.result = None
        self._build()
        self.grab_set()

    def _build(self):
        tk.Label(self, text="Add a Table", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Label(self,
                 text="Configure the table, then place and arrange seats on the canvas.",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 padx=24).pack(anchor="w")
        sep = tk.Frame(self, bg=theme.SEP, height=1)
        sep.pack(fill="x", padx=24)

        # Buttons FIRST (bottom-up packing rule). If body is packed with
        # expand=True before the button row, the buttons get pushed off-screen.
        btn_row = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "Add Table", self._save,
                 style="primary", padx=16, pady=8).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=16, pady=8).pack(side="left", padx=10)

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        # ── Name ─────────────────────────────────────────────────────────
        row1 = tk.Frame(body, bg=theme.BG)
        row1.pack(fill="x", pady=(0, 12))
        tk.Label(row1, text="Name", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=10, anchor="w").pack(side="left")
        self.name_var = tk.StringVar(value="Table")
        styled_entry(row1, textvariable=self.name_var, width=30).pack(
            side="left", padx=(8, 0))

        # ── Shape ────────────────────────────────────────────────────────
        row2 = tk.Frame(body, bg=theme.BG)
        row2.pack(fill="x", pady=(0, 12))
        tk.Label(row2, text="Shape", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=10, anchor="w").pack(side="left")
        self.shape_var = tk.StringVar(value="rect")

        def _shape_btn(label, value, icon):
            btn = tk.Frame(row2, bg=theme.PANEL,
                            highlightbackground=theme.BORDER,
                            highlightthickness=1, cursor="hand2")
            inner = tk.Label(btn, text=f"{icon}  {label}",
                             bg=theme.PANEL, fg=theme.TEXT,
                             font=theme.FONT_BODY, padx=14, pady=8)
            inner.pack()
            def _click(e=None):
                self.shape_var.set(value)
                self._refresh()
            btn.bind("<Button-1>", _click)
            inner.bind("<Button-1>", _click)
            return btn

        self._rect_btn  = _shape_btn("Rectangle", "rect",  "▭")
        self._rect_btn.pack(side="left", padx=(8, 6))
        self._round_btn = _shape_btn("Round",     "round", "⬤")
        self._round_btn.pack(side="left")

        # ── Size sliders ─────────────────────────────────────────────────
        sr = tk.Frame(body, bg=theme.BG)
        sr.pack(fill="x", pady=(0, 4))
        tk.Label(sr, text="Width", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=10, anchor="w").pack(side="left")
        self.width_var = tk.IntVar(value=140)
        tk.Scale(sr, from_=60, to=280, orient="horizontal",
                 variable=self.width_var, length=280, resolution=10,
                 bg=theme.BG, fg=theme.TEXT, troughcolor=theme.GHOST_BG,
                 highlightthickness=0, borderwidth=0,
                 command=lambda _=None: self._refresh()).pack(side="left", padx=(8, 0))

        hr = tk.Frame(body, bg=theme.BG)
        hr.pack(fill="x", pady=(0, 12))
        tk.Label(hr, text="Height", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=10, anchor="w").pack(side="left")
        self.height_var = tk.IntVar(value=90)
        tk.Scale(hr, from_=60, to=280, orient="horizontal",
                 variable=self.height_var, length=280, resolution=10,
                 bg=theme.BG, fg=theme.TEXT, troughcolor=theme.GHOST_BG,
                 highlightthickness=0, borderwidth=0,
                 command=lambda _=None: self._refresh()).pack(side="left", padx=(8, 0))

        # ── Seat count ───────────────────────────────────────────────────
        cr = tk.Frame(body, bg=theme.BG)
        cr.pack(fill="x", pady=(0, 12))
        tk.Label(cr, text="Seats", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=10, anchor="w").pack(side="left")
        self.cap_var = tk.IntVar(value=4)
        tk.Spinbox(cr, from_=0, to=30, textvariable=self.cap_var,
                   width=5, font=theme.FONT_BODY,
                   bg=theme.GHOST_BG, fg=theme.TEXT,
                   buttonbackground=theme.GHOST_BG, relief="flat",
                   highlightthickness=1, highlightbackground=theme.BORDER,
                   command=self._refresh).pack(side="left", padx=(8, 0))
        self.cap_var.trace_add("write", lambda *a: self._refresh())
        tk.Label(cr, text="(0 = decorative; no students will be seated here)",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM).pack(
            side="left", padx=(10, 0))

        # ── Preview ──────────────────────────────────────────────────────
        tk.Label(body, text="Preview", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(anchor="w", pady=(8, 4))
        self.preview = tk.Canvas(body, bg=theme.CANVAS_BG,
                                  width=440, height=180,
                                  highlightthickness=1,
                                  highlightbackground=theme.BORDER)
        self.preview.pack(anchor="w")

        # ── Buttons ──────────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "Add Table", self._save,
                 style="primary", padx=16, pady=8).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=16, pady=8).pack(side="left", padx=10)

        self._refresh()

    def _refresh(self):
        # Update shape-button highlight
        is_rect = self.shape_var.get() == "rect"
        self._rect_btn.configure(
            highlightbackground=theme.ACCENT if is_rect else theme.BORDER,
            highlightthickness=2 if is_rect else 1)
        self._round_btn.configure(
            highlightbackground=theme.ACCENT if not is_rect else theme.BORDER,
            highlightthickness=2 if not is_rect else 1)

        # Redraw preview
        self.preview.delete("all")
        cw, ch = 440, 180
        cx, cy = cw / 2, ch / 2

        try:
            w   = self.width_var.get()
            h   = self.height_var.get()
            cap = self.cap_var.get()
        except tk.TclError:
            return

        # Scale so preview fits comfortably (seats add ~44px each side)
        max_dim = max(w, h) + 100
        scale = min((cw - 40) / max_dim, (ch - 40) / max_dim, 1.0)
        dw, dh = w * scale, h * scale

        shape = self.shape_var.get()
        decorative = (cap == 0)
        fill = theme.GHOST_BG if decorative else theme.TABLE_BG
        if shape == "round":
            self.preview.create_oval(cx - dw/2, cy - dh/2,
                                      cx + dw/2, cy + dh/2,
                                      fill=fill, outline=theme.TABLE_BORDER, width=2)
        else:
            self.preview.create_rectangle(cx - dw/2, cy - dh/2,
                                           cx + dw/2, cy + dh/2,
                                           fill=fill, outline=theme.TABLE_BORDER, width=2)

        # Table name label inside
        self.preview.create_text(cx, cy, text=self.name_var.get() or "Table",
                                  fill=theme.TEXT_DIM,
                                  font=(theme.FONT_BOLD[0], 10, "bold"))

        # Preview seats (scaled with same scale)
        if not decorative and cap > 0:
            import math as _m
            seat_r = 10
            if shape == "round":
                r = max(dw, dh) / 2 + 22 * scale
                for i in range(cap):
                    a = (2 * _m.pi * i / cap) - _m.pi / 2
                    sx = cx + r * _m.cos(a)
                    sy = cy + r * _m.sin(a)
                    self.preview.create_oval(sx - seat_r, sy - seat_r,
                                              sx + seat_r, sy + seat_r,
                                              fill=theme.PANEL,
                                              outline=theme.SEAT_DOT, width=2)
            else:
                long_side = cap // 2
                remainder = cap % 2
                margin = 22 * scale
                if long_side > 0:
                    spacing = dw / long_side
                    for i in range(long_side):
                        sx = cx - dw/2 + spacing * (i + 0.5)
                        sy = cy - dh/2 - margin
                        self.preview.create_oval(sx - seat_r, sy - seat_r,
                                                  sx + seat_r, sy + seat_r,
                                                  fill=theme.PANEL,
                                                  outline=theme.SEAT_DOT, width=2)
                bc = long_side + remainder
                if bc > 0:
                    spacing = dw / bc
                    for i in range(bc):
                        sx = cx - dw/2 + spacing * (i + 0.5)
                        sy = cy + dh/2 + margin
                        self.preview.create_oval(sx - seat_r, sy - seat_r,
                                                  sx + seat_r, sy + seat_r,
                                                  fill=theme.PANEL,
                                                  outline=theme.SEAT_DOT, width=2)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Enter a table name.", parent=self)
            return
        try:
            cap = self.cap_var.get()
            w   = self.width_var.get()
            h   = self.height_var.get()
        except tk.TclError:
            messagebox.showwarning("Invalid Values", "Check the seat count.", parent=self)
            return
        self.result = {
            "label": name,
            "shape": self.shape_var.get(),
            "capacity": cap,
            "width": w,
            "height": h,
            "decorative": 1 if cap == 0 else 0,
        }
        self.destroy()


class _TableResizeDialog(tk.Toplevel):
    """Resize dialog for an existing table. Width/height sliders with a live
    preview. Unlike the add-table dialog, this one edits an existing table —
    the shape is fixed (change shape separately), and seats aren't shown in
    the preview since they're positioned independently on the canvas."""

    def __init__(self, parent, table: dict):
        super().__init__(parent)
        self.table  = table
        self.result = None   # Will be (width, height) on success
        self.title(f"Resize — {table.get('label', 'Table')}")
        self.geometry("440x400")
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self._build()
        self.grab_set()

    def _build(self):
        tk.Label(self, text=f"Resize {self.table.get('label', 'Table')}",
                 font=theme.FONT_TITLE, bg=theme.BG, fg=theme.TEXT,
                 padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Buttons FIRST (bottom-up packing rule)
        btn_row = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "Apply", self._save,
                 style="primary", padx=16, pady=8).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=16, pady=8).pack(side="left", padx=10)

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        # Width
        wr = tk.Frame(body, bg=theme.BG)
        wr.pack(fill="x", pady=(0, 4))
        tk.Label(wr, text="Width", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=8, anchor="w").pack(side="left")
        self.width_var = tk.IntVar(value=int(self.table.get("width") or 140))
        tk.Scale(wr, from_=60, to=280, orient="horizontal",
                 variable=self.width_var, length=280, resolution=10,
                 bg=theme.BG, fg=theme.TEXT, troughcolor=theme.GHOST_BG,
                 highlightthickness=0, borderwidth=0,
                 command=lambda _=None: self._refresh()).pack(side="left", padx=(8, 0))

        # Height
        hr = tk.Frame(body, bg=theme.BG)
        hr.pack(fill="x", pady=(0, 12))
        tk.Label(hr, text="Height", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT, width=8, anchor="w").pack(side="left")
        self.height_var = tk.IntVar(value=int(self.table.get("height") or 90))
        tk.Scale(hr, from_=60, to=280, orient="horizontal",
                 variable=self.height_var, length=280, resolution=10,
                 bg=theme.BG, fg=theme.TEXT, troughcolor=theme.GHOST_BG,
                 highlightthickness=0, borderwidth=0,
                 command=lambda _=None: self._refresh()).pack(side="left", padx=(8, 0))

        # Preview
        tk.Label(body, text="Preview", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(anchor="w", pady=(8, 4))
        self.preview = tk.Canvas(body, bg=theme.CANVAS_BG,
                                  width=380, height=160,
                                  highlightthickness=1,
                                  highlightbackground=theme.BORDER)
        self.preview.pack(anchor="w")

        self._refresh()

    def _refresh(self):
        self.preview.delete("all")
        cw, ch = 380, 160
        cx, cy = cw / 2, ch / 2
        try:
            w = self.width_var.get()
            h = self.height_var.get()
        except tk.TclError:
            return
        max_dim = max(w, h) + 20
        scale = min((cw - 40) / max_dim, (ch - 40) / max_dim, 1.0)
        dw, dh = w * scale, h * scale
        shape = self.table.get("shape") or "rect"
        decorative = bool(self.table.get("decorative"))
        fill = theme.GHOST_BG if decorative else theme.TABLE_BG
        if shape == "round":
            self.preview.create_oval(cx - dw/2, cy - dh/2,
                                      cx + dw/2, cy + dh/2,
                                      fill=fill, outline=theme.TABLE_BORDER, width=2)
        else:
            self.preview.create_rectangle(cx - dw/2, cy - dh/2,
                                           cx + dw/2, cy + dh/2,
                                           fill=fill, outline=theme.TABLE_BORDER, width=2)
        self.preview.create_text(cx, cy, text=f"{w} × {h}",
                                  fill=theme.TEXT_DIM,
                                  font=(theme.FONT_BOLD[0], 10, "bold"))

    def _save(self):
        try:
            w = self.width_var.get()
            h = self.height_var.get()
        except tk.TclError:
            return
        self.result = (w, h)
        self.destroy()


class _ClassDialog(tk.Toplevel):
    def __init__(self, parent, title, existing=None):
        super().__init__(parent)
        self.title(title)
        # Shorter (content sets height via pack), wider so wrap text fits.
        # Existing-class edits (no mode picker) fit in a smaller window.
        if existing:
            self.geometry("500x200")
        else:
            self.geometry("520x340")
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self.result = None
        self._build(existing)
        self.grab_set()

    def _build(self, existing):
        f = tk.Frame(self, bg=theme.BG, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="Class name", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).grid(row=0, column=0, sticky="w", pady=6)
        self.name_var = tk.StringVar(value=existing["name"] if existing else "")
        styled_entry(f, textvariable=self.name_var, width=26).grid(
            row=0, column=1, sticky="w", padx=10)
        tk.Label(f, text="Layout", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).grid(row=1, column=0, sticky="w", pady=6)
        layouts = db.get_all_layouts()
        self._layout_map = {l["name"]: l["id"] for l in layouts}
        self.layout_var  = tk.StringVar(
            value=existing["layout_name"] if existing and existing.get("layout_name") else "(none)")
        ttk.Combobox(f, textvariable=self.layout_var,
                     values=["(none)"] + [l["name"] for l in layouts],
                     state="readonly", width=24).grid(row=1, column=1, sticky="w", padx=10)

        # Seating mode picker — only visible when creating a new class.
        # Once a class has rounds, switching modes happens from the class
        # detail page (which shows consequences more clearly). For existing
        # classes, we hide this picker in the rename/edit dialog.
        self.mode_var = tk.StringVar(
            value=existing.get("seating_mode", "per_table") if existing else "per_table")
        if not existing:
            tk.Label(f, text="Seating mode", font=theme.FONT_BOLD,
                     bg=theme.BG, fg=theme.TEXT).grid(
                row=2, column=0, sticky="nw", pady=(12, 6))
            mode_frame = tk.Frame(f, bg=theme.BG)
            mode_frame.grid(row=2, column=1, sticky="w", padx=10, pady=(12, 6))
            tk.Radiobutton(
                mode_frame, text="Basic (per-table)",
                variable=self.mode_var, value="per_table",
                font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT,
                activebackground=theme.BG, activeforeground=theme.TEXT,
                selectcolor=theme.PANEL, anchor="w",
                highlightthickness=0, borderwidth=0).pack(anchor="w")
            tk.Label(mode_frame,
                     text="Students are assigned to tables. Simpler, faster.",
                     font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, wraplength=320,
                     justify="left").pack(anchor="w", padx=(22, 0), pady=(0, 6))
            tk.Radiobutton(
                mode_frame, text="Advanced (per-seat)",
                variable=self.mode_var, value="per_seat",
                font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT,
                activebackground=theme.BG, activeforeground=theme.TEXT,
                selectcolor=theme.PANEL, anchor="w",
                highlightthickness=0, borderwidth=0).pack(anchor="w")
            tk.Label(mode_frame,
                     text="Students are assigned to specific seats. Use this "
                          "when seat position matters (group work, labs, etc.).",
                     font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, wraplength=320,
                     justify="left").pack(anchor="w", padx=(22, 0))

        btn_row_idx = 3 if not existing else 2
        btn_row = tk.Frame(f, bg=theme.BG)
        btn_row.grid(row=btn_row_idx, column=0, columnspan=2, pady=(18, 0))
        make_btn(btn_row, "Save",   self._save,   style="primary").pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy, style="ghost").pack(side="left", padx=10)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Enter a class name.", parent=self)
            return
        layout_id = self._layout_map.get(self.layout_var.get(), None)
        mode = self.mode_var.get()
        self.result = (name, layout_id, mode)
        self.destroy()


# ── Student Name Dialog ───────────────────────────────────────────────────────

class _StudentNameDialog(tk.Toplevel):
    """Single-field dialog for adding or renaming a student.

    Parses the input into (first_name, last_name) using the same rules
    as the bulk importer (Last,First / First Last / mononym) and shows
    a live preview of how the name will be stored so the teacher can
    confirm before saving.

    Result interface (read after wait_window returns):
      - self.result: None if cancelled, else a dict with keys
        first_name, last_name, display.
    """
    def __init__(self, parent, title: str, prompt: str,
                 initial: str = "", ok_label: str = "Save"):
        super().__init__(parent)
        self.result: dict | None = None
        self._ok_label = ok_label
        self.title(title)
        self.geometry("440x260")
        self.configure(bg=theme.BG)
        self.resizable(True, False)
        self.grab_set()
        self._build(prompt, initial)

    def _build(self, prompt: str, initial: str):
        hdr = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text=self.title(), font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=prompt, font=theme.FONT_BODY,
                 bg=theme.BG, fg=theme.TEXT,
                 anchor="w", justify="left",
                 wraplength=380).pack(anchor="w", pady=(0, 4))
        dim_label(body,
                  "Accepts 'First Last', 'Last, First', or just a "
                  "first name.",
                  wraplength=380).pack(anchor="w", pady=(0, 8))

        self.entry = tk.Entry(body, font=theme.FONT_BODY,
                               bg=theme.GHOST_BG, fg=theme.TEXT,
                               insertbackground=theme.TEXT,
                               relief="flat", bd=0)
        self.entry.pack(fill="x", ipady=6)
        if initial:
            self.entry.insert(0, initial)
        self.entry.bind("<KeyRelease>", self._update_preview)
        self.entry.bind("<Return>",     lambda _e: self._save())
        self.entry.bind("<Escape>",     lambda _e: self.destroy())

        self.preview_lbl = tk.Label(body, text="", font=theme.FONT_SMALL,
                                     bg=theme.BG, fg=theme.TEXT_DIM,
                                     anchor="w", justify="left",
                                     wraplength=380)
        self.preview_lbl.pack(anchor="w", pady=(8, 0), fill="x")

        btn_row = tk.Frame(body, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x", pady=(14, 0))
        self.ok_btn = make_btn(btn_row, f"✓ {self._ok_label}",
                                self._save,
                                style="primary", padx=18, pady=9)
        self.ok_btn.pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)

        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self._update_preview()

    def _update_preview(self, *_):
        raw = self.entry.get().strip()
        if not raw:
            self.preview_lbl.configure(
                text="Type a name to see how it will be saved.",
                fg=theme.TEXT_DIM)
            self.ok_btn.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED)
            self.ok_btn._btn_bg    = theme.GHOST_BG
            self.ok_btn._btn_hover = theme.GHOST_BG
            return
        first, last = db.parse_name_input(raw)
        display = db.compose_full_name(first, last)
        if last:
            detail = f"First: {first}   ·   Last: {last}"
        else:
            detail = f"First: {first}   ·   (no last name)"
        self.preview_lbl.configure(
            text=f"Will save as:  {display}\n{detail}",
            fg=theme.TEXT)
        self.ok_btn.configure(bg=theme.ACCENT, fg=theme.ACCENT_TEXT)
        self.ok_btn._btn_bg    = theme.ACCENT
        self.ok_btn._btn_hover = theme.ACCENT_DARK

    def _save(self):
        raw = self.entry.get().strip()
        if not raw:
            return
        first, last = db.parse_name_input(raw)
        if not first and not last:
            return
        self.result = {
            "first_name": first,
            "last_name":  last,
            "display":    db.compose_full_name(first, last),
        }
        self.destroy()


# ── Bulk Import Dialog ────────────────────────────────────────────────────────

class _BulkImportDialog(tk.Toplevel):
    """
    Paste-a-list bulk student importer.
    Accepts one name per line, or names separated by commas.
    Shows a live preview of parsed names with duplicate detection.
    """
    def __init__(self, parent, class_id: int):
        super().__init__(parent)
        self.class_id       = class_id
        self.imported_count = 0
        self.title("Bulk Import Students")
        self.geometry("560x560")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        self.grab_set()

        # Pre-fetch existing names for duplicate detection
        self._existing = {s["name"].lower() for s in
                          db.get_students_for_class(class_id)}

        self._build()

    def _build(self):
        tk.Label(self, text="Bulk Import Students", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Paste student names below", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w")
        dim_label(body,
                  "One per line. 'Last, First' is reordered to natural "
                  "'First Last' form on save. Plain first names paste "
                  "as-is. Multiple names separated by commas on one "
                  "line split into individual students.",
                  wraplength=500,
                  justify="left").pack(anchor="w", pady=(2, 8), fill="x")

        # Pack bottom-up: buttons first, then summary, then text area last
        # (which fills remaining space). This prevents the text area from
        # pushing the buttons offscreen.
        btn_row = tk.Frame(body, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x", pady=(10, 0))
        self.import_btn = make_btn(btn_row, "Import", self._import,
                                    style="primary", padx=18, pady=9)
        self.import_btn.pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)

        self.summary_lbl = tk.Label(body, text="", font=theme.FONT_SMALL,
                                    bg=theme.BG, fg=theme.TEXT_DIM, anchor="w",
                                    justify="left")
        self.summary_lbl.pack(side="bottom", anchor="w", pady=(10, 4), fill="x")

        # Preview of the final display names (after Last,First reformat).
        # Shows up to 8 names with an overflow marker. Wraplength so
        # long previews word-wrap rather than getting clipped.
        self.preview_lbl = tk.Label(body, text="", font=theme.FONT_SMALL,
                                    bg=theme.BG, fg=theme.TEXT, anchor="w",
                                    justify="left", wraplength=510)
        self.preview_lbl.pack(side="bottom", anchor="w", pady=(4, 0), fill="x")

        # Text area (fills remaining space)
        text_frame = tk.Frame(body, bg=theme.BORDER, padx=1, pady=1)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, height=10, wrap="word",
                            bg=theme.GHOST_BG, fg=theme.TEXT,
                            insertbackground=theme.TEXT,
                            relief="flat", bd=0,
                            font=theme.FONT_BODY, padx=10, pady=8)
        self.text.pack(fill="both", expand=True)
        self.text.bind("<KeyRelease>", self._update_preview)

        self.text.focus_set()
        self._update_preview()

    def _parse_line(self, line: str) -> list[dict]:
        """Parse one input line into zero or more entry dicts with
        explicit first_name / last_name / display. The display field is
        the natural 'First Last' composition used for duplicate
        detection and preview rendering.

        Delegates to db.parse_name_input for the Last,First vs mononym
        heuristic. For lines with 3+ comma-separated tokens, treats
        each as its own student (separator mode)."""
        line = line.strip()
        if not line:
            return []
        # 3+ comma-separated non-empty tokens → separator mode
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
            non_empty = [p for p in parts if p]
            if len(non_empty) >= 3:
                entries = []
                for piece in non_empty:
                    first, last = db.parse_name_input(piece)
                    entries.append({
                        "first_name": first,
                        "last_name":  last,
                        "display":    db.compose_full_name(first, last),
                    })
                return entries
        # Otherwise defer to db.parse_name_input (handles Last,First,
        # First Last, mononym, and degenerate forms).
        first, last = db.parse_name_input(line)
        if not first and not last:
            return []
        return [{
            "first_name": first,
            "last_name":  last,
            "display":    db.compose_full_name(first, last),
        }]

    def _parse_names(self) -> tuple[list[dict], list[str], list[str]]:
        """
        Parse the text area. Returns (new_entries, duplicates_in_db, duplicates_in_list).
        - new_entries: list of dicts {first_name, last_name, display}
          ready to hand to db.bulk_add_students.
        - duplicates_in_db: display strings already present in the class
        - duplicates_in_list: display strings that appeared more than
          once in the paste
        """
        raw = self.text.get("1.0", "end")
        entries: list[dict] = []
        for line in raw.splitlines():
            entries.extend(self._parse_line(line))

        seen_lower  = set()
        new_entries = []
        dup_in_list = []
        dup_in_db   = []
        for e in entries:
            disp = e["display"]
            key = disp.lower()
            if key in self._existing:
                dup_in_db.append(disp)
            elif key in seen_lower:
                dup_in_list.append(disp)
            else:
                seen_lower.add(key)
                new_entries.append(e)

        return new_entries, dup_in_db, dup_in_list

    def _update_preview(self, *_):
        new_entries, dup_db, dup_list = self._parse_names()
        parts = []
        if new_entries:
            parts.append(f"✓ {len(new_entries)} new to import")
        if dup_db:
            parts.append(f"⚠ {len(dup_db)} already in roster (will skip)")
        if dup_list:
            parts.append(f"⚠ {len(dup_list)} duplicate in list (will skip)")
        if not parts:
            parts.append("Nothing to import yet.")

        color = theme.SUCCESS if new_entries and not (dup_db or dup_list) else \
                (theme.ACCENT if new_entries else theme.TEXT_DIM)
        self.summary_lbl.configure(text="   ·   ".join(parts), fg=color)

        # Name preview: show up to 8 parsed display names so the teacher
        # can see how 'Last, First' inputs were reordered to natural
        # 'First Last' form before importing.
        if new_entries:
            displays = [e["display"] for e in new_entries]
            preview = ", ".join(displays[:8])
            if len(displays) > 8:
                preview += f", + {len(displays) - 8} more"
            self.preview_lbl.configure(text=preview)
        else:
            self.preview_lbl.configure(text="")

        # Enable/disable Import button
        if new_entries:
            self.import_btn.configure(bg=theme.ACCENT, fg=theme.ACCENT_TEXT)
            self.import_btn._btn_bg    = theme.ACCENT
            self.import_btn._btn_hover = theme.ACCENT_DARK
        else:
            self.import_btn.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED)
            self.import_btn._btn_bg    = theme.GHOST_BG
            self.import_btn._btn_hover = theme.GHOST_BG

    def _import(self):
        new_entries, _, _ = self._parse_names()
        if not new_entries:
            return
        count = db.bulk_add_students(self.class_id, new_entries)
        self.imported_count = count
        self.destroy()


# ── Notes Editor Dialog ───────────────────────────────────────────────────────

class _NotesEditorDialog(tk.Toplevel):
    """
    Multi-line notes editor for a seating round.
    Save writes notes to DB; self.saved is True on a successful save.
    """
    def __init__(self, parent, rnd: dict):
        super().__init__(parent)
        self.rnd       = rnd
        self.saved     = False
        self.new_notes = ""
        self.title(f"Notes — {rnd['label']}")
        self.geometry("520x400")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Edit Notes", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        dim_label(body, f"Round: {self.rnd['label']}").pack(anchor="w", pady=(0, 8))

        # Pack buttons FIRST at the bottom so they always reserve space.
        # If we packed the text area first with fill="both" expand=True, it
        # would claim all remaining vertical space and hide the buttons.
        btn_row = tk.Frame(body, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x", pady=(12, 0))
        make_btn(btn_row, "Save", self._save,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)

        text_frame = tk.Frame(body, bg=theme.BORDER, padx=1, pady=1)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word",
                            bg=theme.GHOST_BG, fg=theme.TEXT,
                            insertbackground=theme.TEXT,
                            relief="flat", bd=0,
                            font=theme.FONT_BODY, padx=10, pady=8)
        self.text.pack(fill="both", expand=True)
        existing = self.rnd.get("notes") or ""
        if existing:
            self.text.insert("1.0", existing)
        self.text.focus_set()

    def _save(self):
        notes = self.text.get("1.0", "end").rstrip()
        try:
            db.update_round_notes(self.rnd["id"], notes)
            self.new_notes = notes
            self.saved     = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Could not save notes: {e}", parent=self)


# ── Pin Student Dialog ────────────────────────────────────────────────────────

class _PinStudentDialog(tk.Toplevel):
    """
    Pick where a student should be pinned.

    In per-table mode: pick a table (or "(not pinned)").
    In per-seat mode: pick a table AND optionally a specific seat within
    that table. Seat picker appears after a table is chosen.

    Inputs:
      - current_pin: existing pinned_table_id (or None)
      - current_seat: existing pinned_seat_id (or None)
      - mode: "per_seat" | "per_table" — controls whether the seat
        picker appears.

    Outputs (read on self.saved == True):
      - self.new_pin:      the chosen table_id, or None
      - self.new_seat_pin: the chosen seat_id, or None
    """
    def __init__(self, parent, student_name: str, layout_id: int,
                 current_pin: int | None, current_seat: int | None = None,
                 mode: str = "per_table",
                 class_id: int | None = None,
                 student_id: int | None = None):
        super().__init__(parent)
        self.student_name = student_name
        self.layout_id    = layout_id
        self.current_pin  = current_pin
        self.current_seat = current_seat
        self.mode         = mode
        self.class_id     = class_id
        self.student_id   = student_id
        self.saved        = False
        self.new_pin      = current_pin
        self.new_seat_pin = current_seat

        # Pre-compute conflict data: who has pinned what, excluding this
        # student (their own pin is not a conflict against themselves).
        #   _other_pins_by_seat:  {seat_id: other_student_name}
        #   _other_pins_by_table: {table_id: [other_student_name, ...]}
        #   _blocked_seats:       set of seat_ids not clickable
        #   _blocked_tables:      set of table_ids not clickable (full)
        self._other_pins_by_seat:  dict = {}
        self._other_pins_by_table: dict = {}
        self._blocked_seats:  set = set()
        self._blocked_tables: set = set()
        if class_id is not None:
            try:
                others = db.get_students_for_class(class_id,
                                                     active_only=False)
            except Exception:
                others = []
            for s in others:
                if student_id is not None and s["id"] == student_id:
                    continue
                seat_id  = s.get("pinned_seat_id")
                table_id = s.get("pinned_table_id")
                disp = s.get("display") or s["name"]
                if seat_id is not None:
                    self._other_pins_by_seat[seat_id] = disp
                    self._blocked_seats.add(seat_id)
                if table_id is not None:
                    self._other_pins_by_table.setdefault(
                        table_id, []).append(disp)
            # Table fullness: count other students pinned to each table;
            # if >= capacity, block it in per-table mode.
            try:
                tables = db.get_tables_for_layout(self.layout_id)
            except Exception:
                tables = []
            for t in tables:
                cap = t.get("capacity") or 0
                others_here = len(self._other_pins_by_table.get(t["id"],
                                                                     []))
                if cap > 0 and others_here >= cap:
                    self._blocked_tables.add(t["id"])

        self.title(f"Pin {student_name}")
        self.geometry("860x680")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        self.grab_set()
        self._build()

    def _build(self):
        if self.mode == "per_seat":
            self._build_per_seat()
        else:
            self._build_per_table()

    def _build_per_table(self):
        """Visual table picker for per-table classes.

        Full room canvas with tables clickable. Each table shows any
        students already pinned to it as a roster inside the shape,
        giving the teacher immediate context about who's already there.
        """
        # Header
        hdr = tk.Frame(self, bg=theme.BG, padx=24, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Pin {self.student_name}",
                 font=theme.FONT_TITLE, bg=theme.BG, fg=theme.TEXT).pack(
                     anchor="w")
        tk.Label(hdr,
                 text="Click a table to pin to it. Click it again to unpin.",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 anchor="w", justify="left", wraplength=780).pack(
                     anchor="w", pady=(2, 0))
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Bottom bar
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")
        self._status_lbl = tk.Label(
            bottom, text="", font=theme.FONT_SMALL,
            bg=theme.BG, fg=theme.TEXT_DIM, anchor="w",
            justify="left", wraplength=780)
        self._status_lbl.pack(side="bottom", anchor="w",
                                pady=(8, 0), fill="x")

        btn_row = tk.Frame(bottom, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "✓ Save", self._save,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)
        make_btn(btn_row, "Remove pin", self._clear_seat_pick,
                 style="ghost", padx=14, pady=9).pack(side="right")

        # Canvas area. Other students' table pins render as a roster
        # inside each table; tables at-capacity (from others' pins)
        # reject clicks via _on_canvas_table_click.
        canvas_frame = tk.Frame(self, bg=theme.CANVAS_BG)
        canvas_frame.pack(fill="both", expand=True, padx=24, pady=(4, 0))

        # Keep _tables populated for reference.
        self._tables = db.get_tables_for_layout(self.layout_id)

        self._room = rc.RoomCanvas(
            canvas_frame,
            layout_id=self.layout_id,
            mode="table_picker",
            table_roster=dict(self._other_pins_by_table),
            on_table_click=self._on_canvas_table_click,
        )
        self._room.selected_table_id = self.new_pin
        self._room.pack(fill="both", expand=True)
        self._room.after(50, self._room.load)
        self._update_status()

    def _build_per_seat(self):
        """Full-room canvas for per-seat classes.

        The canvas IS the interface — click any seat to pin to it. The
        underlying table pin is derived silently from the clicked seat.
        Clicking the already-pinned seat toggles the pin off entirely.
        """
        # Preload tables so _save can validate / derive table from seat.
        tables = db.get_tables_for_layout(self.layout_id)
        self._tables = [t for t in tables if not t.get("decorative")]

        # Header
        hdr = tk.Frame(self, bg=theme.BG, padx=24, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Pin {self.student_name}",
                 font=theme.FONT_TITLE, bg=theme.BG, fg=theme.TEXT).pack(
                     anchor="w")
        tk.Label(hdr,
                 text="Click a seat to pin to it. Click it again to unpin.",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 anchor="w", justify="left", wraplength=780).pack(
                     anchor="w", pady=(2, 0))
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Bottom bar: Save / Cancel / Remove pin + status
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")
        self._status_lbl = tk.Label(
            bottom, text="", font=theme.FONT_SMALL,
            bg=theme.BG, fg=theme.TEXT_DIM, anchor="w",
            justify="left", wraplength=780)
        self._status_lbl.pack(side="bottom", anchor="w",
                                pady=(8, 0), fill="x")

        btn_row = tk.Frame(bottom, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "✓ Save", self._save,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)
        make_btn(btn_row, "Remove pin", self._clear_seat_pick,
                 style="ghost", padx=14, pady=9).pack(side="right")

        # Canvas area. Other students' seat pins render as "occupied"
        # seats (seat looks taken, shows their name inside) and clicks
        # on them are rejected by _on_canvas_seat_click.
        canvas_frame = tk.Frame(self, bg=theme.CANVAS_BG)
        canvas_frame.pack(fill="both", expand=True, padx=24, pady=(4, 0))

        self._room = rc.RoomCanvas(
            canvas_frame,
            layout_id=self.layout_id,
            mode="assign",
            assignments=dict(self._other_pins_by_seat),
            on_seat_click=self._on_canvas_seat_click,
        )
        self._room.selected_seat_id = self.new_seat_pin
        self._room.pack(fill="both", expand=True)
        self._room.after(50, self._room.load)
        self._update_status()

    def _selected_table_id(self) -> int | None:
        """Used only by per-table mode (via the dropdown). Per-seat mode
        derives the table silently from the clicked seat in _save."""
        if not hasattr(self, "var"):
            return None
        selected = self.var.get()
        for t in self._tables:
            label = t["label"] if t["id"] is None \
                    else f"{t['label']}  (cap {t['capacity']})"
            if label == selected:
                return t["id"]
        return None

    def _on_canvas_seat_click(self, seat_id: int):
        """User clicked a seat. Blocked seats (pinned by another student)
        are ignored silently — the visual already shows the seat as
        occupied, so no further feedback is needed. Clicking the already-
        pinned seat unpins; clicking a new one moves the pin."""
        if seat_id in self._blocked_seats:
            return
        if seat_id == self.new_seat_pin:
            self.new_seat_pin = None
        else:
            self.new_seat_pin = seat_id
        self._room.selected_seat_id = self.new_seat_pin
        self._room._draw()
        self._update_status()

    def _on_canvas_table_click(self, table_id: int):
        """User clicked a table in the per-table picker. Blocked tables
        (at-capacity from other students' pins) are ignored silently."""
        if table_id in self._blocked_tables:
            return
        if table_id == self.new_pin:
            self.new_pin = None
        else:
            self.new_pin = table_id
        self._room.selected_table_id = self.new_pin
        self._room._draw()
        self._update_status()

    def _find_class_id_for_layout(self) -> int | None:
        """DEPRECATED — kept temporarily for backwards compatibility.
        Returns self.class_id (now passed in by the caller). Avoid in new
        code; the class id is authoritative only when explicitly provided."""
        return self.class_id

    def _clear_seat_pick(self):
        """'Remove pin' — clears the pin entirely in either mode."""
        self.new_seat_pin = None
        self.new_pin      = None
        if hasattr(self, "_room"):
            self._room.selected_seat_id  = None
            self._room.selected_table_id = None
            self._room._draw()
        self._update_status()

    def _update_status(self):
        """Refresh the status line at the bottom of the dialog."""
        if not hasattr(self, "_status_lbl"):
            return
        if self.mode == "per_seat":
            if self.new_seat_pin is not None:
                self._status_lbl.configure(
                    text="Will pin to this seat.",
                    fg=theme.ACCENT)
            else:
                self._status_lbl.configure(
                    text="No pin. Click a seat to pin to it.",
                    fg=theme.TEXT_DIM)
        else:
            if self.new_pin is not None:
                self._status_lbl.configure(
                    text="Will pin to this table.",
                    fg=theme.ACCENT)
            else:
                self._status_lbl.configure(
                    text="No pin. Click a table to pin to it.",
                    fg=theme.TEXT_DIM)

    def _save(self):
        """Commit the pick. In per-seat mode, derive the table from the
        chosen seat. In per-table mode, the table is already set from the
        canvas click; seat pin stays None."""
        if self.mode == "per_seat":
            if self.new_seat_pin is not None:
                all_seats = db.get_seats_for_layout(self.layout_id)
                seat = next((s for s in all_seats
                              if s["id"] == self.new_seat_pin), None)
                if seat is None:
                    self.new_pin = None
                    self.new_seat_pin = None
                else:
                    self.new_pin = seat["table_id"]
            else:
                self.new_pin = None
        else:
            # per-table mode — new_pin is set directly by canvas clicks
            self.new_seat_pin = None
        self.saved = True
        self.destroy()


# ── Constraints Dialog ────────────────────────────────────────────────────────

class _ConstraintsDialog(tk.Toplevel):
    """
    Manage never-together pair constraints for a class.
    self.changed = True if any constraint was added or removed (for cache
    invalidation by caller).
    """
    def __init__(self, parent, class_id: int):
        super().__init__(parent)
        self.class_id = class_id
        self.changed  = False
        self.title("Pair Rules")
        self.geometry("640x560")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        self.grab_set()
        # Hold picker references so we can query selected student ids
        self._picker_a = None
        self._picker_b = None
        self._build()
        self._refresh()

    def _build(self):
        tk.Label(self, text="Never-Together Pair Rules", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Bottom: Close button always visible
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")
        make_btn(bottom, "Close", self.destroy,
                 style="ghost", padx=14, pady=6).pack(side="right")

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        dim_label(body, "Students in a never-together pair will be kept at "
                        "separate tables when generating seating chart rounds."
                 ).pack(anchor="w", pady=(0, 10))

        self._students = db.get_students_for_class(self.class_id)

        # ── Add new pair ──────────────────────────────────────────────────────
        add_frame = tk.Frame(body, bg=theme.PANEL, padx=14, pady=12,
                             highlightbackground=theme.BORDER, highlightthickness=1)
        add_frame.pack(fill="x", pady=(0, 14))

        tk.Label(add_frame, text="Add a new pair:", font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w", pady=(0, 8))

        # Two-column grid: label + picker, label + picker
        grid = tk.Frame(add_frame, bg=theme.PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        tk.Label(grid, text="Student 1", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).grid(row=0, column=0,
                                                          sticky="w", pady=(0, 2))
        tk.Label(grid, text="Student 2", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).grid(row=0, column=1,
                                                          sticky="w", padx=(12, 0),
                                                          pady=(0, 2))

        picker_a_frame = tk.Frame(grid, bg=theme.PANEL)
        picker_a_frame.grid(row=1, column=0, sticky="ew")
        self._picker_a = _StudentPicker(picker_a_frame, self._students)
        self._picker_a.pack(fill="x")

        picker_b_frame = tk.Frame(grid, bg=theme.PANEL)
        picker_b_frame.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        self._picker_b = _StudentPicker(picker_b_frame, self._students)
        self._picker_b.pack(fill="x")

        # Add Rule button — own row below so it has room to breathe
        add_btn_row = tk.Frame(add_frame, bg=theme.PANEL)
        add_btn_row.pack(fill="x", pady=(10, 0))
        make_btn(add_btn_row, "+ Add Rule", self._add, style="primary",
                 padx=16, pady=7).pack(side="left")

        # ── Existing pairs list ───────────────────────────────────────────────
        tk.Label(body, text="Current rules:", font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).pack(anchor="w", pady=(0, 6))

        # Pack Remove button FIRST at the bottom of the list section so it
        # reserves space. If we packed the tree first with fill="both"
        # expand=True, it would consume all remaining space and push the
        # button off-screen.
        remove_row = tk.Frame(body, bg=theme.BG)
        remove_row.pack(side="bottom", fill="x", pady=(10, 0))
        self._remove_btn = make_btn(remove_row, "Remove Selected", self._remove,
                                     style="danger", padx=14, pady=6)
        self._remove_btn.pack(side="left")

        list_frame = tk.Frame(body, bg=theme.BG)
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, columns=("pair",), show="headings",
                                 height=8, selectmode="browse")
        self.tree.heading("pair", text="Pair")
        self.tree.column("pair", width=400, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Initial state: no selection -> button disabled
        self._set_remove_enabled(False)

    def _set_remove_enabled(self, enabled: bool):
        if enabled:
            self._remove_btn.configure(bg=theme.DANGER, fg=theme.ACCENT_TEXT,
                                        cursor="hand2")
            self._remove_btn._btn_bg    = theme.DANGER
            self._remove_btn._btn_hover = theme.DANGER_DARK
            self._remove_btn._command   = self._remove
        else:
            self._remove_btn.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED,
                                        cursor="")
            self._remove_btn._btn_bg    = theme.GHOST_BG
            self._remove_btn._btn_hover = theme.GHOST_BG
            self._remove_btn._command   = lambda: None

    def _on_tree_select(self, *_):
        self._set_remove_enabled(bool(self.tree.selection()))

    def _refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for c in db.get_pair_constraints(self.class_id):
            self.tree.insert("", "end", iid=str(c["id"]),
                             values=(f"{c['name_a']}   ✕   {c['name_b']}",))
        # Selection is cleared by the rebuild; reset button state to match
        if hasattr(self, "_remove_btn"):
            self._set_remove_enabled(False)

    def _add(self):
        a_id = self._picker_a.get_selected_id()
        b_id = self._picker_b.get_selected_id()
        if a_id is None or b_id is None:
            messagebox.showwarning("Pick Two Students",
                                   "Select a student in each box.", parent=self)
            return
        if a_id == b_id:
            messagebox.showwarning("Same Student",
                                   "Pick two different students.", parent=self)
            return
        db.add_pair_constraint(self.class_id, a_id, b_id, "never_together")
        self.changed = True
        self._picker_a.clear()
        self._picker_b.clear()
        self._refresh()

    def _remove(self):
        sel = self.tree.selection()
        if not sel:
            return
        constraint_id = int(sel[0])
        db.delete_pair_constraint(constraint_id)
        self.changed = True
        self._refresh()


# ── Stats Window ──────────────────────────────────────────────────────────────

class _StatsWindow(tk.Toplevel):
    """
    Full stats dashboard launched from the Rounds tab.
    Shows:
      - L1 headline metrics with confidence-labeled projection
      - L2 per-student section (dropdown -> who they've paired with / not)
      - L3 pairing heat map (N x N, click a cell for that pair's history)
    """
    def __init__(self, parent, class_id: int, cls: dict):
        super().__init__(parent)
        self.class_id = class_id
        self.cls      = cls
        self.title(f"📊  Stats — {cls['name']}")
        self.geometry("820x720")
        self.configure(bg=theme.BG)
        self.resizable(True, True)
        # Cache data once on open so we're not re-querying repeatedly
        self.stats    = db.get_pair_stats(class_id)
        self.students = db.get_students_for_class(class_id, active_only=False)
        self.name_by_id = {s["id"]: (s.get("display") or s["name"])
                           for s in self.students}
        self.active_by_id = {s["id"]: s["active"] for s in self.students}
        self._build()

    def _build(self):
        tk.Label(self, text=f"Statistics for {self.cls['name']}",
                 font=theme.FONT_TITLE, bg=theme.BG, fg=theme.TEXT,
                 padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Close button at bottom-fixed
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")
        make_btn(bottom, "Close", self.destroy,
                 style="ghost", padx=16, pady=7).pack(side="right")

        # Use a Text widget as the outer scroll container — native trackpad
        # scroll with freely-embedded widgets.
        body_container, body_text = make_text_scroll_container(
            self, padx=24, pady=12)
        body_container.pack(fill="both", expand=True)

        def add_block(w, pady_after=0):
            body_text.window_create("end", window=w, stretch=1)
            body_text.insert("end", "\n")
            if pady_after:
                sp = tk.Frame(body_text, bg=theme.BG, height=pady_after)
                body_text.window_create("end", window=sp)
                body_text.insert("end", "\n")

        # Block text editing but keep scroll
        body_text.bind("<Key>", lambda e: "break")
        body_text.bind("<Button-2>", lambda e: "break")

        # ── L1: Headline metrics ─────────────────────────────────────────
        l1 = self._build_metrics_section(body_text)
        add_block(l1, pady_after=16)

        # ── L2: Per-student pairings ─────────────────────────────────────
        l2 = self._build_student_section(body_text)
        add_block(l2, pady_after=16)

        # ── L3: Heat map ─────────────────────────────────────────────────
        l3 = self._build_heatmap_section(body_text)
        add_block(l3, pady_after=8)

    # ── L1 ────────────────────────────────────────────────────────────────

    def _build_metrics_section(self, parent):
        frame = tk.Frame(parent, bg=theme.PANEL,
                          highlightbackground=theme.BORDER, highlightthickness=1)
        inner = tk.Frame(frame, bg=theme.PANEL, padx=18, pady=14)
        inner.pack(fill="x")

        tk.Label(inner, text="Pairing Coverage", font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w")

        total  = self.stats["total_possible_pairs"]
        unique = self.stats["unique_pairs_seen"]
        pct    = (unique / total * 100) if total else 0

        # Big coverage number
        if total == 0:
            status = "Not enough students."
        elif unique == total:
            status = f"✓ All {total} possible pairs have sat together."
        else:
            status = f"{unique} of {total} unique pairs  —  {pct:.1f}% coverage"
        tk.Label(inner, text=status, font=theme.FONT_BODY,
                 bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w", pady=(6, 2))

        # Secondary details
        details = []
        details.append(f"Total rounds generated: {self.stats['total_rounds']}")
        details.append(f"Total pair-sharing events: {self.stats['total_pairings']}")

        mr = self.stats["most_repeated"]
        if mr:
            if mr["count"] == 1:
                details.append("Most repeated: no pair has sat together more than once yet")
            else:
                details.append(f"Most repeated: {mr['name_a']} + {mr['name_b']}  ({mr['count']} times)")

        for d in details:
            tk.Label(inner, text=d, font=theme.FONT_SMALL,
                     bg=theme.PANEL, fg=theme.TEXT_DIM).pack(anchor="w")

        # Momentum (replaces the old "projection" — we don't predict any more,
        # we describe what's happening)
        projection = self._compute_projection()
        if projection:
            tk.Frame(inner, bg=theme.SEP, height=1).pack(fill="x", pady=(10, 8))
            tk.Label(inner, text="Rotation momentum", font=theme.FONT_BOLD,
                     bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w")
            for line in projection:
                tk.Label(inner, text=line, font=theme.FONT_SMALL,
                         bg=theme.PANEL, fg=theme.TEXT_DIM).pack(anchor="w")

        return frame

    def _compute_projection(self) -> list:
        """
        Returns a list of human-readable status lines about rotation progress.

        The old implementation reported "N more rounds to full coverage"
        using a theoretical upper bound — but 100% coverage is rarely
        actually reachable in practice (attendance, constraints, optimizer
        tradeoffs), which made the metric feel like a perpetually-unmet
        goal. We replaced it with a descriptive momentum metric + a
        saturation descriptor that reframes high coverage + 0-new-pairings
        as the success state it is ("done", not "stuck").
        """
        total  = self.stats["total_possible_pairs"]
        unique = self.stats["unique_pairs_seen"]
        if total == 0 or unique == 0:
            return []

        rounds_for_class = db.get_rounds_for_class(self.class_id)
        if not rounds_for_class:
            return []

        lines = []
        pct = (unique / total * 100)
        # Mirror the class detail helper so thresholds stay in one place.
        # Reach into the owning app instance for the classmethod; if it
        # isn't present for some reason, degrade gracefully.
        descriptor = None
        try:
            descriptor = self.master._saturation_descriptor(pct)
        except Exception:
            descriptor = None

        # New pairings in the most recent round
        last_rid = rounds_for_class[0]["id"]
        try:
            last_new = db.count_new_pairs_in_round(self.class_id, last_rid)
        except Exception:
            last_new = None

        if last_new is not None:
            prefix = f"{descriptor}. " if descriptor else ""
            if last_new == 0:
                # At high saturation, "0 new" is the natural end-state, not
                # a stall. The descriptor carries the tone.
                if pct >= 90:
                    lines.append(
                        f"• {prefix}0 new pairings in your last round — most "
                        f"connections have already formed.")
                else:
                    # Low coverage + 0 new = actual stall. Say so gently but
                    # honestly so the teacher knows to check constraints /
                    # attendance.
                    lines.append(
                        f"• {prefix}0 new pairings in your last round. This "
                        f"can happen if the same students are absent each "
                        f"round or if constraints are tight.")
            else:
                plural = "s" if last_new != 1 else ""
                lines.append(
                    f"• {prefix}{last_new} new pairing{plural} added in your "
                    f"last round.")

        # Recent trend: average new pairings over the last 3 rounds
        recent_ids = [r["id"] for r in rounds_for_class[:3]]
        if len(recent_ids) >= 2:
            try:
                recent_counts = [db.count_new_pairs_in_round(self.class_id, rid)
                                   for rid in recent_ids]
                avg_recent = sum(recent_counts) / len(recent_counts)
                if avg_recent > 0:
                    lines.append(
                        f"• Averaging {avg_recent:.1f} new pairings per round "
                        f"across your last {len(recent_counts)} rounds.")
            except Exception:
                pass

        # Coverage context — framed as success states, not deficits
        if pct >= 96:
            lines.append(
                "• At this level of saturation, remaining pairings are the "
                "hardest to form — some may never happen due to constraints "
                "or schedules. That's fine.")
        elif pct >= 75:
            lines.append(
                "• Most students have sat with most of their classmates "
                "at least once.")

        return lines

    # ── L2 ────────────────────────────────────────────────────────────────

    def _build_student_section(self, parent):
        frame = tk.Frame(parent, bg=theme.PANEL,
                          highlightbackground=theme.BORDER, highlightthickness=1)
        inner = tk.Frame(frame, bg=theme.PANEL, padx=18, pady=14)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="Per-Student Pairings", font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w")
        tk.Label(inner, text="Select a student to see who they have and haven't sat with.",
                 font=theme.FONT_SMALL, bg=theme.PANEL,
                 fg=theme.TEXT_DIM).pack(anchor="w", pady=(2, 8))

        # Picker row
        picker_row = tk.Frame(inner, bg=theme.PANEL)
        picker_row.pack(fill="x")
        tk.Label(picker_row, text="Student:", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT).pack(side="left", padx=(0, 8))
        student_names = [s.get("display") or s["name"] for s in self.students]
        self._student_var = tk.StringVar()
        picker = ttk.Combobox(picker_row, textvariable=self._student_var,
                               values=student_names, state="readonly", width=30)
        picker.pack(side="left")
        picker.bind("<<ComboboxSelected>>", self._on_student_selected)

        # Results area (populated on selection)
        self._student_results = tk.Frame(inner, bg=theme.PANEL)
        self._student_results.pack(fill="both", expand=True, pady=(12, 0))
        tk.Label(self._student_results,
                 text="(pick a student above)",
                 font=theme.FONT_SMALL, bg=theme.PANEL,
                 fg=theme.TEXT_MUTED).pack(anchor="w")

        return frame

    def _on_student_selected(self, _event=None):
        name = self._student_var.get()
        student = next((s for s in self.students
                          if (s.get("display") or s["name"]) == name), None)
        if not student:
            return
        data = db.get_student_pairings(self.class_id, student["id"])

        # Clear previous results
        for w in self._student_results.winfo_children():
            w.destroy()

        # Two-column layout: paired on left, never paired on right
        cols = tk.Frame(self._student_results, bg=theme.PANEL)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1, uniform="cols")
        cols.columnconfigure(1, weight=1, uniform="cols")

        # Left: paired, grouped by count
        paired_col = tk.Frame(cols, bg=theme.PANEL)
        paired_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Label(paired_col,
                 text=f"Has sat with ({len(data['paired'])})",
                 font=theme.FONT_BOLD, bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w")
        if not data["paired"]:
            tk.Label(paired_col, text="(nobody yet)",
                     font=theme.FONT_SMALL, bg=theme.PANEL,
                     fg=theme.TEXT_MUTED).pack(anchor="w", pady=(4, 0))
        else:
            # Group by count (highest first)
            from collections import defaultdict
            groups: dict = defaultdict(list)
            for p in data["paired"]:
                groups[p["count"]].append(p)
            for cnt in sorted(groups.keys(), reverse=True):
                tk.Label(paired_col,
                         text=f"  {cnt}× together:",
                         font=theme.FONT_SMALL, bg=theme.PANEL,
                         fg=theme.TEXT_DIM).pack(anchor="w", pady=(6, 2))
                for p in groups[cnt]:
                    dim = not self.active_by_id.get(p["id"], True)
                    fg  = theme.TEXT_MUTED if dim else theme.TEXT
                    suffix = "  (inactive)" if dim else ""
                    tk.Label(paired_col, text=f"      • {p['name']}{suffix}",
                             font=theme.FONT_BODY, bg=theme.PANEL,
                             fg=fg).pack(anchor="w")

        # Right: never paired
        never_col = tk.Frame(cols, bg=theme.PANEL)
        never_col.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        tk.Label(never_col,
                 text=f"Has NOT sat with ({len(data['never_paired'])})",
                 font=theme.FONT_BOLD, bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w")
        if not data["never_paired"]:
            tk.Label(never_col, text="(sat with everyone!)",
                     font=theme.FONT_SMALL, bg=theme.PANEL,
                     fg=theme.SUCCESS).pack(anchor="w", pady=(4, 0))
        else:
            for p in data["never_paired"]:
                dim = not self.active_by_id.get(p["id"], True)
                fg  = theme.TEXT_MUTED if dim else theme.TEXT
                suffix = "  (inactive)" if dim else ""
                tk.Label(never_col, text=f"  • {p['name']}{suffix}",
                         font=theme.FONT_BODY, bg=theme.PANEL,
                         fg=fg).pack(anchor="w", pady=1)

    # ── L3: Heat Map ──────────────────────────────────────────────────────

    def _build_heatmap_section(self, parent):
        frame = tk.Frame(parent, bg=theme.PANEL,
                          highlightbackground=theme.BORDER, highlightthickness=1)
        inner = tk.Frame(frame, bg=theme.PANEL, padx=18, pady=14)
        inner.pack(fill="x")

        tk.Label(inner, text="Pairing Heat Map", font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT).pack(anchor="w")
        tk.Label(inner,
                 text="Each cell shows how many times a pair has sat together. "
                      "Click a cell to see the rounds they shared.",
                 font=theme.FONT_SMALL, bg=theme.PANEL,
                 fg=theme.TEXT_DIM).pack(anchor="w", pady=(2, 10))

        # Sort students alphabetically for deterministic grid
        sorted_students = sorted(
            self.students,
            key=lambda s: (s.get("display") or s["name"]).lower())
        N = len(sorted_students)
        if N < 2:
            tk.Label(inner, text="(need at least 2 students)",
                     font=theme.FONT_SMALL, bg=theme.PANEL,
                     fg=theme.TEXT_MUTED).pack(anchor="w")
            return frame

        # Cell size adapts to class size so huge classes still fit
        cell = 28 if N <= 20 else (22 if N <= 30 else 18)
        # Reserve horizontal space for row labels based on longest display
        max_name_len = max(len(s.get("display") or s["name"])
                           for s in sorted_students)
        label_w = max(60, min(140, 8 * max_name_len))
        # Reserve vertical space for rotated column labels. At 45° rotation,
        # the text extent vertically is roughly the text's horizontal length
        # times sin(45°) ≈ 0.71, plus padding. Cap truncated names at 12 chars.
        import math as _math
        max_col_chars = min(12, max_name_len)
        label_h = int(max_col_chars * 8 * _math.sin(_math.radians(45))) + 16

        canvas_w = label_w + cell * N + 20
        canvas_h = label_h + cell * N + 20

        canvas = tk.Canvas(inner, bg=theme.PANEL, width=canvas_w,
                            height=canvas_h, highlightthickness=0)
        canvas.pack()

        # Find max pair count to scale colors
        max_count = max(self.stats["pair_counts"].values(), default=0)

        def color_for(count: int) -> str:
            """Return a hex color for a pair count from 0 to max_count."""
            if count == 0 or max_count == 0:
                return theme.BG
            # Interpolate from PANEL (bg) to ACCENT
            t = min(1.0, count / max_count)
            # Parse accent and panel as hex
            def hex_to_rgb(h):
                h = h.lstrip("#")
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            bg = hex_to_rgb(theme.GHOST_BG)
            fg = hex_to_rgb(theme.ACCENT)
            r = int(bg[0] + (fg[0] - bg[0]) * t)
            g = int(bg[1] + (fg[1] - bg[1]) * t)
            b = int(bg[2] + (fg[2] - bg[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"

        # Draw column labels — rotated 45° with SW anchor so the text's
        # bottom-left sits right above each column's center. The text then
        # extends up and to the right, fitting neatly into the triangle of
        # space above the grid.
        for j, s in enumerate(sorted_students):
            # Anchor point: above the column, slightly left of center so
            # rotated text visually centers on the column
            x = label_w + j * cell + cell // 2 - 4
            y = label_h - 4
            active = s["active"]
            fg = theme.TEXT if active else theme.TEXT_MUTED
            full = s.get("display") or s["name"]
            txt = full if len(full) <= 12 else full[:11] + "…"
            canvas.create_text(x, y, text=txt, angle=45, anchor="sw",
                                font=theme.FONT_SMALL, fill=fg)

        # Draw row labels
        for i, s in enumerate(sorted_students):
            y = label_h + i * cell + cell // 2
            active = s["active"]
            fg = theme.TEXT if active else theme.TEXT_MUTED
            full = s.get("display") or s["name"]
            txt = full if len(full) <= 12 else full[:11] + "…"
            canvas.create_text(label_w - 4, y, text=txt, anchor="e",
                                font=theme.FONT_SMALL, fill=fg)

        # Draw cells
        pair_counts = self.stats["pair_counts"]
        for i, s_i in enumerate(sorted_students):
            for j, s_j in enumerate(sorted_students):
                x1 = label_w + j * cell
                y1 = label_h + i * cell
                x2 = x1 + cell
                y2 = y1 + cell
                if i == j:
                    # Diagonal — can't pair with yourself
                    canvas.create_rectangle(x1, y1, x2, y2,
                                             fill=theme.SEP, outline=theme.PANEL)
                    continue
                a, b = sorted([s_i["id"], s_j["id"]])
                count = pair_counts.get((a, b), 0)
                fill  = color_for(count)
                rect  = canvas.create_rectangle(x1, y1, x2, y2,
                                                 fill=fill, outline=theme.PANEL,
                                                 tags=(f"cell_{a}_{b}",))
                # Show count number if >= 2 (otherwise the color carries it)
                if count >= 2:
                    # Choose text color based on cell brightness
                    tc = theme.ACCENT_TEXT if count / max(max_count, 1) > 0.5 else theme.TEXT
                    canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2,
                                        text=str(count), font=theme.FONT_SMALL,
                                        fill=tc, tags=(f"cell_{a}_{b}",))
                # Click handler
                def on_click(event, pa=a, pb=b):
                    self._show_pair_history(pa, pb)
                canvas.tag_bind(f"cell_{a}_{b}", "<Button-1>", on_click)

        # Color legend
        legend_row = tk.Frame(inner, bg=theme.PANEL)
        legend_row.pack(anchor="w", pady=(10, 0))
        tk.Label(legend_row, text="Legend:", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 8))
        if max_count > 0:
            for step in range(min(max_count, 5) + 1):
                cnt = step
                swatch = tk.Frame(legend_row, bg=color_for(cnt),
                                   width=24, height=18,
                                   highlightbackground=theme.BORDER,
                                   highlightthickness=1)
                swatch.pack(side="left", padx=(6, 2))
                swatch.pack_propagate(False)
                tk.Label(legend_row, text=str(cnt),
                         font=theme.FONT_SMALL, bg=theme.PANEL,
                         fg=theme.TEXT_DIM).pack(side="left")

        return frame

    def _show_pair_history(self, student_a: int, student_b: int):
        """Popup showing rounds the pair shared a table."""
        rounds = db.get_rounds_for_pair(self.class_id, student_a, student_b)
        name_a = self.name_by_id.get(student_a, f"#{student_a}")
        name_b = self.name_by_id.get(student_b, f"#{student_b}")

        dlg = tk.Toplevel(self)
        dlg.title(f"{name_a} + {name_b}")
        dlg.geometry("460x380")
        dlg.configure(bg=theme.BG)
        dlg.transient(self)

        tk.Label(dlg, text=f"{name_a} + {name_b}",
                 font=theme.FONT_TITLE, bg=theme.BG, fg=theme.TEXT,
                 padx=20, pady=14).pack(anchor="w")
        tk.Frame(dlg, bg=theme.SEP, height=1).pack(fill="x", padx=20)

        bottom = tk.Frame(dlg, bg=theme.BG, padx=20, pady=12)
        bottom.pack(side="bottom", fill="x")
        make_btn(bottom, "Close", dlg.destroy,
                 style="ghost", padx=14, pady=6).pack(side="right")

        body = tk.Frame(dlg, bg=theme.BG, padx=20, pady=12)
        body.pack(fill="both", expand=True)

        if not rounds:
            tk.Label(body, text="They have never sat together.",
                     font=theme.FONT_BODY, bg=theme.BG,
                     fg=theme.TEXT_DIM).pack(anchor="w")
            return

        tk.Label(body,
                 text=f"They have shared a table in {len(rounds)} round{'s' if len(rounds) != 1 else ''}:",
                 font=theme.FONT_BODY, bg=theme.BG, fg=theme.TEXT).pack(anchor="w")

        list_frame = tk.Frame(body, bg=theme.BG)
        list_frame.pack(fill="both", expand=True, pady=(8, 0))
        tree = ttk.Treeview(list_frame,
                             columns=("label", "date", "table"),
                             show="headings", height=10)
        tree.heading("label", text="Round")
        tree.heading("date",  text="Date")
        tree.heading("table", text="Table")
        tree.column("label", width=180, anchor="w")
        tree.column("date",  width=120, anchor="w")
        tree.column("table", width=100, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        if len(rounds) > 10:
            sb.pack(side="right", fill="y")
        for r in rounds:
            tree.insert("", "end",
                         values=(r["label"],
                                 r["created_at"][:10] if r["created_at"] else "",
                                 r["table_label"] or ""))


# ── Assignment Editor Dialogs ──────────────────────────────────────────────────
# Two variants: one for per-seat rounds (canvas-based), one for per-table rounds
# (card-based). Dispatched at the call site based on rnd["seating_mode"].


class _AssignmentEditorDialogTableMode(tk.Toplevel):
    """
    Manual override editor for per-TABLE rounds. Simpler than the per-seat
    editor: students are grouped by table in cards, click to pick a student
    and click another student (or an empty slot) to swap/move. Seats are
    not tracked — every table has a capacity, not named seat identities.

    Data model: {table_id: [student_id, ...]}. An "empty slot" at a table
    exists when len(students) < table.capacity.

    Operations (all undoable):
    - Swap two students (either same-table, which is a visual no-op since
      seat positions don't matter, or cross-table)
    - Move a student from one table to an empty slot at another table

    Forbidden-pair and pinned-table warnings are preserved.
    """
    def __init__(self, parent, rnd: dict, cls: dict):
        super().__init__(parent)
        self.rnd     = rnd
        self.cls     = cls
        self.saved   = False
        self.new_repeat_score = rnd.get("repeat_score", 0)

        self.title(f"Edit Assignments — {rnd['label']}")
        self.geometry("780x680")
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()

        # Load tables + cap, then existing assignments grouped by table
        self.tables = db.get_tables_for_layout(cls["layout_id"])
        # Only tables that had students assigned in this round are editable.
        # Decorative tables shouldn't appear at all. Excluded-this-round
        # tables also shouldn't appear (students can't move to them).
        excluded_tids = set(rnd.get("excluded_tables") or [])
        self.tables = [t for t in self.tables
                        if not t.get("decorative")
                        and t["id"] not in excluded_tids]
        self.tables_by_id: dict = {t["id"]: t for t in self.tables}

        # Disambiguate duplicate labels for display
        from collections import Counter
        lbl_counts = Counter(t["label"] for t in self.tables)
        lbl_seen: dict = {}
        self.display_label: dict = {}
        for t in sorted(self.tables, key=lambda x: x["id"]):
            lbl = t["label"]
            if lbl_counts[lbl] > 1:
                lbl_seen[lbl] = lbl_seen.get(lbl, 0) + 1
                self.display_label[t["id"]] = f"{lbl} #{lbl_seen[lbl]}"
            else:
                self.display_label[t["id"]] = lbl

        # Working state: {table_id: [student_id, ...]}
        self.table_assignments: dict[int, list[int]] = {
            t["id"]: [] for t in self.tables}
        raw = db.get_assignments_for_round(rnd["id"])
        for a in raw:
            if a["table_id"] in self.table_assignments:
                self.table_assignments[a["table_id"]].append(a["student_id"])

        # Student roster
        students = db.get_students_for_class(cls["id"], active_only=False)
        self.name_by_id: dict = {s["id"]: (s.get("display") or s["name"])
                                  for s in students}
        self.pinned_by_id: dict = {
            s["id"]: s.get("pinned_table_id") for s in students}
        self.forbidden_pairs: set = set()
        for c in db.get_pair_constraints(cls["id"]):
            a, b = sorted([c["student_a"], c["student_b"]])
            self.forbidden_pairs.add((a, b))

        # Undo stack
        self._undo_stack: list = []
        # Click state: student_id currently picked up, or None
        self._picked_student_id: int | None = None

        self._build()
        self.bind_all("<Command-z>", lambda e: self._undo())
        self.bind_all("<Control-z>", lambda e: self._undo())
        self.bind_all("<Escape>",    lambda e: self._clear_picked())
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event):
        if event.widget is self:
            try:
                self.unbind_all("<Command-z>")
                self.unbind_all("<Control-z>")
                self.unbind_all("<Escape>")
            except tk.TclError:
                pass

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self):
        tk.Label(self, text="Edit Assignments", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Bottom: Save / Cancel + Undo + status
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")
        self.status_lbl = tk.Label(bottom, text="", font=theme.FONT_SMALL,
                                    bg=theme.BG, fg=theme.TEXT_DIM, anchor="w")
        self.status_lbl.pack(side="bottom", anchor="w", pady=(10, 0), fill="x")

        btn_row = tk.Frame(bottom, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "✓ Save Changes", self._save,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)
        self._undo_btn = make_btn(btn_row, "↶ Undo", lambda: None,
                                    style="ghost", padx=14, pady=9)
        self._undo_btn.pack(side="right")
        self._update_undo_button()

        # Instructions
        instr_frame = tk.Frame(self, bg=theme.BG, padx=24, pady=10)
        instr_frame.pack(fill="x")
        self.instr_lbl = tk.Label(
            instr_frame,
            text="Click a student to pick them up, then click another "
                 "student to swap or an empty slot to move. Esc cancels, Cmd+Z undoes.",
            font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM, anchor="w")
        self.instr_lbl.pack(anchor="w")

        # Body: scrollable container of table cards in a wrap grid
        container, self.body_frame = make_text_scroll_container(
            self, padx=0, pady=0)
        container.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        self.body_frame.bind("<Key>", lambda e: "break")
        self.body_frame.bind("<Button-2>", lambda e: "break")

        self._render_cards()

    def _render_cards(self):
        """Re-render every table card based on current state."""
        # Clear the body
        self.body_frame.configure(state="normal")
        self.body_frame.delete("1.0", "end")
        # Rebuild as a grid of card frames, two columns
        grid = tk.Frame(self.body_frame, bg=theme.BG)
        self.body_frame.window_create("end", window=grid)
        self.body_frame.configure(state="disabled")

        COLS = 2
        for i, t in enumerate(self.tables):
            row, col = divmod(i, COLS)
            card = self._build_table_card(grid, t)
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            grid.grid_columnconfigure(col, weight=1, uniform="col")

    def _build_table_card(self, parent, t: dict) -> tk.Frame:
        tid = t["id"]
        cap = t["capacity"]
        sids = self.table_assignments.get(tid, [])
        occupied = len(sids)

        card = tk.Frame(parent, bg=theme.PANEL,
                         highlightbackground=theme.BORDER,
                         highlightthickness=1)
        inner = tk.Frame(card, bg=theme.PANEL, padx=12, pady=10)
        inner.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(inner, bg=theme.PANEL)
        hdr.pack(fill="x", pady=(0, 4))
        tk.Label(hdr, text=self.display_label[tid], font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.TEXT, anchor="w").pack(side="left")
        tk.Label(hdr, text=f"  ({occupied}/{cap})", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM, anchor="w").pack(side="left")

        # Student rows
        for sid in sids:
            self._build_student_row(inner, sid, tid)

        # Empty slots (visible + clickable only if a student is picked up)
        empty_slots = cap - occupied
        for _ in range(empty_slots):
            self._build_empty_row(inner, tid)

        return card

    def _build_student_row(self, parent, sid: int, tid: int):
        name = self.name_by_id.get(sid, f"#{sid}")
        is_picked = (sid == self._picked_student_id)
        bg = theme.ACCENT if is_picked else theme.PANEL
        fg = theme.ACCENT_TEXT if is_picked else theme.TEXT
        prefix = "→  " if is_picked else "•  "

        pin_tbl = self.pinned_by_id.get(sid)
        pin_suffix = ""
        if pin_tbl is not None:
            pin_suffix = " 📌" if pin_tbl == tid else " 📌!"

        row = tk.Frame(parent, bg=bg, padx=6, pady=2, cursor="hand2")
        row.pack(fill="x", pady=1)
        lbl = tk.Label(row, text=f"{prefix}{name}{pin_suffix}",
                        font=theme.FONT_BODY, bg=bg, fg=fg, anchor="w",
                        cursor="hand2")
        lbl.pack(fill="x")
        def on_click(_e=None, s=sid, t=tid):
            self._on_student_click(s, t)
        for w in (row, lbl):
            w.bind("<Button-1>", on_click)

    def _build_empty_row(self, parent, tid: int):
        # Show the empty slot only as a meaningful target when a student is
        # picked up. Otherwise render a subtle placeholder so the card
        # capacity is visible but the slot looks inactive.
        active = self._picked_student_id is not None
        if active:
            bg = theme.GHOST_BG
            fg = theme.ACCENT
            text = "+  place here"
            cursor = "hand2"
        else:
            bg = theme.PANEL
            fg = theme.TEXT_MUTED
            text = "○  empty"
            cursor = ""
        row = tk.Frame(parent, bg=bg, padx=6, pady=2, cursor=cursor)
        row.pack(fill="x", pady=1)
        lbl = tk.Label(row, text=text, font=theme.FONT_SMALL,
                        bg=bg, fg=fg, anchor="w", cursor=cursor)
        lbl.pack(fill="x")
        if active:
            def on_click(_e=None, t=tid):
                self._on_empty_click(t)
            for w in (row, lbl):
                w.bind("<Button-1>", on_click)

    # ── Click handling ────────────────────────────────────────────────────

    def _on_student_click(self, sid: int, tid: int):
        if self._picked_student_id is None:
            # Pick up
            self._picked_student_id = sid
            name = self.name_by_id.get(sid, f"#{sid}")
            self.instr_lbl.configure(
                text=f"Picked up {name}. Click another student to swap, or "
                     f"click an empty slot to move them. Esc cancels.",
                fg=theme.ACCENT)
            self._render_cards()
        elif sid == self._picked_student_id:
            # Clicking the same student cancels
            self._clear_picked()
        else:
            # Swap two students
            self._swap_students(self._picked_student_id, sid)

    def _on_empty_click(self, target_tid: int):
        if self._picked_student_id is None:
            return
        self._move_student_to_table(self._picked_student_id, target_tid)

    def _clear_picked(self):
        self._picked_student_id = None
        self.instr_lbl.configure(
            text="Click a student to pick them up, then click another "
                 "student to swap or an empty slot to move. Esc cancels, Cmd+Z undoes.",
            fg=theme.TEXT_DIM)
        self._render_cards()

    # ── Operations ────────────────────────────────────────────────────────

    def _swap_students(self, sid_a: int, sid_b: int):
        """Swap two students between their tables (or same table = no-op)."""
        # Find current tables
        tid_a = self._table_of(sid_a)
        tid_b = self._table_of(sid_b)
        if tid_a is None or tid_b is None:
            self._clear_picked()
            return
        if tid_a == tid_b:
            # Same table — swap has no effect in per-table mode. Just clear.
            self.status_lbl.configure(
                text="Those students are already at the same table.",
                fg=theme.TEXT_DIM)
            self._clear_picked()
            return

        warnings = self._check_warnings(sid_a, tid_a, sid_b, tid_b)
        if warnings and not self._confirm_warnings(warnings):
            self._clear_picked()
            return

        # Perform: remove each, add to the other table
        self.table_assignments[tid_a].remove(sid_a)
        self.table_assignments[tid_b].remove(sid_b)
        self.table_assignments[tid_a].append(sid_b)
        self.table_assignments[tid_b].append(sid_a)

        name_a = self.name_by_id.get(sid_a, f"#{sid_a}")
        name_b = self.name_by_id.get(sid_b, f"#{sid_b}")
        desc = f"Swap {name_a} ↔ {name_b}"

        def _reverse(a=sid_a, b=sid_b, ta=tid_a, tb=tid_b):
            self.table_assignments[ta].remove(b)
            self.table_assignments[tb].remove(a)
            self.table_assignments[ta].append(a)
            self.table_assignments[tb].append(b)
        self._undo_stack.append((_reverse, desc))

        self._clear_picked()
        self._update_undo_button()

    def _move_student_to_table(self, sid: int, target_tid: int):
        """Move a student from their current table to an empty slot at
        target_tid. Fails quietly if target is at capacity."""
        src_tid = self._table_of(sid)
        if src_tid is None:
            self._clear_picked()
            return
        if src_tid == target_tid:
            # No-op
            self._clear_picked()
            return
        # Capacity check
        target_cap = self.tables_by_id[target_tid]["capacity"]
        if len(self.table_assignments[target_tid]) >= target_cap:
            messagebox.showwarning(
                "Table Full",
                f"{self.display_label[target_tid]} has no empty slots.",
                parent=self)
            self._clear_picked()
            return

        warnings = self._check_warnings(sid, src_tid, None, target_tid)
        if warnings and not self._confirm_warnings(warnings):
            self._clear_picked()
            return

        self.table_assignments[src_tid].remove(sid)
        self.table_assignments[target_tid].append(sid)

        name = self.name_by_id.get(sid, f"#{sid}")
        src_lbl = self.display_label[src_tid]
        tgt_lbl = self.display_label[target_tid]
        desc = f"Move {name}: {src_lbl} → {tgt_lbl}"

        def _reverse(s=sid, src=src_tid, tgt=target_tid):
            self.table_assignments[tgt].remove(s)
            self.table_assignments[src].append(s)
        self._undo_stack.append((_reverse, desc))

        self._clear_picked()
        self._update_undo_button()

    def _table_of(self, sid: int) -> int | None:
        for tid, sids in self.table_assignments.items():
            if sid in sids:
                return tid
        return None

    # ── Warnings ──────────────────────────────────────────────────────────

    def _check_warnings(self, sid_a, tid_a, sid_b, tid_b) -> list:
        """Collect human-readable warnings about a pending swap/move.
        sid_b may be None (moving to an empty slot)."""
        warnings = []

        def pin_violation(sid, new_tbl):
            if sid is None:
                return None
            pinned = self.pinned_by_id.get(sid)
            if pinned is not None and pinned != new_tbl:
                name = self.name_by_id.get(sid, f"#{sid}")
                tbl_lbl = self.display_label.get(pinned, f"Table #{pinned}")
                return (f"📌 {name} is pinned to {tbl_lbl}. "
                        f"This move violates that pin.")
            return None

        v = pin_violation(sid_a, tid_b)
        if v: warnings.append(v)
        v = pin_violation(sid_b, tid_a)
        if v: warnings.append(v)

        # Forbidden pairs at destination tables
        def students_at_table_after(target_tbl):
            result = set(self.table_assignments[target_tbl])
            if sid_a is not None and tid_a == target_tbl:
                result.discard(sid_a)
            if sid_b is not None and tid_b == target_tbl:
                result.discard(sid_b)
            if sid_a is not None and tid_b == target_tbl:
                result.add(sid_a)
            if sid_b is not None and tid_a == target_tbl:
                result.add(sid_b)
            return result

        def check_forbidden_at(target_tbl):
            students_here = students_at_table_after(target_tbl)
            for a, b in self.forbidden_pairs:
                if a in students_here and b in students_here:
                    name_a = self.name_by_id.get(a, f"#{a}")
                    name_b = self.name_by_id.get(b, f"#{b}")
                    tbl_lbl = self.display_label.get(target_tbl,
                                                       f"Table #{target_tbl}")
                    warnings.append(
                        f"🚫 {name_a} and {name_b} are marked never-together, "
                        f"but this puts them both at {tbl_lbl}.")

        if tid_a is not None:
            check_forbidden_at(tid_a)
        if tid_b is not None and tid_b != tid_a:
            check_forbidden_at(tid_b)

        return warnings

    def _confirm_warnings(self, warnings: list) -> bool:
        msg = "This change creates the following issue(s):\n\n"
        msg += "\n".join(f"  • {w}" for w in warnings)
        msg += "\n\nContinue anyway?"
        return messagebox.askyesno("Confirm Change", msg, parent=self)

    # ── Undo ──────────────────────────────────────────────────────────────

    def _undo(self):
        if not self._undo_stack:
            return
        reverse_fn, desc = self._undo_stack.pop()
        reverse_fn()
        self._clear_picked()
        self._update_undo_button()
        self.status_lbl.configure(text=f"Undid: {desc}", fg=theme.TEXT_DIM)

    def _update_undo_button(self):
        if not hasattr(self, "_undo_btn") or not self._undo_btn.winfo_exists():
            return
        if self._undo_stack:
            last_desc = self._undo_stack[-1][1]
            if len(last_desc) > 32:
                last_desc = last_desc[:29] + "…"
            self._undo_btn.configure(bg=theme.BG, fg=theme.TEXT, cursor="hand2",
                                      text=f"↶ Undo: {last_desc}")
            self._undo_btn._btn_bg    = theme.BG
            self._undo_btn._btn_hover = theme.SEP
            self._undo_btn._command   = self._undo
        else:
            self._undo_btn.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED,
                                      cursor="", text="↶ Undo")
            self._undo_btn._btn_bg    = theme.GHOST_BG
            self._undo_btn._btn_hover = theme.GHOST_BG
            self._undo_btn._command   = lambda: None

    # ── Save ──────────────────────────────────────────────────────────────

    def _save(self):
        if not self._undo_stack:
            self.destroy()
            return

        # Recompute pairing score against full history minus this round
        full_history = db.get_pair_history(self.cls["id"])
        on_disk = db.get_assignments_for_round(self.rnd["id"])
        on_disk_by_table: dict = defaultdict(list)
        for a in on_disk:
            on_disk_by_table[a["table_id"]].append(a["student_id"])
        prior_history = dict(full_history)
        for sids in on_disk_by_table.values():
            for i in range(len(sids)):
                for j in range(i + 1, len(sids)):
                    a, b = sorted([sids[i], sids[j]])
                    prior_history[(a, b)] = prior_history.get((a, b), 0) - 1
                    if prior_history[(a, b)] <= 0:
                        del prior_history[(a, b)]

        repeat_score = 0
        for sids in self.table_assignments.values():
            for i in range(len(sids)):
                for j in range(i + 1, len(sids)):
                    a, b = sorted([sids[i], sids[j]])
                    repeat_score += prior_history.get((a, b), 0)

        # Flatten. Per-table rounds keep seat_id=None.
        flat = []
        for tid, sids in self.table_assignments.items():
            for sid in sids:
                flat.append((sid, None, tid))

        db.replace_assignments(self.rnd["id"], flat,
                                mark_edited=True,
                                new_repeat_score=repeat_score)
        self.new_repeat_score = repeat_score
        self.saved = True
        self.destroy()


class _AssignmentEditorDialog(tk.Toplevel):
    """
    Manual override editor for a round's seat assignments.

    Uses the per-seat Room View canvas as the primary surface. Click a seat
    to pick up a student; click another seat to swap (or to move to the
    empty seat). Cmd+Z undoes within the session. Cancel discards all
    changes; Save writes the new arrangement to the DB with mark_edited=True.

    Data model is {seat_id: student_id}, one-to-one. Empty seats are
    represented by absence of the key (seat_id not in the dict).
    """
    def __init__(self, parent, rnd: dict, cls: dict):
        super().__init__(parent)
        self.rnd     = rnd
        self.cls     = cls
        self.saved   = False
        self.new_repeat_score = rnd.get("repeat_score", 0)

        self.title(f"Edit Assignments — {rnd['label']}")
        self.geometry("1100x780")
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()

        # Layout metadata
        self.tables = db.get_tables_for_layout(cls["layout_id"])
        self.tables_by_id = {t["id"]: t for t in self.tables}
        self.seats = db.get_seats_for_layout(cls["layout_id"])
        # Map seat_id → table_id for fast lookup in swap validation
        self.table_for_seat: dict[int, int] = {s["id"]: s["table_id"] for s in self.seats}

        # Working assignments: {seat_id: student_id}
        self.seat_to_student: dict[int, int] = {}
        raw = db.get_assignments_for_round(rnd["id"])
        # If seat_id is NULL on an assignment (legacy pre-per-seat data),
        # allocate a seat at its table on the fly so the editor has
        # something to render. These allocations become permanent on save.
        seats_by_table_remaining: dict[int, list] = defaultdict(list)
        for s in self.seats:
            seats_by_table_remaining[s["table_id"]].append(s["id"])
        # First pass: honor existing seat_ids
        for a in raw:
            if a.get("seat_id") is not None:
                self.seat_to_student[a["seat_id"]] = a["student_id"]
                if a["seat_id"] in seats_by_table_remaining.get(a["table_id"], []):
                    seats_by_table_remaining[a["table_id"]].remove(a["seat_id"])
        # Second pass: allocate any NULL-seat assignments to free seats
        for a in raw:
            if a.get("seat_id") is None:
                pool = seats_by_table_remaining.get(a["table_id"], [])
                if pool:
                    seat_id = pool.pop(0)
                    self.seat_to_student[seat_id] = a["student_id"]

        # Remember which students were in this round at load time. Used on
        # save to detect if any were unseated during this edit session —
        # saving with an unseated student would silently drop them from the
        # round, which is never the user's intent. Save is blocked until
        # they're re-seated or the edit is cancelled.
        self.initial_student_ids: set = set(self.seat_to_student.values())

        # Load student roster
        students = db.get_students_for_class(cls["id"], active_only=False)
        self.name_by_id = {s["id"]: (s.get("display") or s["name"])
                           for s in students}
        self.pinned_by_id = {s["id"]: s.get("pinned_table_id") for s in students}
        self.pinned_seat_by_id = {s["id"]: s.get("pinned_seat_id") for s in students}
        self.forbidden_pairs = set()
        for c in db.get_pair_constraints(cls["id"]):
            a, b = sorted([c["student_a"], c["student_b"]])
            self.forbidden_pairs.add((a, b))

        # Undo stack: list of (reverse_fn, description) tuples
        self._undo_stack: list = []
        # Click-selection state. Either _picked_seat_id OR _picked_student_id
        # is set, never both. None means "nothing picked yet."
        #   _picked_seat_id — a seat was clicked on the canvas (occupied or empty)
        #   _picked_student_id — an unseated student was clicked in the sidebar
        self._picked_seat_id: int | None = None
        self._picked_student_id: int | None = None

        self._build()
        self.bind_all("<Command-z>", lambda e: self._undo())
        self.bind_all("<Control-z>", lambda e: self._undo())
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event):
        if event.widget is self:
            try:
                self.unbind_all("<Command-z>")
                self.unbind_all("<Control-z>")
            except tk.TclError:
                pass

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self):
        tk.Label(self, text="Edit Assignments", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.TEXT, padx=24, pady=16).pack(anchor="w")
        tk.Frame(self, bg=theme.SEP, height=1).pack(fill="x", padx=24)

        # Bottom: Save / Cancel + Undo + status
        bottom = tk.Frame(self, bg=theme.BG, padx=24, pady=12)
        bottom.pack(side="bottom", fill="x")

        self.status_lbl = tk.Label(bottom, text="", font=theme.FONT_SMALL,
                                    bg=theme.BG, fg=theme.TEXT_DIM, anchor="w")
        self.status_lbl.pack(side="bottom", anchor="w", pady=(10, 0), fill="x")

        btn_row = tk.Frame(bottom, bg=theme.BG)
        btn_row.pack(side="bottom", fill="x")
        make_btn(btn_row, "✓ Save Changes", self._save,
                 style="primary", padx=18, pady=9).pack(side="left")
        make_btn(btn_row, "Cancel", self.destroy,
                 style="ghost", padx=18, pady=9).pack(side="left", padx=10)
        self._undo_btn = make_btn(btn_row, "↶ Undo", lambda: None,
                                    style="ghost", padx=14, pady=9)
        self._undo_btn.pack(side="right")
        self._update_undo_button()

        # Instructions
        instr_frame = tk.Frame(self, bg=theme.BG, padx=24, pady=10)
        instr_frame.pack(fill="x")
        self.instr_lbl = tk.Label(instr_frame,
                                    text="Click a seat to pick up that student (or an empty seat). "
                                         "Click another seat to swap or move. Esc cancels, Cmd+Z undoes.",
                                    font=theme.FONT_SMALL, bg=theme.BG,
                                    fg=theme.TEXT_DIM, anchor="w")
        self.instr_lbl.pack(anchor="w")

        # Body: canvas on the left, unassigned-student list on the right
        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        # Right sidebar: shows any students not currently in a seat (e.g.,
        # if a student was present but every seat happened to be taken,
        # which shouldn't normally happen, but we handle it)
        sidebar_frame = tk.Frame(body, bg=theme.BG)
        sidebar_frame.pack(side="right", fill="y", padx=(12, 0))
        tk.Label(sidebar_frame, text="Unseated",
                 font=theme.FONT_BOLD, bg=theme.BG, fg=theme.TEXT,
                 anchor="w").pack(fill="x", pady=(0, 6))
        self._unseated_frame = tk.Frame(sidebar_frame, bg=theme.PANEL,
                                          highlightbackground=theme.BORDER,
                                          highlightthickness=1, width=200)
        self._unseated_frame.pack(fill="y", expand=True)
        self._unseated_frame.pack_propagate(False)

        # Canvas in assign mode
        canvas_frame = tk.Frame(body, bg=theme.CANVAS_BG)
        canvas_frame.pack(side="left", fill="both", expand=True)
        self._canvas = rc.RoomCanvas(
            canvas_frame, self.cls["layout_id"], mode="assign",
            assignments=self._build_name_mapping(),
            on_seat_click=self._on_seat_click,
            snap_enabled=False)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.after(50, self._canvas.load)
        self._render_unseated()

    def _build_name_mapping(self) -> dict:
        """Build the {seat_id: student_name} dict the canvas expects."""
        return {seat_id: self.name_by_id.get(sid, f"#{sid}")
                for seat_id, sid in self.seat_to_student.items()}

    def _render_unseated(self):
        """Populate the sidebar with:
        (1) An 'Unseat' drop target shown only when a seat is picked
        (2) A list of currently-unseated students, clickable to pick them up
        """
        for w in self._unseated_frame.winfo_children():
            w.destroy()

        seated_ids = set(self.seat_to_student.values())
        all_assigned = [a for a in db.get_assignments_for_round(self.rnd["id"])]
        original_ids = {a["student_id"] for a in all_assigned}
        unseated = original_ids - seated_ids

        # Drop target (visible only when something is picked from the canvas)
        if self._picked_seat_id is not None and self.seat_to_student.get(self._picked_seat_id) is not None:
            drop = tk.Frame(self._unseated_frame, bg=theme.ACCENT,
                             padx=10, pady=8, cursor="hand2")
            drop.pack(fill="x", padx=6, pady=(6, 8))
            tk.Label(drop, text="⬇  Drop here to unseat",
                     font=theme.FONT_BOLD, bg=theme.ACCENT,
                     fg=theme.ACCENT_TEXT, anchor="w").pack(fill="x")
            for w in (drop, drop.winfo_children()[0]):
                w.bind("<Button-1>", lambda _e: self._unseat_picked())

        if not unseated:
            tk.Label(self._unseated_frame,
                     text="All students are\nseated.",
                     font=theme.FONT_SMALL, bg=theme.PANEL,
                     fg=theme.TEXT_DIM, justify="left",
                     padx=10, pady=8).pack(anchor="w")
            return

        # Clickable roster of unseated students
        for sid in sorted(unseated, key=lambda s: self.name_by_id.get(s, "")):
            name = self.name_by_id.get(sid, f"#{sid}")
            is_picked = (sid == self._picked_student_id)
            bg = theme.ACCENT if is_picked else theme.PANEL
            fg = theme.ACCENT_TEXT if is_picked else theme.TEXT
            prefix = "→  " if is_picked else "•  "
            row = tk.Frame(self._unseated_frame, bg=bg,
                            padx=10, pady=3, cursor="hand2")
            row.pack(fill="x")
            lbl = tk.Label(row, text=f"{prefix}{name}",
                            font=theme.FONT_BODY, bg=bg, fg=fg,
                            anchor="w", cursor="hand2")
            lbl.pack(fill="x")
            def on_click(_e=None, s=sid):
                self._on_unseated_click(s)
            for w in (row, lbl):
                w.bind("<Button-1>", on_click)

    # ── Canvas event handling ─────────────────────────────────────────────

    def _on_seat_click(self, seat_id):
        """Canvas dispatches here for every left-click on a seat.
        seat_id=None means Esc was pressed — clear selection."""
        if seat_id is None:
            self._clear_picked()
            return

        # If a sidebar-picked student is pending, complete by placing them
        # in this seat (swapping with current occupant if any)
        if self._picked_student_id is not None:
            self._place_unseated_into_seat(self._picked_student_id, seat_id)
            return

        if self._picked_seat_id is None:
            self._picked_seat_id = seat_id
            occupant = self.seat_to_student.get(seat_id)
            if occupant is not None:
                name = self.name_by_id.get(occupant, f"#{occupant}")
                self.instr_lbl.configure(
                    text=f"Picked up {name}. Click another seat to swap/move, "
                         f"click 'Drop here to unseat' to unseat, or click this "
                         f"seat again (or Esc) to cancel.",
                    fg=theme.ACCENT)
            else:
                self.instr_lbl.configure(
                    text="Picked up an empty seat. Click a student's seat or "
                         "an unseated student to move them here. "
                         "Click this seat again (or Esc) to cancel.",
                    fg=theme.ACCENT)
            self._refresh_canvas_and_sidebar()
        elif seat_id == self._picked_seat_id:
            self._clear_picked()
        else:
            self._swap_seats(self._picked_seat_id, seat_id)

    def _on_unseated_click(self, student_id: int):
        """Sidebar row click: pick up this unseated student, or complete a
        swap if something's already picked."""
        # If a seat is picked (with an occupant), clicking an unseated student
        # in the sidebar doesn't make sense — that's not how the flow reads.
        # Clicking a different unseated student while one is picked = switch.
        if self._picked_seat_id is not None:
            # User had a seat picked, then clicked a sidebar student.
            # Interpret this as: swap the seat's occupant with the picked
            # unseated student. (If seat was empty, just move the student
            # into it.)
            self._place_unseated_into_seat(student_id, self._picked_seat_id)
            return

        if self._picked_student_id == student_id:
            # Clicking the same unseated student again cancels
            self._clear_picked()
            return

        # Pick up this unseated student
        self._picked_student_id = student_id
        name = self.name_by_id.get(student_id, f"#{student_id}")
        self.instr_lbl.configure(
            text=f"Picked up {name} (unseated). Click a seat to place them. "
                 f"Click again (or Esc) to cancel.",
            fg=theme.ACCENT)
        self._refresh_canvas_and_sidebar()

    def _refresh_canvas_and_sidebar(self):
        """Re-render both the canvas and the sidebar based on current
        _picked_* state."""
        self._canvas.set_assignments(self._build_name_mapping(),
                                       self._picked_seat_id)
        self._render_unseated()

    def _clear_picked(self):
        self._picked_seat_id = None
        self._picked_student_id = None
        self.instr_lbl.configure(
            text="Click a seat to pick up that student (or an empty seat). "
                 "Click another seat to swap/move. Esc cancels, Cmd+Z undoes.",
            fg=theme.TEXT_DIM)
        self._refresh_canvas_and_sidebar()

    # ── Swap operation ────────────────────────────────────────────────────

    def _swap_seats(self, seat_a: int, seat_b: int):
        """Swap occupants of two seats. Either can be empty."""
        student_a = self.seat_to_student.get(seat_a)
        student_b = self.seat_to_student.get(seat_b)
        table_a = self.table_for_seat.get(seat_a)
        table_b = self.table_for_seat.get(seat_b)

        # Both empty: nothing to do
        if student_a is None and student_b is None:
            self._clear_picked()
            return

        # Warnings: pinned-table violations, forbidden-pair creation
        warnings = self._check_warnings(student_a, table_a, seat_a,
                                         student_b, table_b, seat_b)
        if warnings and not self._confirm_warnings(warnings):
            self._clear_picked()
            return

        # Perform swap
        snapshot_a = self.seat_to_student.get(seat_a)
        snapshot_b = self.seat_to_student.get(seat_b)
        if student_b is None:
            # seat_b is empty: move student_a there
            del self.seat_to_student[seat_a]
            self.seat_to_student[seat_b] = student_a
        elif student_a is None:
            # seat_a is empty: move student_b there
            del self.seat_to_student[seat_b]
            self.seat_to_student[seat_a] = student_b
        else:
            # Both occupied: swap
            self.seat_to_student[seat_a] = student_b
            self.seat_to_student[seat_b] = student_a

        # Description for undo
        def name_or_empty(sid):
            return self.name_by_id.get(sid, f"#{sid}") if sid is not None else "(empty)"
        desc = f"Swap {name_or_empty(student_a)} ↔ {name_or_empty(student_b)}"

        def _reverse(sa=seat_a, sb=seat_b, va=snapshot_a, vb=snapshot_b):
            # Restore previous mapping exactly
            if va is not None:
                self.seat_to_student[sa] = va
            else:
                self.seat_to_student.pop(sa, None)
            if vb is not None:
                self.seat_to_student[sb] = vb
            else:
                self.seat_to_student.pop(sb, None)
        self._undo_stack.append((_reverse, desc))

        self._clear_picked()
        self._update_undo_button()
        self._render_unseated()

    def _unseat_picked(self):
        """Remove the student from the picked seat, dropping them into the
        unseated pool."""
        if self._picked_seat_id is None:
            return
        seat_id = self._picked_seat_id
        student_id = self.seat_to_student.get(seat_id)
        if student_id is None:
            # Empty seat — nothing to unseat
            self._clear_picked()
            return

        del self.seat_to_student[seat_id]
        name = self.name_by_id.get(student_id, f"#{student_id}")

        def _reverse(s=seat_id, sid=student_id):
            self.seat_to_student[s] = sid
        self._undo_stack.append((_reverse, f"Unseat {name}"))

        self._clear_picked()
        self._update_undo_button()
        self._render_unseated()

    def _place_unseated_into_seat(self, student_id: int, seat_id: int):
        """Place an unseated student into the given seat. If the seat is
        already occupied, the previous occupant becomes unseated (swap)."""
        table_id = self.table_for_seat.get(seat_id)
        prior_occupant = self.seat_to_student.get(seat_id)

        # Warnings: forbidden pair created at the destination table, pin violations
        warnings = self._check_warnings(student_id, None, None,
                                         prior_occupant, table_id, seat_id)
        if warnings and not self._confirm_warnings(warnings):
            self._clear_picked()
            return

        # Record prior state for undo
        prior_snapshot = prior_occupant  # may be None

        # Perform the placement
        self.seat_to_student[seat_id] = student_id

        name = self.name_by_id.get(student_id, f"#{student_id}")
        if prior_snapshot is None:
            desc = f"Seat {name}"
        else:
            prev_name = self.name_by_id.get(prior_snapshot, f"#{prior_snapshot}")
            desc = f"Swap {prev_name} out for {name}"

        def _reverse(s=seat_id, sid=student_id, prev=prior_snapshot):
            if prev is not None:
                self.seat_to_student[s] = prev
            else:
                self.seat_to_student.pop(s, None)
        self._undo_stack.append((_reverse, desc))

        self._clear_picked()
        self._update_undo_button()
        self._render_unseated()

    # ── Warning detection ─────────────────────────────────────────────────

    def _check_warnings(self, sid_a, table_a, seat_a,
                         sid_b, table_b, seat_b) -> list:
        """Collect human-readable warnings about a pending swap.
        Either student may be None (empty seat)."""
        warnings = []

        # Pinned-table violations: is either student pinned to a table that
        # the swap would move them away from?
        def pin_violation(sid, current_tbl, new_tbl):
            if sid is None:
                return None
            pinned_tbl = self.pinned_by_id.get(sid)
            pinned_seat = self.pinned_seat_by_id.get(sid)
            if pinned_seat is not None:
                # Seat-level pin: violated if new seat differs
                if new_tbl != current_tbl:  # moving changes seat
                    name = self.name_by_id.get(sid, f"#{sid}")
                    return f"📌 {name} is pinned to a specific seat. This move violates that pin."
            elif pinned_tbl is not None and pinned_tbl != new_tbl:
                name = self.name_by_id.get(sid, f"#{sid}")
                tbl_lbl = self.tables_by_id.get(pinned_tbl, {}).get("label",
                                                                       f"Table #{pinned_tbl}")
                return f"📌 {name} is pinned to {tbl_lbl}. This move violates that pin."
            return None

        v = pin_violation(sid_a, table_a, table_b)
        if v: warnings.append(v)
        v = pin_violation(sid_b, table_b, table_a)
        if v: warnings.append(v)

        # Forbidden pairs: check the destination table for each student
        def students_at_table_after(target_tbl):
            """Who will be at target_tbl after the swap?"""
            result = {self.seat_to_student[seat] for seat in self.seat_to_student
                      if self.table_for_seat.get(seat) == target_tbl}
            # Remove anyone leaving target_tbl
            if sid_a is not None and table_a == target_tbl:
                result.discard(sid_a)
            if sid_b is not None and table_b == target_tbl:
                result.discard(sid_b)
            # Add anyone arriving at target_tbl
            if sid_a is not None and table_b == target_tbl:
                result.add(sid_a)
            if sid_b is not None and table_a == target_tbl:
                result.add(sid_b)
            return result

        def check_forbidden_at(target_tbl):
            students_here = students_at_table_after(target_tbl)
            for a, b in self.forbidden_pairs:
                if a in students_here and b in students_here:
                    name_a = self.name_by_id.get(a, f"#{a}")
                    name_b = self.name_by_id.get(b, f"#{b}")
                    tbl_lbl = self.tables_by_id.get(target_tbl, {}).get("label",
                                                                          f"Table #{target_tbl}")
                    warnings.append(f"🚫 {name_a} and {name_b} are marked never-together, "
                                     f"but this puts them both at {tbl_lbl}.")

        if table_a is not None:
            check_forbidden_at(table_a)
        if table_b is not None and table_b != table_a:
            check_forbidden_at(table_b)

        return warnings

    def _confirm_warnings(self, warnings: list) -> bool:
        msg = "This change creates the following issue(s):\n\n"
        msg += "\n".join(f"  • {w}" for w in warnings)
        msg += "\n\nContinue anyway?"
        return messagebox.askyesno("Confirm Change", msg, parent=self)

    # ── Undo ──────────────────────────────────────────────────────────────

    def _undo(self):
        if not self._undo_stack:
            return
        reverse_fn, desc = self._undo_stack.pop()
        reverse_fn()
        self._clear_picked()
        self._update_undo_button()
        self._render_unseated()
        self.status_lbl.configure(text=f"Undid: {desc}", fg=theme.TEXT_DIM)

    def _update_undo_button(self):
        if not hasattr(self, "_undo_btn") or not self._undo_btn.winfo_exists():
            return
        if self._undo_stack:
            last_desc = self._undo_stack[-1][1]
            if len(last_desc) > 32:
                last_desc = last_desc[:29] + "…"
            self._undo_btn.configure(bg=theme.BG, fg=theme.TEXT, cursor="hand2",
                                      text=f"↶ Undo: {last_desc}")
            self._undo_btn._btn_bg    = theme.BG
            self._undo_btn._btn_hover = theme.SEP
            self._undo_btn._command   = self._undo
        else:
            self._undo_btn.configure(bg=theme.GHOST_BG, fg=theme.TEXT_MUTED,
                                      cursor="", text="↶ Undo")
            self._undo_btn._btn_bg    = theme.GHOST_BG
            self._undo_btn._btn_hover = theme.GHOST_BG
            self._undo_btn._command   = lambda: None

    # ── Save ──────────────────────────────────────────────────────────────

    def _save(self):
        if not self._undo_stack:
            self.destroy()
            return

        # Guard: any student who was in this round at load time must still
        # be seated at save time. Otherwise saving silently drops them from
        # the round — the sidebar is a transient holding area, not a
        # destination. Teachers who want to truly remove someone should
        # cancel this edit and regenerate the round with attendance set.
        current_student_ids = set(self.seat_to_student.values())
        unseated = self.initial_student_ids - current_student_ids
        if unseated:
            names = sorted(self.name_by_id.get(s, f"#{s}") for s in unseated)
            if len(names) == 1:
                msg = (f"{names[0]} is unseated.\n\n"
                       f"Place them at a seat before saving, or cancel "
                       f"this edit if you didn't mean to make changes.")
            else:
                listing = "\n".join(f"  • {n}" for n in names)
                msg = (f"These students are unseated:\n\n{listing}\n\n"
                       f"Place them at seats before saving, or cancel "
                       f"this edit if you didn't mean to make changes.")
            messagebox.showwarning("Unseated students", msg, parent=self)
            return

        # Recompute pairing score. Subtract this round's contribution from
        # the full class history so we're comparing new assignments against
        # history-minus-this-round.
        full_history = db.get_pair_history(self.cls["id"])
        on_disk = db.get_assignments_for_round(self.rnd["id"])
        on_disk_by_table: dict = defaultdict(list)
        for a in on_disk:
            on_disk_by_table[a["table_id"]].append(a["student_id"])
        prior_history = dict(full_history)
        for students_at_table in on_disk_by_table.values():
            for i in range(len(students_at_table)):
                for j in range(i + 1, len(students_at_table)):
                    a, b = sorted([students_at_table[i], students_at_table[j]])
                    prior_history[(a, b)] = prior_history.get((a, b), 0) - 1
                    if prior_history[(a, b)] <= 0:
                        del prior_history[(a, b)]

        # Group new assignments by table to count pairs
        new_by_table: dict = defaultdict(list)
        for seat_id, sid in self.seat_to_student.items():
            tid = self.table_for_seat.get(seat_id)
            if tid is not None:
                new_by_table[tid].append(sid)
        repeat_score = 0
        for students_at_table in new_by_table.values():
            for i in range(len(students_at_table)):
                for j in range(i + 1, len(students_at_table)):
                    a, b = sorted([students_at_table[i], students_at_table[j]])
                    repeat_score += prior_history.get((a, b), 0)

        # Flatten to (student_id, seat_id, table_id) tuples for DB save
        flat = []
        for seat_id, sid in self.seat_to_student.items():
            tid = self.table_for_seat.get(seat_id)
            flat.append((sid, seat_id, tid))

        db.replace_assignments(self.rnd["id"], flat,
                                mark_edited=True,
                                new_repeat_score=repeat_score)
        self.new_repeat_score = repeat_score
        self.saved = True
        self.destroy()