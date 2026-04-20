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
    by_table_id: dict = {}
    by_seat_id:  dict = {}
    for a in assignments_raw:
        by_table_id.setdefault(a["table_id"], [])
        by_table_id[a["table_id"]].append(a["student_name"])
        if a.get("seat_id") is not None:
            by_seat_id[a["seat_id"]] = a["student_name"]

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


# Seat circle radius in points. The source canvas uses SEAT_RADIUS=16px.
# In the PDF we render at the layout's uniform scale.
_SEAT_RADIUS_PT = 10


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
    circles at their layout positions, each with the student's name inside."""
    w     = t["draw_w"]
    h     = t["draw_h"]
    scale = t.get("scale", 1.0)
    rot   = t.get("rotation") or 0

    cx = draw_left + t["px"]
    cy = draw_top  - t["py"]
    abs_x = cx - w / 2
    abs_y = cy - h / 2

    # Shadow
    c.setFillColor(colors.Color(0, 0, 0, alpha=0.08))
    if shape == "round":
        c.ellipse(abs_x + 2, abs_y - 2, abs_x + w + 2, abs_y + h - 2,
                  fill=1, stroke=0)
    else:
        c.rect(abs_x + 2, abs_y - 2, w, h, fill=1, stroke=0)

    # Body (per-seat mode uses the table shape as a backdrop, not a
    # container with stacked names — so no header stripe)
    fill_col = pal["table_bg"] if not decorative else pal.get("ghost_bg", pal["table_bg"])
    c.setFillColor(_pdf_color(fill_col))
    c.setStrokeColor(_pdf_color(pal["table_border"]))
    c.setLineWidth(1)
    if shape == "round":
        c.ellipse(abs_x, abs_y, abs_x + w, abs_y + h, fill=1, stroke=1)
    else:
        c.rect(abs_x, abs_y, w, h, fill=1, stroke=1)

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
    for s in seats:
        rx, ry = _rotate_point(s["x_offset"], s["y_offset"], rot)
        sx = cx + rx * scale
        # Canvas y grows downward; PDF y grows upward — so flip.
        sy = cy - ry * scale

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
            # line at 6pt; names with whitespace split into two lines at
            # 5pt; long single-word names truncate.
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


def _fit_name_to_seat_pdf(name: str) -> tuple:
    """PDF counterpart to room_canvas._fit_name_to_seat. Returns
    (display_text, font_pt, line_count). Seat radius in the PDF is 10pt
    (smaller than the on-screen 16px canvas seat), so fonts are smaller:
    6pt single, 5pt double."""
    name = name.strip()
    if len(name) <= 9:
        return name, 6, 1
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
        if len(line1) > 9:
            line1 = line1[:8] + "…"
        if len(line2) > 9:
            line2 = line2[:8] + "…"
        return f"{line1}\n{line2}", 5, 2
    return name[:9] + "…", 6, 1


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