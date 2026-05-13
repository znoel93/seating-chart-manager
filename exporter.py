"""
exporter.py — PDF seating chart export using ReportLab.

Renders a room-view seating chart to a single PDF page.
Theme-aware: light themes export as-is; dark themes invert to a
white background with accent colours for table headers.
"""

import math
import os
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas

import db
import theme


# ── Colour helpers ────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16)/255, int(h[2:4], 16)/255, int(h[4:6], 16)/255)


def _luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    return 0.299*r + 0.587*g + 0.114*b


def _is_dark_theme() -> bool:
    return _luminance(theme.BG) < 0.4


def _pdf_color(hex_color: str) -> colors.Color:
    r, g, b = _hex_to_rgb(hex_color)
    return colors.Color(r, g, b)


def _darken(hex_color: str, factor: float = 0.55) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * factor), int(g * factor), int(b * factor))


# ── Print palette ─────────────────────────────────────────────────────────────

def _get_print_palette() -> dict:
    """
    Returns a colour palette suitable for printing.
    Dark themes are inverted to white background; light themes use their
    own colours directly.
    """
    if _is_dark_theme():
        # Invert: white page, accent colour for table headers
        return {
            "page_bg":      "#FFFFFF",
            "header_bg":    theme.ACCENT,
            "header_fg":    theme.ACCENT_TEXT,
            "table_bg":     "#F8F8F8",
            "table_border": theme.ACCENT,
            "student_fg":   "#1A1A1A",
            "label_fg":     theme.ACCENT_TEXT,
            "front_bg":     theme.ACCENT,
            "front_fg":     theme.ACCENT_TEXT,
            "grid_color":   "#E8E8E8",
            "title_fg":     "#1A1A1A",
            "meta_fg":      "#666666",
            "sep_color":    "#CCCCCC",
            "ghost_bg":     "#F0F0F0",
        }
    else:
        # Light theme — use theme colours directly
        return {
            "page_bg":      theme.BG,
            "header_bg":    _darken(theme.TABLE_BORDER),
            "header_fg":    "#FFFFFF",
            "table_bg":     theme.PANEL,
            "table_border": theme.TABLE_BORDER,
            "student_fg":   theme.TEXT,
            "label_fg":     "#FFFFFF",
            "front_bg":     theme.FRONT_BG,
            "front_fg":     theme.FRONT_FG,
            "grid_color":   theme.GRID_COLOR,
            "title_fg":     theme.TEXT,
            "meta_fg":      theme.TEXT_DIM,
            "sep_color":    theme.BORDER,
            "ghost_bg":     theme.GHOST_BG,
        }


# ── Layout engine ─────────────────────────────────────────────────────────────

TABLE_W_PT = 110   # points
TABLE_H_BASE = 80  # points — grows with student count
HEADER_H = 20      # points — table label stripe
FRONT_H  = 28      # points — front of room banner
PADDING  = 24      # points — canvas edge padding
GRID_PT  = 14      # points — grid spacing
STUDENT_LINE_H = 13  # points — per-student line height


def _snap_pt(v: float) -> float:
    return round(v / GRID_PT) * GRID_PT


def _get_table_height(n_students: int) -> float:
    body_h = max(TABLE_H_BASE - HEADER_H, STUDENT_LINE_H * n_students + 10)
    return HEADER_H + body_h


def _auto_place(tables: list, canvas_w: float, canvas_h: float) -> list:
    """Place tables in a centred grid. Returns tables with px/py set."""
    n        = len(tables)
    usable_w = canvas_w - PADDING * 2
    usable_h = canvas_h - FRONT_H - PADDING * 3

    best_cols  = 1
    best_score = float("inf")
    for cols in range(1, n + 1):
        rows     = math.ceil(n / cols)
        needed_w = cols * TABLE_W_PT + (cols - 1) * GRID_PT * 2
        needed_h = rows * TABLE_H_BASE + (rows - 1) * GRID_PT * 2
        if needed_w > usable_w or needed_h > usable_h:
            continue
        aspect_t = usable_w / max(usable_h, 1)
        aspect_g = needed_w / max(needed_h, 1)
        score    = abs(aspect_t - aspect_g)
        if score < best_score:
            best_score = score
            best_cols  = cols

    cols    = best_cols
    rows    = math.ceil(n / cols)
    gap_x   = GRID_PT * 2
    gap_y   = GRID_PT * 2
    total_w = cols * TABLE_W_PT + (cols - 1) * gap_x
    total_h = rows * TABLE_H_BASE + (rows - 1) * gap_y
    start_x = PADDING + (usable_w - total_w) / 2
    start_y = FRONT_H + PADDING * 2 + (usable_h - total_h) / 2

    placed = []
    for i, t in enumerate(tables):
        col = i % cols
        row = i // cols
        t = dict(t)
        t["px"] = _snap_pt(start_x + col * (TABLE_W_PT + gap_x))
        t["py"] = _snap_pt(start_y + row * (TABLE_H_BASE + gap_y))
        # Defaults so the per-seat rendering path also works when tables
        # fell into auto-place (no stored positions).
        t["draw_w"] = TABLE_W_PT
        t["draw_h"] = TABLE_H_BASE
        t["scale"]  = 1.0
        placed.append(t)
    return placed


def _resolve_positions(tables: list, canvas_w: float, canvas_h: float,
                        assignments: dict) -> list:
    """
    Scale stored absolute canvas pixel positions into PDF points. The
    source canvas uses an 800x600+ pixel logical space; we scale to fit
    the PDF canvas while preserving aspect ratio.
    Falls back to auto-placement for any unplaced table.
    """
    any_unplaced = any(t["pos_x"] is None for t in tables)
    if any_unplaced:
        return _auto_place(tables, canvas_w, canvas_h)

    # Find bounding box of all tables in source coords
    min_x = min(t["pos_x"] - (t.get("width")  or 140) / 2 for t in tables)
    max_x = max(t["pos_x"] + (t.get("width")  or 140) / 2 for t in tables)
    min_y = min(t["pos_y"] - (t.get("height") or 90)  / 2 for t in tables)
    max_y = max(t["pos_y"] + (t.get("height") or 90)  / 2 for t in tables)

    src_w = max(max_x - min_x, 1)
    src_h = max(max_y - min_y, 1)
    dst_w = canvas_w - PADDING * 2
    dst_h = canvas_h - FRONT_H - PADDING * 2

    # Scale uniformly so contents fit without distortion
    scale = min(dst_w / src_w, dst_h / src_h, 1.0)

    # Centre the scaled content
    offset_x = PADDING + (dst_w - src_w * scale) / 2
    offset_y = FRONT_H + PADDING + (dst_h - src_h * scale) / 2

    placed = []
    for t in tables:
        t = dict(t)
        # Store scaled values for the draw pass
        t["px"]    = offset_x + (t["pos_x"] - min_x) * scale
        t["py"]    = offset_y + (t["pos_y"] - min_y) * scale
        t["draw_w"] = (t.get("width")  or 140) * scale
        t["draw_h"] = (t.get("height") or 90)  * scale
        t["scale"]  = scale
        placed.append(t)
    return placed


# ── PDF drawing ───────────────────────────────────────────────────────────────

def export_pdf(
    round_id:      int,
    class_name:    str,
    layout_id:     int,
    output_path:   str,
    label:         str,
    orientation:   str  = "landscape",   # "landscape" | "portrait"
    show_score:    bool = False,
    repeat_score:  int  = 0,
    created_at:    str  = "",
    seating_mode:  str  = "per_seat",    # "per_seat" | "per_table"
) -> str:
    """
    Render a seating chart PDF and save it to output_path.

    seating_mode controls how students are drawn inside each table:
      - per_seat  — students shown at their specific seat positions as
                    small circles with names inside, mirroring the on-
                    screen Room View. Reads seat_id from assignments.
      - per_table — students listed as a roster inside each table shape.
                    Simpler and sufficient for rounds where seat position
                    doesn't matter. Ignores seat_id.

    Returns output_path on success.
    """
    pagesize = landscape(A4) if orientation == "landscape" else A4
    pw, ph   = pagesize          # page width/height in points

    assignments_raw = db.get_assignments_for_round(round_id)
    tables          = db.get_tables_for_layout(layout_id)

    # Build assignments dict: table_id -> [student_name, ...] for roster mode.
    # For per_seat mode we also need seat_id -> student_name.
    # Use `student_display` (already formatted per the class's
    # name_display preference) rather than the raw `student_name`, so
    # the exported PDF matches what teachers see in the in-app view.
    by_table_id: dict = {}
    by_seat_id:  dict = {}
    for a in assignments_raw:
        display = a.get("student_display") or a["student_name"]
        by_table_id.setdefault(a["table_id"], [])
        by_table_id[a["table_id"]].append(display)
        if a.get("seat_id") is not None:
            by_seat_id[a["seat_id"]] = display

    # Seats (only needed for per_seat rendering)
    seats_by_table: dict = {}
    if seating_mode == "per_seat":
        all_seats = db.get_seats_for_layout(layout_id)
        for s in all_seats:
            seats_by_table.setdefault(s["table_id"], []).append(s)

    pal = _get_print_palette()

    # Canvas area (below header band)
    HEADER_BAND = 52   # pts — title/meta band at top
    canvas_y0   = ph - HEADER_BAND   # top of drawing area (PDF coords from bottom)
    canvas_h    = canvas_y0 - PADDING
    canvas_w    = pw - PADDING * 2

    # Resolve table positions into points
    tables_placed = _resolve_positions(tables, canvas_w, canvas_h, by_table_id)

    c = pdf_canvas.Canvas(output_path, pagesize=pagesize)
    c.setTitle(f"{class_name} — {label}")

    # ── Page background ───────────────────────────────────────────────────────
    c.setFillColor(_pdf_color(pal["page_bg"]))
    c.rect(0, 0, pw, ph, fill=1, stroke=0)

    # ── Header band ───────────────────────────────────────────────────────────
    c.setFillColor(_pdf_color(pal["page_bg"]))
    # Title
    c.setFillColor(_pdf_color(pal["title_fg"]))
    c.setFont("Helvetica-Bold", 18)
    c.drawString(PADDING, ph - 28, label)

    meta_parts = [class_name]
    if created_at:
        meta_parts.append(created_at[:16].replace("T", " "))
    if show_score:
        score_txt = f"Pairing score: {repeat_score}"
        meta_parts.append(score_txt)
    c.setFont("Helvetica", 9)
    c.setFillColor(_pdf_color(pal["meta_fg"]))
    c.drawString(PADDING, ph - 42, "  ·  ".join(meta_parts))

    # Separator line
    c.setStrokeColor(_pdf_color(pal["sep_color"]))
    c.setLineWidth(0.5)
    c.line(PADDING, ph - HEADER_BAND, pw - PADDING, ph - HEADER_BAND)

    # ── Drawing canvas area ───────────────────────────────────────────────────
    draw_top    = ph - HEADER_BAND       # PDF y for top of room canvas
    draw_bottom = PADDING
    draw_left   = PADDING
    draw_right  = pw - PADDING

    # Grid
    c.setStrokeColor(_pdf_color(pal["grid_color"]))
    c.setLineWidth(0.3)
    x = draw_left
    while x <= draw_right:
        c.line(x, draw_bottom, x, draw_top)
        x += GRID_PT
    y = draw_bottom
    while y <= draw_top:
        c.line(draw_left, y, draw_right, y)
        y += GRID_PT

    # Front of room banner
    front_top = draw_top
    front_bot = draw_top - FRONT_H
    c.setFillColor(_pdf_color(pal["front_bg"]))
    c.rect(draw_left, front_bot, canvas_w, FRONT_H, fill=1, stroke=0)
    c.setFillColor(_pdf_color(pal["front_fg"]))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(pw / 2, front_bot + 9, "▲   FRONT OF ROOM   ▲")

    # ── Tables ────────────────────────────────────────────────────────────────
    # Dispatch per mode. In per_table mode, names stack inside each table
    # shape (a roster). In per_seat mode, each seat is drawn as a circle at
    # its position with the student's name inside, mirroring the on-screen
    # Room View.
    for t in tables_placed:
        names      = sorted(by_table_id.get(t["id"], []))
        shape      = t.get("shape", "rect")
        decorative = bool(t.get("decorative"))

        if seating_mode == "per_table":
            _draw_table_roster(c, t, names, shape, decorative,
                                draw_left, draw_top, pal)
        else:
            _draw_table_with_seats(c, t, by_seat_id, shape, decorative,
                                     draw_left, draw_top, pal,
                                     seats=seats_by_table.get(t["id"], []))

    c.save()
    return output_path


def _draw_table_roster(c, t: dict, names: list, shape: str,
                         decorative: bool, draw_left: float, draw_top: float,
                         pal: dict):
    """Per-table render: table shape + stacked student names inside."""
    w = t["draw_w"]
    h_base = max(t["draw_h"],
                  HEADER_H + STUDENT_LINE_H * max(len(names), 1) + 8)
    if decorative:
        h_base = t["draw_h"]

    cx = draw_left + t["px"]
    cy = draw_top  - t["py"]
    abs_x = cx - w / 2
    abs_y = cy - h_base / 2

    # Shadow
    c.setFillColor(colors.Color(0, 0, 0, alpha=0.08))
    if shape == "round":
        c.ellipse(abs_x + 2, abs_y - 2, abs_x + w + 2, abs_y + h_base - 2,
                  fill=1, stroke=0)
    else:
        c.rect(abs_x + 2, abs_y - 2, w, h_base, fill=1, stroke=0)

    # Body
    fill_col = pal["table_bg"] if not decorative else pal.get("ghost_bg", pal["table_bg"])
    c.setFillColor(_pdf_color(fill_col))
    c.setStrokeColor(_pdf_color(pal["table_border"]))
    c.setLineWidth(1)
    if shape == "round":
        c.ellipse(abs_x, abs_y, abs_x + w, abs_y + h_base, fill=1, stroke=1)
    else:
        c.rect(abs_x, abs_y, w, h_base, fill=1, stroke=1)

    # Header + label
    if not decorative and shape != "round":
        header_y = abs_y + h_base - HEADER_H
        c.setFillColor(_pdf_color(pal["header_bg"]))
        c.rect(abs_x, header_y, w, HEADER_H, fill=1, stroke=0)
        c.setFillColor(_pdf_color(pal["label_fg"]))
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(cx, header_y + 6, t["label"])
    else:
        c.setFillColor(_pdf_color(pal["student_fg"]))
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(cx, cy - 4, t["label"])

    # Student names
    if not decorative:
        c.setFillColor(_pdf_color(pal["student_fg"]))
        c.setFont("Helvetica", 9)
        if shape == "round":
            for i, name in enumerate(names):
                ny = cy - 16 - i * STUDENT_LINE_H
                c.drawCentredString(cx, ny, name)
        else:
            for i, name in enumerate(names):
                name_y = abs_y + h_base - HEADER_H - 12 - i * STUDENT_LINE_H
                c.drawString(abs_x + 8, name_y, name)


# Seat circle radius in points. Mirrors room_canvas.SEAT_RADIUS so the
# PDF and in-app room view render at consistent sizes. The default seat
# margin (where _seed_default_seats places seats) is 22 source-px from
# the table edge to the seat center — so a 22pt radius keeps the seat's
# inner edge tangent to the table edge without overlapping.
_SEAT_RADIUS_PT = 22


def _rotate_point(px: float, py: float, angle_deg: float) -> tuple:
    """Rotate (px, py) around origin by angle_deg. Mirrors room_canvas.py."""
    if angle_deg == 0:
        return px, py
    a = math.radians(angle_deg)
    cos_a = math.cos(a)
    sin_a = math.sin(a)
    return (px * cos_a - py * sin_a,
            px * sin_a + py * cos_a)


def _draw_table_with_seats(c, t: dict, by_seat_id: dict, shape: str,
                             decorative: bool, draw_left: float,
                             draw_top: float, pal: dict, seats: list):
    """Per-seat render: table shape at its native size + individual seat
    circles at their layout positions, each with the student's name inside.

    Table rotation is honored — the body, shadow, and seats all rotate
    together. This mirrors how room_canvas draws rotated tables (rotated
    polygons for rectangles, polygon-approximated ellipses for rounds).
    Without this, a portrait-oriented table in the in-app view would
    render as landscape in the PDF and seat positions would visibly
    drift relative to the table edges.
    """
    w     = t["draw_w"]
    h     = t["draw_h"]
    scale = t.get("scale", 1.0)
    rot   = t.get("rotation") or 0

    cx = draw_left + t["px"]
    cy = draw_top  - t["py"]

    # Build the four corners in local table coordinates, then rotate
    # each by `rot` degrees and translate to canvas space.
    corners_local = [(-w/2, -h/2), (w/2, -h/2),
                     (w/2,  h/2),  (-w/2, h/2)]

    def _to_canvas(lx: float, ly: float) -> tuple:
        rx, ry = _rotate_point(lx, ly, rot)
        # Canvas y grows down, PDF y grows up — flip Y when applying.
        return cx + rx, cy - ry

    canvas_corners = [_to_canvas(lx, ly) for lx, ly in corners_local]

    # Shadow: same corners, shifted slightly (+2 in x, -2 in y in canvas
    # space, which means +2/-2 in PDF after flip). For rotated tables
    # the shadow inherits the rotation since it traces the same shape.
    shadow_corners = [(x + 2, y - 2) for (x, y) in canvas_corners]
    c.setFillColor(colors.Color(0, 0, 0, alpha=0.08))
    if shape == "round":
        # Round tables: trace an N-gon approximating the ellipse so
        # rotation is correctly applied. 36 segments is plenty smooth
        # at the sizes we render.
        ellipse_corners = _ellipse_polygon(cx, cy, w, h, rot, n=36)
        shadow_ellipse = [(x + 2, y - 2) for (x, y) in ellipse_corners]
        p = c.beginPath()
        p.moveTo(*shadow_ellipse[0])
        for x, y in shadow_ellipse[1:]:
            p.lineTo(x, y)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
    else:
        p = c.beginPath()
        p.moveTo(*shadow_corners[0])
        for x, y in shadow_corners[1:]:
            p.lineTo(x, y)
        p.close()
        c.drawPath(p, fill=1, stroke=0)

    # Body
    fill_col = pal["table_bg"] if not decorative else pal.get("ghost_bg", pal["table_bg"])
    c.setFillColor(_pdf_color(fill_col))
    c.setStrokeColor(_pdf_color(pal["table_border"]))
    c.setLineWidth(1)
    if shape == "round":
        ellipse_corners = _ellipse_polygon(cx, cy, w, h, rot, n=36)
        p = c.beginPath()
        p.moveTo(*ellipse_corners[0])
        for x, y in ellipse_corners[1:]:
            p.lineTo(x, y)
        p.close()
        c.drawPath(p, fill=1, stroke=1)
    else:
        p = c.beginPath()
        p.moveTo(*canvas_corners[0])
        for x, y in canvas_corners[1:]:
            p.lineTo(x, y)
        p.close()
        c.drawPath(p, fill=1, stroke=1)

    # Table label — centered on the table, dim colour so the seat text stands out
    c.setFillColor(_pdf_color(pal["meta_fg"]))
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(cx, cy - 3, t["label"] or "")

    if decorative:
        return  # No seats on decorative tables

    # Draw each seat. The seat's x_offset / y_offset are in the same
    # pixel-space as the table's pos_x/pos_y in the source layout; they
    # need to be rotated by the table's rotation, then scaled to PDF
    # points, then placed relative to the table centre.
    #
    # Anti-overlap adjustment: the seat margin (distance from table edge
    # to seat center in source pixels) scales with the layout's fit-to-
    # page scale factor, but the seat CIRCLE radius is a fixed pt size.
    # On layouts that scale down, the scaled margin can shrink below the
    # radius and seats visually overlap the table edge.
    #
    # Fix: push the seat outward along the AXIS PERPENDICULAR to the
    # table edge it sits nearest to (not radially from center, which
    # would push seats sideways along the table). Top-row seats get
    # pushed up; bottom-row seats get pushed down; etc. This keeps
    # seats centered along the table edge they belong to and just
    # increases the gap to the table.
    for s in seats:
        # The seat's offset in the table's LOCAL coordinate system —
        # before rotation. If we're going to push perpendicular to the
        # nearest edge, we want to do that in the table's local frame
        # (where edges are axis-aligned), THEN rotate.
        lx_src = s["x_offset"]
        ly_src = s["y_offset"]

        # Scaled offset in local (un-rotated) frame
        lx_scaled = lx_src * scale
        ly_scaled = ly_src * scale

        # The table's half-extents in PDF space
        half_w = w / 2
        half_h = h / 2

        # Determine which edge the seat is "outside" along the dominant
        # axis. We compare how far the seat is past each edge:
        #   x-overshoot: |lx_scaled| - half_w
        #   y-overshoot: |ly_scaled| - half_h
        # Whichever is greater determines the perpendicular push axis.
        # If neither overshoots (seat is INSIDE the table — shouldn't
        # happen for default layouts), skip the push entirely.
        x_overshoot = abs(lx_scaled) - half_w
        y_overshoot = abs(ly_scaled) - half_h

        if x_overshoot > 0 or y_overshoot > 0:
            # Pick the dominant axis — the one where the seat is most
            # clearly "outside" the table body.
            if y_overshoot >= x_overshoot:
                # Top/bottom seat — push along Y only
                # Required overshoot = seat_radius; current = y_overshoot
                deficit = _SEAT_RADIUS_PT - y_overshoot
                if deficit > 0:
                    # Push outward in the direction the seat already
                    # sits relative to table center
                    direction = 1 if ly_scaled > 0 else -1
                    ly_scaled += direction * deficit
            else:
                # Left/right seat — push along X only
                deficit = _SEAT_RADIUS_PT - x_overshoot
                if deficit > 0:
                    direction = 1 if lx_scaled > 0 else -1
                    lx_scaled += direction * deficit
        # else: seat is inside table body (custom layout?), leave it
        # alone — we don't want to surprise the teacher.

        # Now rotate the (possibly adjusted) local offset by the
        # table's rotation, then place relative to the table center
        # in PDF coordinates.
        rx, ry = _rotate_point(lx_scaled, ly_scaled, rot)
        sx = cx + rx
        # Canvas y grows downward; PDF y grows upward — so flip.
        sy = cy - ry

        occupant = by_seat_id.get(s["id"])
        # Outline in border colour; interior fill is table bg when empty,
        # a tinted fill when occupied (mirrors canvas convention).
        seat_fill = pal["table_bg"] if not occupant else pal.get("ghost_bg", pal["table_bg"])
        c.setFillColor(_pdf_color(seat_fill))
        c.setStrokeColor(_pdf_color(pal["table_border"]))
        c.setLineWidth(0.8)
        c.circle(sx, sy, _SEAT_RADIUS_PT, fill=1, stroke=1)

        if occupant:
            # Match the on-screen canvas logic: short names render on one
            # line at 11pt; names with whitespace split into two lines at
            # 9pt; long single-word names truncate.
            display, font_size, lines = _fit_name_to_seat_pdf(occupant)
            c.setFillColor(_pdf_color(pal["student_fg"]))
            c.setFont("Helvetica-Bold", font_size)
            if lines == 2:
                line1, line2 = display.split("\n", 1)
                # Two-line: offset each line vertically around sy.
                # Line height ~ font_size + 1pt.
                lh = font_size + 1
                c.drawCentredString(sx, sy + lh / 2 - 1, line1)
                c.drawCentredString(sx, sy - lh / 2 - 1, line2)
            else:
                c.drawCentredString(sx, sy - 2, display)


def _ellipse_polygon(cx: float, cy: float, w: float, h: float,
                       rot: float, n: int = 36) -> list:
    """Return n points around an ellipse with the given size + rotation,
    centered at (cx, cy) in PDF (Y-up) coordinates. Used to draw rotated
    ellipses as filled polygons because ReportLab's c.ellipse() is
    axis-aligned only. Mirrors the polygon-approximation approach used
    by room_canvas for the same reason."""
    import math
    pts = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        # Ellipse local coords (canvas Y-down convention to match seat math)
        lx = (w / 2) * math.cos(angle)
        ly = (h / 2) * math.sin(angle)
        rx, ry = _rotate_point(lx, ly, rot)
        pts.append((cx + rx, cy - ry))  # flip Y for PDF
    return pts


def _fit_name_to_seat_pdf(name: str) -> tuple:
    """PDF counterpart to room_canvas._fit_name_to_seat. Returns
    (display_text, font_pt, line_count). Mirrors the in-app function
    so the room view and printed PDF show names consistently.

    Sizing rules:
      - ≤9 chars → 1 line at 11pt.
      - Names with whitespace → split into 2 lines at 9pt each.
      - Long single-word names → truncate at 9 chars with ellipsis."""
    name = (name or "").strip()
    SINGLE_LIMIT = 9
    LINE_LIMIT   = 9

    if not name:
        return "", 11, 1
    if len(name) <= SINGLE_LIMIT:
        return name, 11, 1
    if " " in name:
        words = name.split()
        if len(words) == 2:
            line1, line2 = words[0], words[1]
        else:
            best_split = 1
            best_diff  = float("inf")
            for i in range(1, len(words)):
                left  = " ".join(words[:i])
                right = " ".join(words[i:])
                d = abs(len(left) - len(right))
                if d < best_diff:
                    best_diff = d
                    best_split = i
            line1 = " ".join(words[:best_split])
            line2 = " ".join(words[best_split:])
        if len(line1) > LINE_LIMIT:
            line1 = line1[:LINE_LIMIT - 1] + "…"
        if len(line2) > LINE_LIMIT:
            line2 = line2[:LINE_LIMIT - 1] + "…"
        return f"{line1}\n{line2}", 9, 2
    return name[:LINE_LIMIT - 1] + "…", 11, 1


# ── Save path helper ──────────────────────────────────────────────────────────

def default_save_path(class_name: str, label: str) -> str:
    """Suggest a default filename in the user's Documents folder."""
    safe_class = "".join(c for c in class_name if c.isalnum() or c in " _-").strip()
    safe_label = "".join(c for c in label      if c.isalnum() or c in " _-").strip()
    filename   = f"{safe_class} — {safe_label}.pdf".replace(" ", "_")

    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home()
    return str(docs / filename)


# ── Activity round PDF export ─────────────────────────────────────────────────
#
# Activities are list-oriented (not spatial like seating), so this exporter
# is deliberately simpler than export_pdf: a grid of activity "cards", each
# with header + student list. Cards flow left-to-right, wrap to new rows,
# spill to new pages when necessary.

# Card sizing constants for activity PDF. Values chosen to fit reasonable
# card counts on both portrait and landscape pages while keeping student
# names readable (9pt body font needs ~40pt height per 3 students).
ACT_CARD_W        = 150   # points
ACT_CARD_HEADER_H = 28    # points — single-line accent band; grows with name wrap
ACT_CARD_NAME_LH  = 12    # points — per-line height for wrapped activity name
ACT_CARD_CAP_H    = 12    # points — capacity "N/N" indicator row
ACT_CARD_MIN_H    = 60    # points — min body height (empty activity)
ACT_CARD_ROW_H    = 12    # points — per-student row
ACT_CARD_PAD      = 8     # points — inner padding
ACT_GUTTER        = 10    # points — between cards
ACT_DESC_LINE_H   = 10    # points — per-line of description (italic 8pt)
ACT_DESC_FONT     = ("Helvetica-Oblique", 8)
ACT_NAME_FONT     = ("Helvetica-Bold", 10)


def _compute_activity_header_height(name_line_count: int) -> float:
    """Accent-band height for an activity card with `name_line_count`
    name lines. Always reserves room for the capacity line below the
    name; padding above and below the whole band."""
    name_line_count = max(1, name_line_count)
    return (ACT_CARD_PAD
             + name_line_count * ACT_CARD_NAME_LH
             + 2  # small gap between name and capacity
             + ACT_CARD_CAP_H
             + ACT_CARD_PAD)


def _wrap_text_for_width(text: str, font_name: str, font_size: float,
                          max_width: float, canvas) -> list:
    """Wrap `text` into lines whose rendered width doesn't exceed
    max_width. Greedy word-wrap — breaks on whitespace; if a single
    word is wider than the limit, it still gets its own line rather
    than being character-split (that edge case is rare for activity
    descriptions and avoiding mid-word breaks keeps the output
    readable).

    Returns a list of lines. Empty input → empty list."""
    text = (text or "").strip()
    if not text:
        return []
    words = text.split()
    lines: list = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if canvas.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _compute_activity_card_height(student_count: int,
                                    desc_line_count: int = 0,
                                    name_line_count: int = 1) -> float:
    """How tall an activity card needs to be for N students, an
    optional M-line description, and a K-line activity name."""
    header_h = _compute_activity_header_height(name_line_count)
    # Description band (if any): pad top + lines + pad bottom + 1px divider
    if desc_line_count > 0:
        desc_h = (ACT_CARD_PAD
                   + desc_line_count * ACT_DESC_LINE_H
                   + ACT_CARD_PAD
                   + 1)
    else:
        desc_h = 0
    body_h = max(ACT_CARD_MIN_H,
                  ACT_CARD_PAD * 2 + student_count * ACT_CARD_ROW_H)
    return header_h + desc_h + body_h


def _paginate_activity_cards(cards: list, page_w: float, page_h: float,
                               header_band: float) -> list:
    """Partition activity cards into pages.

    `cards` is a list of dicts with keys: name, capacity, students.
    Returns [[card, ...], [card, ...], ...] — one list of cards per page,
    each pre-assigned a (col, row, x, y, w, h) placement. Cards too tall
    for a page get truncated at page height (a very long activity with
    50 students would overflow; we cap height and add "…N more" footer
    on that card).
    """
    max_card_h_per_page = page_h - header_band - ACT_CARD_PAD
    usable_w = page_w - ACT_CARD_PAD * 2
    cols = max(1, int((usable_w + ACT_GUTTER) // (ACT_CARD_W + ACT_GUTTER)))
    # Re-center: total width of cols cards + (cols-1) gutters
    total_w = cols * ACT_CARD_W + (cols - 1) * ACT_GUTTER
    start_x = (page_w - total_w) / 2

    pages: list = []
    current_page: list = []
    # Track the tallest card in the current row so the next row starts
    # below all of them (pack in fixed-height rows; simpler than true
    # masonry and produces predictable output).
    row_h = 0.0
    y_cursor = page_h - header_band - ACT_CARD_PAD
    col = 0

    def _new_page():
        nonlocal current_page, y_cursor, row_h, col
        if current_page:
            pages.append(current_page)
        current_page = []
        y_cursor = page_h - header_band - ACT_CARD_PAD
        row_h = 0.0
        col = 0

    for card in cards:
        desc_line_count = len(card.get("desc_lines", []))
        name_line_count = max(1, len(card.get("name_lines", [])))
        card_h = _compute_activity_card_height(len(card["students"]),
                                                 desc_line_count,
                                                 name_line_count)
        header_h = _compute_activity_header_height(name_line_count)
        # Cap card height to a single page's worth (very long activities)
        if card_h > max_card_h_per_page:
            card_h = max_card_h_per_page
            card["truncated"] = True
            # Compute how many students fit after reserving for header +
            # description + ellipsis footer
            desc_h = (ACT_CARD_PAD + desc_line_count * ACT_DESC_LINE_H
                      + ACT_CARD_PAD + 1) if desc_line_count > 0 else 0
            body_capacity = int(
                (card_h - header_h - desc_h - ACT_CARD_PAD * 2)
                // ACT_CARD_ROW_H)
            # Reserve one row for "…N more"
            card["visible_students"] = card["students"][:max(0, body_capacity - 1)]
        else:
            card["visible_students"] = card["students"]

        # Does this card fit in the current row?
        if col >= cols:
            # Row full — advance y by the tallest card in this row
            y_cursor -= row_h + ACT_GUTTER
            row_h = 0.0
            col = 0
            # Does y have room for the next card?
            if y_cursor - card_h < ACT_CARD_PAD:
                _new_page()

        # Does y have room for this card on the current row's baseline?
        # (i.e., is y_cursor - card_h still above the bottom padding?)
        if y_cursor - card_h < ACT_CARD_PAD:
            _new_page()

        x = start_x + col * (ACT_CARD_W + ACT_GUTTER)
        y_top = y_cursor
        card["placement"] = {
            "x":      x,
            "y_top":  y_top,           # top edge in PDF coords
            "w":      ACT_CARD_W,
            "h":      card_h,
        }
        current_page.append(card)
        col += 1
        if card_h > row_h:
            row_h = card_h

    if current_page:
        pages.append(current_page)
    return pages


def export_activity_pdf(
    round_id:      int,
    class_name:    str,
    output_path:   str,
    label:         str,
    orientation:   str  = "portrait",
    show_score:    bool = False,
    repeat_score:  int  = 0,
    activity_repeat_score: int = 0,
    created_at:    str  = "",
) -> str:
    """Render an activity round PDF and save it to output_path.

    Unlike seating PDF (which draws a room layout), activities are
    list-oriented: render a grid of cards (one per activity), each with
    the activity name as an accent-colored header and student names
    beneath. Cards wrap to fill the page; overflow onto additional pages
    as needed.

    Returns output_path on success.
    """
    pagesize = landscape(A4) if orientation == "landscape" else A4
    pw, ph   = pagesize

    # Data gathering. We need class_id to look up activities + students;
    # fetch it from the round record.
    round_meta = db.get_activity_round(round_id)
    if round_meta is None:
        raise ValueError(f"Activity round {round_id} not found")
    class_id = round_meta["class_id"]

    assignments = db.get_activity_assignments_for_round(round_id)
    # Include archived activities so historical rounds referencing them
    # still render properly after the teacher archives them.
    activities = db.get_activities_for_class(class_id, include_archived=True)
    activity_by_id = {a["id"]: a for a in activities}

    students = db.get_students_for_class(class_id, active_only=False)
    students_by_id = {s["id"]: s for s in students}

    # Group assignments by activity_id
    by_activity: dict = {}
    for a in assignments:
        by_activity.setdefault(a["activity_id"], []).append(a["student_id"])

    # Build card list in activity sort order. Only include activities
    # that actually had assignments in this round (excluded-for-this-
    # round activities have none, and shouldn't render as empty cards).
    cards = []
    for a in activities:
        aid = a["id"]
        if aid not in by_activity:
            continue
        student_names = []
        for sid in by_activity[aid]:
            s = students_by_id.get(sid)
            if not s:
                continue
            student_names.append(s.get("display") or s.get("name") or "")
        student_names.sort()
        cards.append({
            "name":        a["name"],
            "capacity":    a["capacity"],
            "description": (a.get("description") or "").strip(),
            "students":    student_names,
        })

    pal = _get_print_palette()
    HEADER_BAND = 60  # points — title/meta area at top of page

    # Pre-compute wrapped description AND wrapped name lines for each
    # card. Needs a canvas to measure text widths, so we build one now
    # and reuse it for the actual render. Required before pagination
    # because card height depends on both line counts.
    c = pdf_canvas.Canvas(output_path, pagesize=pagesize)
    c.setTitle(f"{class_name} — {label}")
    text_max_w = ACT_CARD_W - ACT_CARD_PAD * 2
    for card in cards:
        card["name_lines"] = _wrap_text_for_width(
            card["name"],
            ACT_NAME_FONT[0], ACT_NAME_FONT[1],
            text_max_w, c) or [card["name"]]  # fallback: show raw
        if card["description"]:
            card["desc_lines"] = _wrap_text_for_width(
                card["description"],
                ACT_DESC_FONT[0], ACT_DESC_FONT[1],
                text_max_w, c)
        else:
            card["desc_lines"] = []

    # Paginate
    pages = _paginate_activity_cards(cards, pw, ph, HEADER_BAND)
    if not pages:
        # Empty round — still produce a single page with a friendly
        # "no assignments" message rather than a blank/invalid PDF.
        pages = [[]]

    # Canvas is already created above (needed for text measurement
    # during pagination). Re-use that same canvas for the actual
    # rendering pass.
    for page_idx, page_cards in enumerate(pages):
        # Page background
        c.setFillColor(_pdf_color(pal["page_bg"]))
        c.rect(0, 0, pw, ph, fill=1, stroke=0)

        # Header band
        _draw_activity_page_header(
            c, pw, ph, HEADER_BAND, pal,
            class_name=class_name,
            label=label,
            created_at=created_at,
            show_score=show_score,
            repeat_score=repeat_score,
            activity_repeat_score=activity_repeat_score,
            page_index=page_idx,
            total_pages=len(pages),
        )

        if not page_cards:
            # Empty-round fallback page
            c.setFillColor(_pdf_color(pal["meta_fg"]))
            c.setFont("Helvetica-Oblique", 11)
            msg = "No assignments in this round."
            msg_w = c.stringWidth(msg, "Helvetica-Oblique", 11)
            c.drawString((pw - msg_w) / 2, ph / 2, msg)
        else:
            for card in page_cards:
                _draw_activity_card(c, card, pal)

        c.showPage()

    c.save()
    return output_path


def _draw_activity_page_header(c, pw: float, ph: float, band_h: float,
                                pal: dict,
                                class_name: str, label: str,
                                created_at: str, show_score: bool,
                                repeat_score: int,
                                activity_repeat_score: int,
                                page_index: int, total_pages: int):
    """Draw the top band: class + label + meta line."""
    # Title
    c.setFillColor(_pdf_color(pal["title_fg"]))
    c.setFont("Helvetica-Bold", 16)
    title = f"{class_name} — {label}" if class_name else label
    c.drawString(ACT_CARD_PAD * 2, ph - 24, title)

    # Meta line: date + optional scores + page indicator
    meta_parts = []
    if created_at:
        # Trim ISO timestamp to date only for readability
        ts = created_at.replace("T", " ")[:16]
        meta_parts.append(ts)
    if show_score:
        meta_parts.append(f"Pair repeats: {repeat_score}")
        meta_parts.append(f"Activity repeats: {activity_repeat_score}")
    if total_pages > 1:
        meta_parts.append(f"Page {page_index + 1} of {total_pages}")
    if meta_parts:
        c.setFillColor(_pdf_color(pal["meta_fg"]))
        c.setFont("Helvetica", 10)
        c.drawString(ACT_CARD_PAD * 2, ph - 42, "  ·  ".join(meta_parts))

    # Separator line under the header band
    c.setStrokeColor(_pdf_color(pal["sep_color"]))
    c.setLineWidth(0.5)
    sep_y = ph - band_h + 6
    c.line(ACT_CARD_PAD * 2, sep_y, pw - ACT_CARD_PAD * 2, sep_y)


def _draw_activity_card(c, card: dict, pal: dict):
    """Draw a single activity card at the position computed by
    _paginate_activity_cards."""
    p = card["placement"]
    x = p["x"]
    y_top = p["y_top"]
    w = p["w"]
    h = p["h"]

    # PDF coords: origin bottom-left. y_bot is where the rect starts.
    y_bot = y_top - h

    # Card background + border
    c.setFillColor(_pdf_color(pal["table_bg"]))
    c.setStrokeColor(_pdf_color(pal["table_border"]))
    c.setLineWidth(0.8)
    c.roundRect(x, y_bot, w, h, 4, fill=1, stroke=1)

    # Header band (accent) — height grows with name line count so
    # long activity names wrap cleanly rather than getting truncated
    # with an ellipsis.
    name_lines = card.get("name_lines") or [card["name"]]
    header_h = _compute_activity_header_height(len(name_lines))
    header_y_bot = y_top - header_h
    c.setFillColor(_pdf_color(pal["header_bg"]))
    # Draw a plain rect for the header. The outer roundRect border
    # hides minor corner rounding differences — acceptable for print.
    c.rect(x, header_y_bot, w, header_h, fill=1, stroke=0)

    # Activity name (white on accent), centered across wrapped lines.
    # Each line rendered separately so long names flow to multiple
    # rows instead of being ellipsis-truncated.
    c.setFillColor(_pdf_color(pal["header_fg"]))
    c.setFont(*ACT_NAME_FONT)
    # Start drawing from the top of the header (account for top pad
    # and baseline offset)
    name_top = y_top - ACT_CARD_PAD
    for i, line in enumerate(name_lines):
        line_y = name_top - (i + 1) * ACT_CARD_NAME_LH + 2
        lw = c.stringWidth(line, ACT_NAME_FONT[0], ACT_NAME_FONT[1])
        c.drawString(x + (w - lw) / 2, line_y, line)

    # Capacity indicator (smaller, beneath the name block)
    cap_text = f"{len(card['students'])}/{card['capacity']}"
    c.setFont("Helvetica", 8)
    cap_w = c.stringWidth(cap_text, "Helvetica", 8)
    cap_y = header_y_bot + ACT_CARD_PAD - 2
    c.drawString(x + (w - cap_w) / 2, cap_y, cap_text)

    # Description band (optional). Sits between the accent header
    # and the student list, with a thin separator below. Italic +
    # muted color so it reads as metadata, matching the on-screen
    # card.
    desc_lines = card.get("desc_lines") or []
    if desc_lines:
        desc_band_h = (ACT_CARD_PAD
                        + len(desc_lines) * ACT_DESC_LINE_H
                        + ACT_CARD_PAD)
        desc_band_top = header_y_bot
        desc_band_bot = desc_band_top - desc_band_h
        # Background — use the card bg (already painted by the
        # roundRect above), so no extra fill needed. Just draw text.
        c.setFillColor(_pdf_color(pal["meta_fg"]))
        c.setFont(*ACT_DESC_FONT)
        for i, line in enumerate(desc_lines):
            line_y = (desc_band_top
                       - ACT_CARD_PAD
                       - (i + 1) * ACT_DESC_LINE_H
                       + 2)
            c.drawString(x + ACT_CARD_PAD, line_y, line)
        # Thin separator below description (matches the UI divider)
        c.setStrokeColor(_pdf_color(pal["sep_color"]))
        c.setLineWidth(0.3)
        c.line(x + ACT_CARD_PAD, desc_band_bot,
                x + w - ACT_CARD_PAD, desc_band_bot)
        body_top = desc_band_bot - ACT_CARD_PAD
    else:
        body_top = header_y_bot - ACT_CARD_PAD

    # Student list body
    c.setFillColor(_pdf_color(pal["student_fg"]))
    c.setFont("Helvetica", 9)
    for i, student in enumerate(card.get("visible_students", card["students"])):
        row_y = body_top - (i + 1) * ACT_CARD_ROW_H + 3
        if row_y < y_bot + ACT_CARD_PAD:
            break
        # Truncate student name if too long for card width
        display = student
        max_student_w = w - ACT_CARD_PAD * 2
        if c.stringWidth(display, "Helvetica", 9) > max_student_w:
            while (c.stringWidth(display + "…", "Helvetica", 9) > max_student_w
                   and len(display) > 1):
                display = display[:-1]
            display = display + "…"
        c.drawString(x + ACT_CARD_PAD, row_y, display)

    # "…N more" footer if truncated
    if card.get("truncated") and card.get("visible_students"):
        remaining = len(card["students"]) - len(card["visible_students"])
        if remaining > 0:
            c.setFillColor(_pdf_color(pal["meta_fg"]))
            c.setFont("Helvetica-Oblique", 8)
            foot = f"… {remaining} more"
            c.drawString(x + ACT_CARD_PAD, y_bot + ACT_CARD_PAD, foot)