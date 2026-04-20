"""
room_canvas.py — Drag-and-drop room layout canvas (per-seat model).

Two primitives:
  • Tables   — visual shape (rectangle or ellipse) with rotation. Students
               are not assigned to tables directly; tables are anchors
               for seats and optionally hold a label.
  • Seats    — individual draggable points attached to a table. Each seat
               stores its (x_offset, y_offset) relative to the table center.
               Rotating a table rotates all its seats visually.

Positions are stored in absolute canvas pixel coordinates.

Two modes:
  edit  — tables & seats are draggable.
  view  — read-only. Seats show student names when assignments are given.

All colours are read from the `theme` module at draw time.
"""

import tkinter as tk
import math
import db
import theme

GRID_SNAP   = 20
SEAT_RADIUS = 16
FRONT_H     = 36
PADDING     = 16
MIN_CANVAS_W = 800
MIN_CANVAS_H = 600


def _snap(v: float, enabled: bool = True) -> float:
    if not enabled:
        return v
    return round(v / GRID_SNAP) * GRID_SNAP


def _rotate_point(px: float, py: float, angle_deg: float) -> tuple:
    """Rotate (px, py) around origin by angle_deg. Returns (x, y)."""
    if angle_deg == 0:
        return px, py
    a = math.radians(angle_deg)
    cos_a = math.cos(a)
    sin_a = math.sin(a)
    return (px * cos_a - py * sin_a,
            px * sin_a + py * cos_a)


# Name rendering inside the seat circle. A seat is a ~32px-diameter circle
# which fits about 9 chars at 8pt bold on one line, OR 2 lines of 7pt with
# ~6 chars each. Rather than aggressively truncating every long name, we
# split at whitespace for two-line rendering, giving names like
# "Avery Lynne" → "Avery" / "Lynne" full legibility.
def _fit_name_to_seat(name: str) -> tuple[str, int, int]:
    """Return (display_text, font_pt, line_count) for rendering `name`
    inside a seat circle."""
    # Strip excess whitespace
    name = name.strip()
    if len(name) <= 9:
        # Fits comfortably on one line
        return name, 8, 1
    if " " in name:
        # Split at the space that best balances the two halves.
        words = name.split()
        if len(words) == 2:
            # Simple case: two words → one on each line
            line1, line2 = words[0], words[1]
        else:
            # 3+ words: find the split point minimising length difference
            best_split = 1
            best_diff  = float("inf")
            for i in range(1, len(words)):
                left  = " ".join(words[:i])
                right = " ".join(words[i:])
                diff = abs(len(left) - len(right))
                if diff < best_diff:
                    best_diff = diff
                    best_split = i
            line1 = " ".join(words[:best_split])
            line2 = " ".join(words[best_split:])
        # If either line is still too long for the seat (>11 chars at 7pt),
        # truncate it. Otherwise render as-is.
        if len(line1) > 9:
            line1 = line1[:8] + "…"
        if len(line2) > 9:
            line2 = line2[:8] + "…"
        return f"{line1}\n{line2}", 7, 2
    # Single long word — truncate
    return name[:9] + "…", 8, 1


class RoomCanvas(tk.Frame):
    """
    assignments: dict[seat_id -> student_name]  (view mode only)
    on_change:   callable()  called after any save (edit mode)
    on_move:     callable(kind, entity_id, old_state, new_state) for undo.
                   kind is 'table_move' or 'seat_move'.
    on_seat_click: callable(seat_id)  called in assign mode on left-click
                   of any seat (occupied or empty). Caller decides what to
                   do (start a swap / complete a swap / clear selection).
    selected_seat_id: int | None — seat to highlight as "selected for swap"
                   in assign mode. Caller updates this between redraws.
    """

    def __init__(self, parent, layout_id: int, mode: str = "edit",
                 assignments: dict | None = None, on_change=None,
                 on_move=None, snap_enabled: bool = True,
                 on_context=None, on_selection_change=None,
                 on_seat_click=None, on_table_click=None,
                 table_roster: dict | None = None, **kwargs):
        super().__init__(parent, bg=theme.CANVAS_BG, **kwargs)
        self.layout_id    = layout_id
        self.mode         = mode
        self.assignments  = assignments or {}
        # table_roster: {table_id: [student_name, ...]} for view_roster mode
        # (per-table round view). In this mode seats aren't drawn — each
        # table shows a vertical list of names inside its shape.
        self.table_roster = table_roster or {}
        self.on_change    = on_change
        self.on_move      = on_move
        self.on_context   = on_context    # callable(kind, entity_id, event)
        self.on_selection_change = on_selection_change  # callable(selection_list)
        self.on_seat_click = on_seat_click    # callable(seat_id) for assign mode
        self.on_table_click = on_table_click  # callable(table_id) for table_picker
        self.selected_seat_id: int | None = None
        self.selected_table_id: int | None = None
        self.snap_enabled = snap_enabled

        self._tables: list = []
        self._seats:  list = []
        self._item_to_entity: dict = {}

        self._drag_kind   = None
        self._drag_id     = None
        self._drag_dx     = 0
        self._drag_dy     = 0
        self._drag_start  = None
        self._group_drag_starts: dict = {}
        self._group_drag_anchor = (0, 0)

        # Selection model: set of (kind, id) tuples where kind is "table"|"seat"
        self._selection: set = set()

        # Rubber-band drag-to-select state
        self._rubber_start    = None   # (x, y) or None
        self._rubber_item     = None   # canvas item id for the rectangle
        self._rubber_additive = False  # True when Cmd/Ctrl held — add to selection

        self._auto_placed = False
        self._build()

    # ── Build ────────────────────────────────────────────────────────────────

    def _build(self):
        cursor = "fleur" if self.mode == "edit" else "arrow"

        # Scrollable canvas host: canvas with H and V scrollbars so the
        # user can pan a layout that's bigger than the visible area (e.g.
        # they designed in full-screen and are now viewing in a smaller
        # window). Scrollbars hidden when not needed.
        import tkinter.ttk as ttk
        self._canvas_host = tk.Frame(self, bg=theme.CANVAS_BG)
        self._canvas_host.pack(fill="both", expand=True)
        self._canvas_host.grid_rowconfigure(0, weight=1)
        self._canvas_host.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self._canvas_host, bg=theme.CANVAS_BG, bd=0,
                                highlightthickness=0, cursor=cursor,
                                xscrollincrement=15, yscrollincrement=15)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self._vbar = ttk.Scrollbar(self._canvas_host, orient="vertical",
                                    command=self.canvas.yview)
        self._vbar.grid(row=0, column=1, sticky="ns")
        self._hbar = ttk.Scrollbar(self._canvas_host, orient="horizontal",
                                    command=self.canvas.xview)
        self._hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self._hbar.set,
                               yscrollcommand=self._vbar.set)

        # Forward mousewheel events: vertical by default, horizontal with
        # shift. Use event_generate so Tk's native canvas scrolling handles
        # it rather than our own yview_scroll calls (which have been flaky
        # on macOS).
        def _wheel_y(e):
            delta = getattr(e, "delta", 0)
            if delta != 0:
                # macOS delivers small deltas (1-2), Windows sends 120.
                # Normalise to units.
                step = -1 if delta > 0 else 1
                self.canvas.yview_scroll(step, "units")
            elif e.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                self.canvas.yview_scroll(1, "units")
            return "break"

        def _wheel_x(e):
            delta = getattr(e, "delta", 0)
            if delta != 0:
                step = -1 if delta > 0 else 1
                self.canvas.xview_scroll(step, "units")
            elif e.num == 4:
                self.canvas.xview_scroll(-1, "units")
            elif e.num == 5:
                self.canvas.xview_scroll(1, "units")
            return "break"

        self.canvas.bind("<MouseWheel>",       _wheel_y)
        self.canvas.bind("<Shift-MouseWheel>", _wheel_x)
        self.canvas.bind("<Button-4>",         _wheel_y)
        self.canvas.bind("<Button-5>",         _wheel_y)

        if self.mode == "edit":
            self.canvas.bind("<ButtonPress-1>",   self._on_press)
            self.canvas.bind("<B1-Motion>",       self._on_drag)
            self.canvas.bind("<ButtonRelease-1>", self._on_release)
            self.canvas.bind("<Command-ButtonPress-1>", self._on_press_additive)
            self.canvas.bind("<Command-B1-Motion>",       self._on_drag)
            self.canvas.bind("<Command-ButtonRelease-1>", self._on_release)
            self.canvas.bind("<Shift-ButtonPress-1>",     self._on_press_additive)
            self.canvas.bind("<Shift-B1-Motion>",         self._on_drag)
            self.canvas.bind("<Shift-ButtonRelease-1>",   self._on_release)
            self.canvas.bind("<Button-2>",        self._on_right_click)
            self.canvas.bind("<Button-3>",        self._on_right_click)
            self.canvas.bind("<Control-Button-1>",self._on_right_click)
            self.canvas.bind("<Escape>",          lambda e: self.clear_selection())
            self.canvas.configure(takefocus=1)
        elif self.mode == "assign":
            # Click a seat to select/complete a swap. Esc clears.
            self.canvas.bind("<ButtonPress-1>", self._on_assign_click)
            self.canvas.bind("<Escape>",
                               lambda e: self._on_assign_click_clear())
            self.canvas.configure(takefocus=1)
        elif self.mode == "table_picker":
            # Click a table to select/pin to it. Seats are not rendered.
            self.canvas.bind("<ButtonPress-1>", self._on_table_picker_click)
            self.canvas.configure(takefocus=1)

        self.canvas.bind("<Configure>", self._on_resize)

        self._banner_visible = False
        self._banner_frame = tk.Frame(self, bg=theme.BANNER_BG,
                                      highlightbackground=theme.BANNER_FG,
                                      highlightthickness=1)
        self._banner_label = tk.Label(
            self._banner_frame,
            text="📐  Tables have been auto-placed — drag them to match your room layout.",
            bg=theme.BANNER_BG, fg=theme.BANNER_FG,
            font=theme.FONT_SMALL, padx=12, pady=7)
        self._banner_label.pack(side="left", fill="x", expand=True)
        dismiss = tk.Label(self._banner_frame, text="✕",
                           bg=theme.BANNER_BG, fg=theme.BANNER_X_FG,
                           font=(theme.FONT_BOLD[0], 11, "bold"),
                           padx=12, pady=7, cursor="hand2")
        dismiss.pack(side="right")
        dismiss.bind("<Button-1>", lambda e: self._hide_banner())

    def _hide_banner(self):
        self._banner_frame.place_forget()
        self._banner_visible = False

    def _show_banner(self):
        self._banner_frame.place(relx=0, rely=0, relwidth=1, anchor="nw")
        self._banner_visible = True

    # ── Load & place ─────────────────────────────────────────────────────────

    def load(self):
        self._tables = db.get_tables_for_layout(self.layout_id)
        self._seats  = db.get_seats_for_layout(self.layout_id)
        self.canvas.update_idletasks()
        cw = max(self.canvas.winfo_width(), MIN_CANVAS_W)
        ch = max(self.canvas.winfo_height(), MIN_CANVAS_H)

        any_unplaced = any(t.get("pos_x") is None for t in self._tables)
        if any_unplaced:
            self._auto_place(cw, ch)
            self._save_all_positions()
            if self.mode == "edit":
                self._auto_placed = True

        self._draw()
        if self._auto_placed and self.mode == "edit":
            self._show_banner()

    def _auto_place(self, cw: int, ch: int):
        unplaced = [t for t in self._tables if t.get("pos_x") is None]
        if not unplaced:
            return

        usable_w = cw - PADDING * 2
        usable_h = ch - FRONT_H - PADDING * 3

        avg_w = sum(t.get("width") or 140 for t in unplaced) / len(unplaced)
        avg_h = sum(t.get("height") or 90 for t in unplaced) / len(unplaced)

        n = len(unplaced)
        best_cols = 1
        best_score = float("inf")
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            needed_w = cols * (avg_w + 80) + 60
            needed_h = rows * (avg_h + 80) + 60
            if needed_w > usable_w or needed_h > usable_h:
                continue
            aspect_target = usable_w / max(usable_h, 1)
            aspect_grid   = needed_w / max(needed_h, 1)
            score = abs(aspect_target - aspect_grid)
            if score < best_score:
                best_score = score
                best_cols  = cols

        cols = best_cols
        gap_x = avg_w + 80
        gap_y = avg_h + 80
        start_x = PADDING + avg_w / 2 + 40
        start_y = FRONT_H + PADDING * 2 + avg_h / 2 + 40

        for i, t in enumerate(unplaced):
            col = i % cols
            row = i // cols
            t["pos_x"] = _snap(start_x + col * gap_x, self.snap_enabled)
            t["pos_y"] = _snap(start_y + row * gap_y, self.snap_enabled)

    def _save_all_positions(self):
        for t in self._tables:
            if t.get("pos_x") is not None:
                db.update_table_position(t["id"], t["pos_x"], t["pos_y"])

    # ── Draw ─────────────────────────────────────────────────────────────────

    def _compute_scrollregion(self, viewport_w: int, viewport_h: int) -> tuple:
        """Compute canvas scrollregion (x0, y0, x1, y1). At minimum, covers
        the viewport. Grows to include any table/seat positioned outside it,
        plus a margin so there's always some empty space to drop new tables."""
        MARGIN = 150
        x0 = 0
        y0 = 0
        x1 = max(viewport_w, MIN_CANVAS_W)
        y1 = max(viewport_h, MIN_CANVAS_H)
        for t in self._tables:
            px = t.get("pos_x")
            py = t.get("pos_y")
            if px is None or py is None:
                continue
            w = t.get("width")  or 140
            h = t.get("height") or 90
            # Ensure the table's full extent is visible within scrollregion
            x1 = max(x1, px + w / 2 + MARGIN)
            y1 = max(y1, py + h / 2 + MARGIN)
        for s in self._seats:
            table = next((x for x in self._tables if x["id"] == s["table_id"]), None)
            if table is None:
                continue
            rot = table.get("rotation") or 0
            rx, ry = _rotate_point(s["x_offset"], s["y_offset"], rot)
            sx = (table.get("pos_x") or 0) + rx
            sy = (table.get("pos_y") or 0) + ry
            x1 = max(x1, sx + SEAT_RADIUS + MARGIN)
            y1 = max(y1, sy + SEAT_RADIUS + MARGIN)
        return (x0, y0, x1, y1)

    def _draw(self):
        self.canvas.configure(bg=theme.CANVAS_BG)
        self.canvas.delete("all")
        self._item_to_entity = {}

        viewport_w = self.canvas.winfo_width()  or MIN_CANVAS_W
        viewport_h = self.canvas.winfo_height() or MIN_CANVAS_H

        # Compute world extents and set scrollregion so content outside the
        # viewport is reachable via scrolling.
        region = self._compute_scrollregion(viewport_w, viewport_h)
        self.canvas.configure(scrollregion=region)

        # Draw grid across the full scrollregion (not just viewport) so the
        # grid extends wherever the user scrolls. World-space coordinates.
        rx0, ry0, rx1, ry1 = region
        rx0_i, ry0_i = int(rx0), int(ry0)
        rx1_i, ry1_i = int(rx1), int(ry1)
        for x in range(rx0_i, rx1_i + 1, GRID_SNAP):
            self.canvas.create_line(x, ry0_i, x, ry1_i,
                                    fill=theme.GRID_COLOR, width=1)
        for y in range(ry0_i, ry1_i + 1, GRID_SNAP):
            self.canvas.create_line(rx0_i, y, rx1_i, y,
                                    fill=theme.GRID_COLOR, width=1)

        # FRONT banner spans the full width of the scrollregion, pinned at top
        self.canvas.create_rectangle(rx0, 0, rx1, FRONT_H,
                                      fill=theme.FRONT_BG, outline="")
        self.canvas.create_text((rx0 + rx1) // 2, FRONT_H // 2,
                                text="▲  FRONT OF ROOM  ▲",
                                fill=theme.FRONT_FG,
                                font=(theme.FONT_BOLD[0], 11, "bold"))

        for t in self._tables:
            self._draw_table(t)
        # In view_roster and table_picker modes, seats are NOT drawn —
        # table_picker shows tables as clickable pick targets (with
        # optional pinned-students roster inside), view_roster shows a
        # round's per-table roster.
        if self.mode not in ("view_roster", "table_picker"):
            for s in self._seats:
                self._draw_seat(s)

        if self._banner_visible:
            self._banner_frame.configure(bg=theme.BANNER_BG,
                                         highlightbackground=theme.BANNER_FG)
            self._banner_label.configure(bg=theme.BANNER_BG, fg=theme.BANNER_FG,
                                         font=theme.FONT_SMALL)

    def _draw_table(self, t: dict):
        cx = t.get("pos_x") or 100
        cy = t.get("pos_y") or 100
        w  = t.get("width")  or 140
        h  = t.get("height") or 90
        shape = t.get("shape") or "rect"
        rot   = t.get("rotation") or 0
        decorative = bool(t.get("decorative"))

        # Selection: edit-mode uses is_selected; table_picker uses the
        # dedicated selected_table_id field (set from outside).
        if self.mode == "table_picker":
            selected = (t["id"] == self.selected_table_id)
        else:
            selected = self.is_selected("table", t["id"])
        border   = theme.TABLE_SEL if selected else theme.TABLE_BORDER
        bw       = 3 if selected else 1

        fill = theme.TABLE_BG if not decorative else theme.GHOST_BG
        # In table_picker mode, highlight the selected table with accent
        # fill for immediate visual feedback.
        if self.mode == "table_picker" and selected:
            fill = theme.ACCENT

        if shape == "round":
            if rot == 0:
                item = self.canvas.create_oval(
                    cx - w/2, cy - h/2, cx + w/2, cy + h/2,
                    fill=fill, outline=border, width=bw)
            else:
                pts = []
                for i in range(36):
                    a = 2 * math.pi * i / 36
                    lx = (w / 2) * math.cos(a)
                    ly = (h / 2) * math.sin(a)
                    rx, ry = _rotate_point(lx, ly, rot)
                    pts.extend([cx + rx, cy + ry])
                item = self.canvas.create_polygon(
                    pts, fill=fill, outline=border, width=bw, smooth=True)
        else:
            corners_local = [(-w/2, -h/2), (w/2, -h/2),
                             (w/2, h/2),   (-w/2, h/2)]
            canvas_pts = []
            for lx, ly in corners_local:
                rx, ry = _rotate_point(lx, ly, rot)
                canvas_pts.extend([cx + rx, cy + ry])
            item = self.canvas.create_polygon(
                canvas_pts, fill=fill, outline=border, width=bw)

        self._item_to_entity[item] = ("table", t["id"])

        label_color = theme.TEXT_DIM if decorative else theme.TEXT
        label_text  = t.get("label") or ""

        if self.mode in ("view_roster", "table_picker") and not decorative:
            # Per-table round view OR table_picker pin dialog: render label
            # at top of table and student names as a vertical list beneath.
            roster = self.table_roster.get(t["id"], [])
            # Title at the top edge (inset 8px) — small & bold
            title_y = cy - h/2 + 10
            if label_text:
                title = self.canvas.create_text(
                    cx, title_y, text=label_text,
                    fill=theme.TEXT_DIM,
                    font=(theme.FONT_BOLD[0], 9, "bold"))
                self._item_to_entity[title] = ("table", t["id"])
            # Names fill the remaining space below the title.
            # Scale font size so N names fit within (h - 24) px of vertical
            # room — 8px gap between lines, cap at 10px, floor at 7px.
            n = len(roster)
            if n:
                usable_h = h - 24   # 10 top inset + 14 bottom margin
                # Each line needs ~ line_h px, so line_h = usable_h / n
                line_h = max(7, min(12, int(usable_h / n)))
                font_size = max(6, min(10, line_h - 2))
                # Center the stack vertically within the remaining space
                name_y_start = title_y + 10 + (line_h / 2)
                for i, name in enumerate(roster):
                    # Truncate overly long names to ~13 chars
                    display = name if len(name) <= 13 else name[:12] + "…"
                    ny = name_y_start + i * line_h
                    t_item = self.canvas.create_text(
                        cx, ny, text=display,
                        fill=theme.STUDENT_FG,
                        font=(theme.FONT_BODY[0], font_size))
                    self._item_to_entity[t_item] = ("table", t["id"])
        elif label_text:
            # Normal mode: label centered in the table
            lbl = self.canvas.create_text(
                cx, cy, text=label_text,
                fill=label_color,
                font=(theme.FONT_BOLD[0], 10, "bold"))
            self._item_to_entity[lbl] = ("table", t["id"])

    def _draw_seat(self, s: dict):
        table = next((t for t in self._tables if t["id"] == s["table_id"]), None)
        if table is None:
            return
        cx = table.get("pos_x") or 0
        cy = table.get("pos_y") or 0
        rot = table.get("rotation") or 0
        rx, ry = _rotate_point(s["x_offset"], s["y_offset"], rot)
        sx = cx + rx
        sy = cy + ry

        # Selection highlight: in edit mode from box-select, in assign mode
        # from the "picked for swap" seat.
        if self.mode == "assign":
            selected = (s["id"] == self.selected_seat_id)
        else:
            selected = self.is_selected("seat", s["id"])
        border   = theme.ACCENT if selected else theme.SEAT_DOT
        bw       = 3 if selected else 2

        student = self.assignments.get(s["id"], "")
        fill = theme.PANEL if not student else theme.TABLE_BG
        # In assign mode, give the selected seat a more prominent fill
        if self.mode == "assign" and selected:
            fill = theme.ACCENT

        item = self.canvas.create_oval(
            sx - SEAT_RADIUS, sy - SEAT_RADIUS,
            sx + SEAT_RADIUS, sy + SEAT_RADIUS,
            fill=fill, outline=border, width=bw)
        self._item_to_entity[item] = ("seat", s["id"])

        if self.mode in ("view", "assign") and student:
            # Name rendering inside the seat circle. Try to show full names
            # when they fit. Strategy:
            #   Short (≤9 chars)  → single line, 8pt bold
            #   Has whitespace    → split at balance point, two lines, 7pt
            #   Long single word  → truncate with ellipsis, 8pt bold
            fg = theme.ACCENT_TEXT if (self.mode == "assign" and
                                        s["id"] == self.selected_seat_id) else theme.STUDENT_FG
            display, font_size, lines = _fit_name_to_seat(student)
            if lines == 2:
                # Two-line: render with a newline. Anchor centered.
                txt = self.canvas.create_text(
                    sx, sy, text=display,
                    fill=fg, justify="center",
                    font=(theme.FONT_BODY[0], font_size, "bold"))
            else:
                txt = self.canvas.create_text(
                    sx, sy, text=display,
                    fill=fg,
                    font=(theme.FONT_BODY[0], font_size, "bold"))
            self._item_to_entity[txt] = ("seat", s["id"])

    # ── Interaction ──────────────────────────────────────────────────────────

    def _on_right_click(self, event):
        """Identify what's under the cursor and forward to on_context."""
        if self.on_context is None:
            return
        # Translate viewport coords to canvas-world coords (handles scroll)
        wx = self.canvas.canvasx(event.x)
        wy = self.canvas.canvasy(event.y)
        kind, eid = self._hit_test(wx, wy)
        if kind is None:
            table_id = self._point_in_table(wx, wy)
            if table_id is not None:
                kind, eid = "table", table_id
        # Rewrite event coordinates so downstream handlers see world space
        # (e.g. "Add seat here" needs canvas coords to place the seat).
        # We mutate in-place; Tk Event objects support attribute assignment.
        event.x = int(wx)
        event.y = int(wy)
        self.on_context(kind, eid, event)

    def _on_assign_click(self, event):
        """Left-click in assign mode: identify seat under cursor and emit
        on_seat_click callback. Caller manages the selection/swap state;
        we just dispatch."""
        if self.on_seat_click is None:
            return
        self.canvas.focus_set()
        wx = self.canvas.canvasx(event.x)
        wy = self.canvas.canvasy(event.y)
        kind, eid = self._hit_test(wx, wy)
        if kind == "seat":
            self.on_seat_click(eid)

    def _on_assign_click_clear(self):
        """Esc in assign mode: clear the selection state via the caller."""
        if self.on_seat_click is None:
            return
        # Pass None to signal "cancel current selection"
        self.on_seat_click(None)

    def _on_table_picker_click(self, event):
        """Left-click in table_picker mode: identify table under cursor
        and emit on_table_click callback. Clicks on empty canvas area are
        ignored. Caller manages the selection state."""
        if self.on_table_click is None:
            return
        self.canvas.focus_set()
        wx = self.canvas.canvasx(event.x)
        wy = self.canvas.canvasy(event.y)
        # Prefer hit_test (more precise for rotated/round tables), fall
        # back to _point_in_table for simple hits.
        kind, eid = self._hit_test(wx, wy)
        if kind == "table":
            self.on_table_click(eid)
            return
        tid = self._point_in_table(wx, wy)
        if tid is not None:
            # Skip decorative tables — they can't be pinned to.
            t = next((t for t in self._tables if t["id"] == tid), None)
            if t and not t.get("decorative"):
                self.on_table_click(tid)

    def _hit_test(self, px, py):
        """Return (kind, id) for whatever's under the cursor, or (None, None).
        Prefers seats over tables when both overlap."""
        items = self.canvas.find_overlapping(px - 1, py - 1, px + 1, py + 1)
        for item in reversed(items):
            ent = self._item_to_entity.get(item)
            if ent and ent[0] == "seat":
                return ent
        for item in reversed(items):
            ent = self._item_to_entity.get(item)
            if ent:
                return ent
        return None, None

    def _point_in_table(self, px, py):
        """Return table_id if (px, py) is inside any table's bounding box."""
        for t in self._tables:
            cx = t.get("pos_x") or 0
            cy = t.get("pos_y") or 0
            w = t.get("width")  or 140
            h = t.get("height") or 90
            # Simple axis-aligned check (ignoring rotation — good enough for
            # context menu targeting)
            if (cx - w/2 <= px <= cx + w/2) and (cy - h/2 <= py <= cy + h/2):
                return t["id"]
        return None

    def canvas_to_table_local(self, table_id: int, px: float, py: float):
        """Convert canvas-absolute (px, py) to table-local offset, undoing
        the table's rotation. Used when adding a seat via right-click."""
        t = next((x for x in self._tables if x["id"] == table_id), None)
        if t is None:
            return (0, 0)
        cx = t.get("pos_x") or 0
        cy = t.get("pos_y") or 0
        rot = t.get("rotation") or 0
        return _rotate_point(px - cx, py - cy, -rot)

    def _on_press(self, event, additive: bool = False):
        """Press handler. Three possible interpretations:
        (1) Hit a seat or table → select it (or toggle if additive) and arm
            for a potential drag-to-move.
        (2) Hit empty canvas → start a rubber-band selection rectangle.
        """
        self.canvas.focus_set()
        # Translate viewport pixels to canvas-world coordinates so hit-testing
        # and drag arithmetic work correctly when the view has been scrolled.
        ex = self.canvas.canvasx(event.x)
        ey = self.canvas.canvasy(event.y)

        items = self.canvas.find_overlapping(ex - 1, ey - 1,
                                              ex + 1, ey + 1)
        kind, eid = None, None
        for item in reversed(items):
            ent = self._item_to_entity.get(item)
            if ent and ent[0] == "seat":
                kind, eid = ent
                break
        if kind is None:
            for item in reversed(items):
                ent = self._item_to_entity.get(item)
                if ent:
                    kind, eid = ent
                    break

        if kind is None:
            if not additive and self._selection:
                self._selection.clear()
                self._emit_selection_change()
                self._draw()
            self._rubber_start    = (ex, ey)
            self._rubber_additive = additive
            return

        if additive:
            self._toggle_selection(kind, eid)
        else:
            if not self.is_selected(kind, eid):
                self._selection.clear()
                self._selection.add((kind, eid))
                self._emit_selection_change()

        self._drag_kind = kind
        self._drag_id   = eid

        if kind == "table":
            t = next(t for t in self._tables if t["id"] == eid)
            self._drag_dx = ex - (t.get("pos_x") or 0)
            self._drag_dy = ey - (t.get("pos_y") or 0)
            self._drag_start = (t.get("pos_x"), t.get("pos_y"))
        else:
            s = next(s for s in self._seats if s["id"] == eid)
            table = next(t for t in self._tables if t["id"] == s["table_id"])
            rot = table.get("rotation") or 0
            rx, ry = _rotate_point(s["x_offset"], s["y_offset"], rot)
            sx = (table.get("pos_x") or 0) + rx
            sy = (table.get("pos_y") or 0) + ry
            self._drag_dx = ex - sx
            self._drag_dy = ey - sy
            self._drag_start = (s["x_offset"], s["y_offset"])

        moving_tables = {tid for (k, tid) in self._selection if k == "table"}
        self._group_drag_starts = {}
        for (k, i) in self._selection:
            if k == self._drag_kind and i == self._drag_id:
                continue
            if k == "table":
                tb = next((x for x in self._tables if x["id"] == i), None)
                if tb is not None:
                    self._group_drag_starts[("table", i)] = (
                        tb.get("pos_x") or 0, tb.get("pos_y") or 0)
            elif k == "seat":
                seat = next((x for x in self._seats if x["id"] == i), None)
                if seat is None:
                    continue
                if seat["table_id"] in moving_tables:
                    continue
                self._group_drag_starts[("seat", i)] = (
                    seat["x_offset"], seat["y_offset"])
        self._group_drag_anchor = (ex, ey)

        self._draw()

    def _on_press_additive(self, event):
        self._on_press(event, additive=True)

    def _on_drag(self, event):
        # Translate viewport pixels to canvas-world coordinates
        ex = self.canvas.canvasx(event.x)
        ey = self.canvas.canvasy(event.y)

        # Rubber-band selection takes priority if we started on empty canvas
        if self._rubber_start is not None:
            x0, y0 = self._rubber_start
            x1, y1 = ex, ey
            if self._rubber_item is not None:
                self.canvas.coords(self._rubber_item, x0, y0, x1, y1)
            else:
                self._rubber_item = self.canvas.create_rectangle(
                    x0, y0, x1, y1,
                    outline=theme.ACCENT, width=2,
                    dash=(4, 3), fill="")
            return

        if self._drag_kind is None:
            return
        new_x = _snap(ex - self._drag_dx, self.snap_enabled)
        new_y = _snap(ey - self._drag_dy, self.snap_enabled)

        if self._drag_kind == "table":
            t = next(t for t in self._tables if t["id"] == self._drag_id)
            t["pos_x"] = new_x
            t["pos_y"] = new_y
        else:
            s = next(s for s in self._seats if s["id"] == self._drag_id)
            table = next(t for t in self._tables if t["id"] == s["table_id"])
            rot = table.get("rotation") or 0
            tx = table.get("pos_x") or 0
            ty = table.get("pos_y") or 0
            lx, ly = _rotate_point(new_x - tx, new_y - ty, -rot)
            s["x_offset"] = lx
            s["y_offset"] = ly

        # Move everyone else in the selection by the same canvas-space delta,
        # computed from the raw event position (not the snapped primary pos)
        # so group members stay in lockstep with the pointer even when snap
        # is aggressive.
        if self._group_drag_starts:
            ax, ay = self._group_drag_anchor
            canvas_dx = ex - ax
            canvas_dy = ey - ay
            for (k, i), (sx0, sy0) in self._group_drag_starts.items():
                if k == "table":
                    tb = next((x for x in self._tables if x["id"] == i), None)
                    if tb is not None:
                        tb["pos_x"] = _snap(sx0 + canvas_dx, self.snap_enabled)
                        tb["pos_y"] = _snap(sy0 + canvas_dy, self.snap_enabled)
                elif k == "seat":
                    seat = next((x for x in self._seats if x["id"] == i), None)
                    if seat is None:
                        continue
                    parent = next((t for t in self._tables
                                    if t["id"] == seat["table_id"]), None)
                    rot = (parent.get("rotation") or 0) if parent else 0
                    local_dx, local_dy = _rotate_point(canvas_dx, canvas_dy, -rot)
                    seat["x_offset"] = sx0 + local_dx
                    seat["y_offset"] = sy0 + local_dy

        self._draw()

    def _on_release(self, event):
        ex = self.canvas.canvasx(event.x)
        ey = self.canvas.canvasy(event.y)

        # Rubber-band release: compute hits
        if self._rubber_start is not None:
            x0, y0 = self._rubber_start
            x1, y1 = ex, ey
            lo_x, hi_x = min(x0, x1), max(x0, x1)
            lo_y, hi_y = min(y0, y1), max(y0, y1)

            # Only treat as rubber-band if there was meaningful drag distance
            if abs(x1 - x0) > 3 or abs(y1 - y0) > 3:
                hits = set()
                for t in self._tables:
                    cx = t.get("pos_x") or 0
                    cy = t.get("pos_y") or 0
                    if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
                        hits.add(("table", t["id"]))
                for s in self._seats:
                    table = next((x for x in self._tables if x["id"] == s["table_id"]), None)
                    if table is None:
                        continue
                    rot = table.get("rotation") or 0
                    rx, ry = _rotate_point(s["x_offset"], s["y_offset"], rot)
                    sx = (table.get("pos_x") or 0) + rx
                    sy = (table.get("pos_y") or 0) + ry
                    if lo_x <= sx <= hi_x and lo_y <= sy <= hi_y:
                        hits.add(("seat", s["id"]))

                if self._rubber_additive:
                    self._selection |= hits
                else:
                    self._selection = hits
                self._emit_selection_change()

            if self._rubber_item is not None:
                self.canvas.delete(self._rubber_item)
            self._rubber_start    = None
            self._rubber_item     = None
            self._rubber_additive = False
            self._draw()
            return

        if self._drag_kind is None:
            return
        moved = False
        if self._drag_kind == "table":
            t = next(t for t in self._tables if t["id"] == self._drag_id)
            new_state = (t["pos_x"], t["pos_y"])
            if new_state != self._drag_start:
                db.update_table_position(t["id"], t["pos_x"], t["pos_y"])
                moved = True
                if self.on_move:
                    self.on_move("table_move", t["id"],
                                  self._drag_start, new_state)
        else:
            s = next(s for s in self._seats if s["id"] == self._drag_id)
            new_state = (s["x_offset"], s["y_offset"])
            if new_state != self._drag_start:
                db.update_seat_position(s["id"], s["x_offset"], s["y_offset"])
                moved = True
                if self.on_move:
                    self.on_move("seat_move", s["id"],
                                  self._drag_start, new_state)
        # Persist group members. Each gets its own undo entry so the user can
        # step back through the group drag one move at a time — simpler than
        # coalescing into a single "Move N tables" undo, and keeps the undo
        # model consistent with single-drag behavior.
        for (k, i), (sx0, sy0) in (getattr(self, "_group_drag_starts", {}) or {}).items():
            if k == "table":
                tb = next((x for x in self._tables if x["id"] == i), None)
                if tb is None:
                    continue
                if (tb["pos_x"], tb["pos_y"]) != (sx0, sy0):
                    db.update_table_position(tb["id"], tb["pos_x"], tb["pos_y"])
                    moved = True
                    if self.on_move:
                        self.on_move("table_move", tb["id"],
                                      (sx0, sy0),
                                      (tb["pos_x"], tb["pos_y"]))
            elif k == "seat":
                seat = next((x for x in self._seats if x["id"] == i), None)
                if seat is None:
                    continue
                if (seat["x_offset"], seat["y_offset"]) != (sx0, sy0):
                    db.update_seat_position(seat["id"],
                                             seat["x_offset"], seat["y_offset"])
                    moved = True
                    if self.on_move:
                        self.on_move("seat_move", seat["id"],
                                      (sx0, sy0),
                                      (seat["x_offset"], seat["y_offset"]))
        if moved and self.on_change:
            self.on_change()
        self._drag_kind = None
        self._drag_id   = None
        self._drag_start = None
        self._group_drag_starts = {}

    def _on_resize(self, event):
        self._draw()

    # ── Public API ───────────────────────────────────────────────────────────

    def redraw(self):
        self.configure(bg=theme.CANVAS_BG)
        self._draw()

    def reload_all(self):
        self._tables = db.get_tables_for_layout(self.layout_id)
        self._seats  = db.get_seats_for_layout(self.layout_id)
        # Prune any selection entries that no longer point to live entities
        live_keys = {("table", t["id"]) for t in self._tables} | \
                    {("seat", s["id"]) for s in self._seats}
        stale = self._selection - live_keys
        if stale:
            self._selection -= stale
            self._emit_selection_change()
        if any(t.get("pos_x") is None for t in self._tables):
            cw = max(self.canvas.winfo_width(), MIN_CANVAS_W)
            ch = max(self.canvas.winfo_height(), MIN_CANVAS_H)
            self._auto_place(cw, ch)
            self._save_all_positions()
        self._draw()

    reload_tables = reload_all

    def set_snap(self, enabled: bool):
        self.snap_enabled = enabled

    def set_assignments(self, assignments: dict, selected_seat_id: int | None = None):
        """Update the seat-to-name mapping for view/assign mode and redraw.
        assignments: {seat_id: student_name}
        selected_seat_id: optional seat to highlight (assign mode only)"""
        self.assignments = dict(assignments or {})
        self.selected_seat_id = selected_seat_id
        self._draw()

    def set_table_roster(self, table_roster: dict):
        """Update per-table roster mapping for view_roster mode and redraw.
        table_roster: {table_id: [student_name, ...]}"""
        self.table_roster = dict(table_roster or {})
        self._draw()

    def reset_positions(self):
        db.clear_table_positions(self.layout_id)
        for t in self._tables:
            t["pos_x"] = None
            t["pos_y"] = None
        cw = max(self.canvas.winfo_width(), MIN_CANVAS_W)
        ch = max(self.canvas.winfo_height(), MIN_CANVAS_H)
        self._auto_place(cw, ch)
        self._save_all_positions()
        self._draw()
        if self.mode == "edit":
            self._show_banner()

    # ── Selection public API ──────────────────────────────────────────────────

    def is_selected(self, kind: str, eid: int) -> bool:
        return (kind, eid) in self._selection

    def selection_list(self) -> list:
        """Return selection as a list of (kind, id) tuples."""
        return list(self._selection)

    def clear_selection(self):
        if self._selection:
            self._selection.clear()
            self._emit_selection_change()
            self._draw()

    def select_only(self, kind: str, eid: int):
        """Replace the current selection with just this entity."""
        self._selection = {(kind, eid)}
        self._emit_selection_change()
        self._draw()

    def _toggle_selection(self, kind: str, eid: int):
        key = (kind, eid)
        if key in self._selection:
            self._selection.discard(key)
        else:
            self._selection.add(key)
        self._emit_selection_change()

    def _emit_selection_change(self):
        if self.on_selection_change:
            try:
                self.on_selection_change(list(self._selection))
            except Exception:
                pass   # Never let UI callback break canvas state

    # Legacy convenience for older callers
    def get_selected(self) -> tuple:
        """Return the first selection as (kind, id), or (None, None)."""
        if not self._selection:
            return (None, None)
        return next(iter(self._selection))

    def select_table(self, table_id: int):
        self.select_only("table", table_id)