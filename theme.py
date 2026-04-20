"""
theme.py — Centralised theming system.

All colour and font constants used across ui.py and room_canvas.py are
sourced from this module.  Switching a preset re-populates every exported
name so callers that re-read the module globals see the new values
immediately (works because Python module globals are shared references).

Usage:
    import theme
    theme.apply("Smith")          # switch preset
    bg = theme.BG                 # read current value
"""

import db

# ── Font pairings ─────────────────────────────────────────────────────────────

FONT_PAIRINGS: dict[str, dict] = {
    "Classic": {
        "display": "Georgia",
        "body":    "Helvetica Neue",
    },
    "Modern": {
        "display": "Trebuchet MS",
        "body":    "Trebuchet MS",
    },
    "Friendly": {
        "display": "Arial Rounded MT Bold",
        "body":    "Arial",
    },
    "Sharp": {
        "display": "Courier New",
        "body":    "Courier New",
    },
    "System": {
        "display": "TkDefaultFont",
        "body":    "TkDefaultFont",
    },
    "Smith": {
        "display": "Impact",
        "body":    "Arial",
    },
}

# ── Colour presets ────────────────────────────────────────────────────────────

PRESETS: dict[str, dict] = {

    "Midnight": {
        "BG":           "#2D2D2D",
        "SIDEBAR_BG":   "#1A1A2E",
        "SIDEBAR_ACT":  "#16213E",
        "PANEL":        "#3A3A3A",
        "ACCENT":       "#4A7FCB",
        "ACCENT_DARK":  "#3568B0",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#C0392B",
        "DANGER_DARK":  "#A93226",
        "SUCCESS":      "#27AE60",
        "SUCCESS_DARK": "#1E8449",
        "GHOST_BG":     "#505050",
        "GHOST_DARK":   "#404040",
        "TEXT":         "#F0EDE8",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#A8A8A8",
        "TEXT_MUTED":   "#707070",
        "BORDER":       "#555555",
        "SEP":          "#404040",
        # Room canvas
        "CANVAS_BG":    "#1E1E2E",
        "GRID_COLOR":   "#2A2A3E",
        "FRONT_BG":     "#2C4A8C",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#3A4A6A",
        "TABLE_BORDER": "#6A8ABE",
        "TABLE_SEL":    "#7EC8E3",
        "TABLE_LABEL":  "#E0EAF8",
        "STUDENT_FG":   "#C8D8F0",
        "SEAT_DOT":     "#4A7FCB",
        "EMPTY_FG":     "#506070",
        "BANNER_BG":    "#3A2A0A",
        "BANNER_FG":    "#F0C040",
        "BANNER_X_FG":  "#A08030",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#1A3A5C", "#7EC8E3"),
            ("#3A2A0A", "#F0C040"),
            ("#0A3A2A", "#4DC890"),
            ("#3A1A3A", "#C880C8"),
            ("#3A2A1A", "#E09060"),
            ("#1A2A3A", "#60A0D0"),
            ("#1A3A1A", "#70C870"),
            ("#3A1A1A", "#D07070"),
        ],
    },

    "Chalk": {
        "BG":           "#F2EFE8",
        "SIDEBAR_BG":   "#3A3226",
        "SIDEBAR_ACT":  "#2A2418",
        "PANEL":        "#FDFAF4",
        "ACCENT":       "#5C7A3E",
        "ACCENT_DARK":  "#4A6230",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#A63020",
        "DANGER_DARK":  "#8A2418",
        "SUCCESS":      "#3A7A30",
        "SUCCESS_DARK": "#2C6024",
        "GHOST_BG":     "#DDD8CE",
        "GHOST_DARK":   "#C8C2B6",
        "TEXT":         "#1A1610",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#5A5248",
        "TEXT_MUTED":   "#9A9288",
        "BORDER":       "#C0B8AC",
        "SEP":          "#D8D0C4",
        "CANVAS_BG":    "#E8E0D0",
        "GRID_COLOR":   "#D0C8B8",
        "FRONT_BG":     "#5C7A3E",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#F0EAD8",
        "TABLE_BORDER": "#8A7A5A",
        "TABLE_SEL":    "#5C7A3E",
        "TABLE_LABEL":  "#FFFFFF",
        "STUDENT_FG":   "#3A3020",
        "SEAT_DOT":     "#7A9A5A",
        "EMPTY_FG":     "#A09080",
        "BANNER_BG":    "#FFF8DC",
        "BANNER_FG":    "#806020",
        "BANNER_X_FG":  "#A08040",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#D8EEC8", "#3A6020"),
            ("#FFF0C0", "#806020"),
            ("#C8E8E0", "#206050"),
            ("#F0D8E8", "#703060"),
            ("#E0D8F0", "#403080"),
            ("#FFE8D0", "#804020"),
            ("#D0EED0", "#205020"),
            ("#F8D8D8", "#702020"),
        ],
    },

    "Navy": {
        "BG":           "#0D1B2A",
        "SIDEBAR_BG":   "#071018",
        "SIDEBAR_ACT":  "#0A1620",
        "PANEL":        "#162534",
        "ACCENT":       "#3A8FD4",
        "ACCENT_DARK":  "#2A72AA",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#D44040",
        "DANGER_DARK":  "#B03030",
        "SUCCESS":      "#30A860",
        "SUCCESS_DARK": "#248048",
        "GHOST_BG":     "#243444",
        "GHOST_DARK":   "#1A2838",
        "TEXT":         "#E8F0F8",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#8AA0B8",
        "TEXT_MUTED":   "#4A6070",
        "BORDER":       "#2A3A4A",
        "SEP":          "#1E2E3E",
        "CANVAS_BG":    "#0A1520",
        "GRID_COLOR":   "#141E28",
        "FRONT_BG":     "#1A4A7A",
        "FRONT_FG":     "#E8F4FF",
        "TABLE_BG":     "#162840",
        "TABLE_BORDER": "#3A6A9A",
        "TABLE_SEL":    "#5AAAE0",
        "TABLE_LABEL":  "#C8E0F8",
        "STUDENT_FG":   "#A8C8E8",
        "SEAT_DOT":     "#3A8FD4",
        "EMPTY_FG":     "#3A5060",
        "BANNER_BG":    "#1A3020",
        "BANNER_FG":    "#60D090",
        "BANNER_X_FG":  "#408060",
        "font":         "Modern",
        "TABLE_COLORS": [
            ("#0A2A4A", "#5AAAE0"),
            ("#0A2A1A", "#50C880"),
            ("#2A1A3A", "#C070D0"),
            ("#2A2A0A", "#D0A030"),
            ("#2A0A0A", "#D06060"),
            ("#0A1A3A", "#4080C0"),
            ("#0A2A2A", "#40B0A0"),
            ("#1A1A2A", "#8080C0"),
        ],
    },

    "Forest": {
        "BG":           "#1A2318",
        "SIDEBAR_BG":   "#0F1A0D",
        "SIDEBAR_ACT":  "#121E10",
        "PANEL":        "#223020",
        "ACCENT":       "#6AAE48",
        "ACCENT_DARK":  "#548A38",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#C04838",
        "DANGER_DARK":  "#A03828",
        "SUCCESS":      "#48A860",
        "SUCCESS_DARK": "#388048",
        "GHOST_BG":     "#2E4028",
        "GHOST_DARK":   "#223018",
        "TEXT":         "#E0ECD8",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#8AA880",
        "TEXT_MUTED":   "#506848",
        "BORDER":       "#3A5030",
        "SEP":          "#283820",
        "CANVAS_BG":    "#141E12",
        "GRID_COLOR":   "#1C2A18",
        "FRONT_BG":     "#2A5020",
        "FRONT_FG":     "#C8EAB0",
        "TABLE_BG":     "#203A18",
        "TABLE_BORDER": "#5A8A40",
        "TABLE_SEL":    "#8ACA60",
        "TABLE_LABEL":  "#C0E8A0",
        "STUDENT_FG":   "#A0C880",
        "SEAT_DOT":     "#6AAE48",
        "EMPTY_FG":     "#405838",
        "BANNER_BG":    "#2A2A10",
        "BANNER_FG":    "#C8B840",
        "BANNER_X_FG":  "#888020",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#183018", "#70C050"),
            ("#302810", "#C0A030"),
            ("#102820", "#40B080"),
            ("#281830", "#A060C0"),
            ("#301818", "#C06050"),
            ("#102030", "#4080A0"),
            ("#183028", "#50B890"),
            ("#282818", "#A0A030"),
        ],
    },

    "High Contrast": {
        "BG":           "#000000",
        "SIDEBAR_BG":   "#000000",
        "SIDEBAR_ACT":  "#1A1A1A",
        "PANEL":        "#111111",
        "ACCENT":       "#FFFF00",
        "ACCENT_DARK":  "#CCCC00",
        "ACCENT_TEXT":  "#000000",
        "DANGER":       "#FF4444",
        "DANGER_DARK":  "#CC2222",
        "SUCCESS":      "#44FF44",
        "SUCCESS_DARK": "#22CC22",
        "GHOST_BG":     "#333333",
        "GHOST_DARK":   "#222222",
        "TEXT":         "#FFFFFF",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#CCCCCC",
        "TEXT_MUTED":   "#888888",
        "BORDER":       "#666666",
        "SEP":          "#444444",
        "CANVAS_BG":    "#000000",
        "GRID_COLOR":   "#1A1A1A",
        "FRONT_BG":     "#FFFF00",
        "FRONT_FG":     "#000000",
        "TABLE_BG":     "#111111",
        "TABLE_BORDER": "#FFFFFF",
        "TABLE_SEL":    "#FFFF00",
        "TABLE_LABEL":  "#FFFFFF",
        "STUDENT_FG":   "#FFFFFF",
        "SEAT_DOT":     "#FFFF00",
        "EMPTY_FG":     "#666666",
        "BANNER_BG":    "#333300",
        "BANNER_FG":    "#FFFF00",
        "BANNER_X_FG":  "#AAAAAA",
        "font":         "Sharp",
        "TABLE_COLORS": [
            ("#000000", "#FFFF00"),
            ("#000000", "#00FFFF"),
            ("#000000", "#FF00FF"),
            ("#000000", "#00FF00"),
            ("#000000", "#FF8800"),
            ("#000000", "#FF4444"),
            ("#000000", "#44AAFF"),
            ("#000000", "#FFFFFF"),
        ],
    },

    "Smith": {
        "BG":           "#0A0A0A",
        "SIDEBAR_BG":   "#111111",
        "SIDEBAR_ACT":  "#1C1600",
        "PANEL":        "#1A1A1A",
        "ACCENT":       "#F5C000",
        "ACCENT_DARK":  "#D4A800",
        "ACCENT_TEXT":  "#000000",
        "DANGER":       "#CC3300",
        "DANGER_DARK":  "#AA2200",
        "SUCCESS":      "#44AA44",
        "SUCCESS_DARK": "#338833",
        "GHOST_BG":     "#2A2A2A",
        "GHOST_DARK":   "#1E1E1E",
        "TEXT":         "#F8F8F8",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#B8A060",
        "TEXT_MUTED":   "#6A5A20",
        "BORDER":       "#4A3800",
        "SEP":          "#2A2000",
        "CANVAS_BG":    "#080808",
        "GRID_COLOR":   "#141400",
        "FRONT_BG":     "#2A2000",
        "FRONT_FG":     "#F5C000",
        "TABLE_BG":     "#1A1600",
        "TABLE_BORDER": "#C8A000",
        "TABLE_SEL":    "#F5C000",
        "TABLE_LABEL":  "#F5C000",
        "STUDENT_FG":   "#E8D890",
        "SEAT_DOT":     "#F5C000",
        "EMPTY_FG":     "#4A4020",
        "BANNER_BG":    "#1A1400",
        "BANNER_FG":    "#F5C000",
        "BANNER_X_FG":  "#8A7020",
        "font":         "Smith",
        "TABLE_COLORS": [
            ("#1A1400", "#F5C000"),
            ("#1A0A00", "#E07020"),
            ("#001A00", "#40C040"),
            ("#1A0000", "#D04040"),
            ("#001010", "#40B0B0"),
            ("#10001A", "#A060D0"),
            ("#0A1A0A", "#80C060"),
            ("#1A1A00", "#D0D040"),
        ],
    },

    "Flower": {
        "BG":           "#FDF0F5",
        "SIDEBAR_BG":   "#8B3A6E",
        "SIDEBAR_ACT":  "#6E2858",
        "PANEL":        "#FFFFFF",
        "ACCENT":       "#C8407A",
        "ACCENT_DARK":  "#A82E62",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#B03030",
        "DANGER_DARK":  "#8A2020",
        "SUCCESS":      "#3A8A50",
        "SUCCESS_DARK": "#2C6E3E",
        "GHOST_BG":     "#F0D0E0",
        "GHOST_DARK":   "#E0B8CC",
        "TEXT":         "#2A1020",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#7A4060",
        "TEXT_MUTED":   "#B080A0",
        "BORDER":       "#E0A8C8",
        "SEP":          "#F0C8DC",
        "CANVAS_BG":    "#FDE8F2",
        "GRID_COLOR":   "#F8D0E8",
        "FRONT_BG":     "#C8407A",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#FFF0F8",
        "TABLE_BORDER": "#E080B0",
        "TABLE_SEL":    "#C8407A",
        "TABLE_LABEL":  "#FFFFFF",
        "STUDENT_FG":   "#501838",
        "SEAT_DOT":     "#C8407A",
        "EMPTY_FG":     "#C0A0B0",
        "BANNER_BG":    "#FFF0E8",
        "BANNER_FG":    "#9040A0",
        "BANNER_X_FG":  "#C0A0B0",
        "font":         "Friendly",
        "TABLE_COLORS": [
            ("#FFE0EE", "#C8407A"),
            ("#F0E0FF", "#8040C0"),
            ("#FFE8F0", "#E0608A"),
            ("#E8E0FF", "#6050D0"),
            ("#FFF0E0", "#D06030"),
            ("#E8F8E8", "#308840"),
            ("#FFF8E0", "#B08020"),
            ("#F0E8FF", "#A040C0"),
        ],
    },

    "Ocean": {
        "BG":           "#EEF7FF",
        "SIDEBAR_BG":   "#1A6090",
        "SIDEBAR_ACT":  "#0E4A72",
        "PANEL":        "#FFFFFF",
        "ACCENT":       "#0880C8",
        "ACCENT_DARK":  "#0668A8",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#C03030",
        "DANGER_DARK":  "#A02020",
        "SUCCESS":      "#208850",
        "SUCCESS_DARK": "#186840",
        "GHOST_BG":     "#C8E4F8",
        "GHOST_DARK":   "#A8D0EE",
        "TEXT":         "#0A2030",
        "SIDEBAR_TEXT":  "#FFFFFF",
        "TEXT_DIM":     "#306080",
        "TEXT_MUTED":   "#70A8C8",
        "BORDER":       "#90C8E8",
        "SEP":          "#C0DFF4",
        "CANVAS_BG":    "#D8EFFF",
        "GRID_COLOR":   "#C0E4F8",
        "FRONT_BG":     "#0880C8",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#F0F8FF",
        "TABLE_BORDER": "#50A8D8",
        "TABLE_SEL":    "#0880C8",
        "TABLE_LABEL":  "#FFFFFF",
        "STUDENT_FG":   "#0A2840",
        "SEAT_DOT":     "#0880C8",
        "EMPTY_FG":     "#90B8D0",
        "BANNER_BG":    "#FFF8E0",
        "BANNER_FG":    "#0868A8",
        "BANNER_X_FG":  "#70A8C8",
        "font":         "Modern",
        "TABLE_COLORS": [
            ("#D8EEFF", "#0870B8"),
            ("#D8F8F0", "#108860"),
            ("#EEE8FF", "#6040C0"),
            ("#FFE8D8", "#C06020"),
            ("#FFEEE8", "#C04840"),
            ("#E8FFE8", "#208840"),
            ("#FFF8D8", "#A07818"),
            ("#E8F0FF", "#3060C0"),
        ],
    },

    "Autumn": {
        "BG":           "#3A1E0E",
        "SIDEBAR_BG":   "#2A1408",
        "SIDEBAR_ACT":  "#4A2812",
        "PANEL":        "#4D2914",
        "ACCENT":       "#E87428",
        "ACCENT_DARK":  "#C85A18",
        "ACCENT_TEXT":  "#1A0A04",
        "DANGER":       "#D03020",
        "DANGER_DARK":  "#A82010",
        "SUCCESS":      "#9CB040",
        "SUCCESS_DARK": "#7A8A30",
        "GHOST_BG":     "#5E3820",
        "GHOST_DARK":   "#4A2C18",
        "TEXT":         "#FBEAD0",
        "SIDEBAR_TEXT": "#F0D8A8",
        "TEXT_DIM":     "#D0A878",
        "TEXT_MUTED":   "#8A6848",
        "BORDER":       "#6A3E20",
        "SEP":          "#4A2812",
        "CANVAS_BG":    "#2A1408",
        "GRID_COLOR":   "#3A1E10",
        "FRONT_BG":     "#E87428",
        "FRONT_FG":     "#1A0A04",
        "TABLE_BG":     "#5A3418",
        "TABLE_BORDER": "#C85A18",
        "TABLE_SEL":    "#F09048",
        "TABLE_LABEL":  "#FBEAD0",
        "STUDENT_FG":   "#FBEAD0",
        "SEAT_DOT":     "#E87428",
        "EMPTY_FG":     "#6A4828",
        "BANNER_BG":    "#4A2812",
        "BANNER_FG":    "#F0A858",
        "BANNER_X_FG":  "#8A6848",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#7A3A14", "#FBD898"),
            ("#8A4818", "#FFE4A8"),
            ("#6A3818", "#F4C880"),
            ("#5A2A10", "#E4A878"),
            ("#8A4A1A", "#F4D098"),
            ("#6A4018", "#E8C088"),
            ("#4A2810", "#D4A070"),
            ("#7A2A0C", "#F4B080"),
        ],
    },

    "Winter": {
        "BG":           "#D4E4F0",
        "SIDEBAR_BG":   "#0A2038",
        "SIDEBAR_ACT":  "#1A3858",
        "PANEL":        "#E8F0F8",
        "ACCENT":       "#1E5FA8",
        "ACCENT_DARK":  "#0E4888",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#C83840",
        "DANGER_DARK":  "#A02830",
        "SUCCESS":      "#288878",
        "SUCCESS_DARK": "#1A6858",
        "GHOST_BG":     "#B4CCDE",
        "GHOST_DARK":   "#98B4C8",
        "TEXT":         "#0A2038",
        "SIDEBAR_TEXT": "#D4E4F0",
        "TEXT_DIM":     "#345878",
        "TEXT_MUTED":   "#6C88A4",
        "BORDER":       "#8AA8C0",
        "SEP":          "#B0C4D6",
        "CANVAS_BG":    "#A8C0D4",
        "GRID_COLOR":   "#90AAC0",
        "FRONT_BG":     "#1E5FA8",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#E0ECF6",
        "TABLE_BORDER": "#3878B0",
        "TABLE_SEL":    "#1E5FA8",
        "TABLE_LABEL":  "#FFFFFF",
        "STUDENT_FG":   "#0A2038",
        "SEAT_DOT":     "#1E5FA8",
        "EMPTY_FG":     "#7890A8",
        "BANNER_BG":    "#C8DCEE",
        "BANNER_FG":    "#0E4888",
        "BANNER_X_FG":  "#688AA8",
        "font":         "Modern",
        "TABLE_COLORS": [
            ("#B4D0E8", "#0A3860"),
            ("#BEC8E8", "#1A2870"),
            ("#A8C4D0", "#0A3850"),
            ("#D4BCD8", "#581868"),
            ("#B8CCE0", "#184870"),
            ("#C4C8DC", "#282858"),
            ("#CAC4E4", "#30307C"),
            ("#A8BCC8", "#102838"),
        ],
    },

    "Spring": {
        "BG":           "#C4E8BC",
        "SIDEBAR_BG":   "#1A4220",
        "SIDEBAR_ACT":  "#2A5830",
        "PANEL":        "#D8F0D0",
        "ACCENT":       "#E05088",
        "ACCENT_DARK":  "#B83870",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#C84050",
        "DANGER_DARK":  "#A02838",
        "SUCCESS":      "#288838",
        "SUCCESS_DARK": "#186828",
        "GHOST_BG":     "#A8D8A0",
        "GHOST_DARK":   "#90C488",
        "TEXT":         "#1A3020",
        "SIDEBAR_TEXT": "#C4E8BC",
        "TEXT_DIM":     "#3A5838",
        "TEXT_MUTED":   "#688868",
        "BORDER":       "#6EA868",
        "SEP":          "#A0C898",
        "CANVAS_BG":    "#98C890",
        "GRID_COLOR":   "#80B478",
        "FRONT_BG":     "#E05088",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#D0ECC8",
        "TABLE_BORDER": "#288838",
        "TABLE_SEL":    "#E05088",
        "TABLE_LABEL":  "#FFFFFF",
        "STUDENT_FG":   "#1A3020",
        "SEAT_DOT":     "#E05088",
        "EMPTY_FG":     "#6A906A",
        "BANNER_BG":    "#F0C0D0",
        "BANNER_FG":    "#B83870",
        "BANNER_X_FG":  "#88A888",
        "font":         "Friendly",
        "TABLE_COLORS": [
            ("#9ED49E", "#184820"),
            ("#F0B4C8", "#A02858"),
            ("#D8DC98", "#485818"),
            ("#F0D088", "#804818"),
            ("#A4C4E8", "#184878"),
            ("#D4B4E0", "#501878"),
            ("#A8D8C0", "#185838"),
            ("#F0BC94", "#683010"),
        ],
    },

    "Summer": {
        "BG":           "#F4D878",
        "SIDEBAR_BG":   "#0A4858",
        "SIDEBAR_ACT":  "#186878",
        "PANEL":        "#F8E89C",
        "ACCENT":       "#E85028",
        "ACCENT_DARK":  "#C03818",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#D02820",
        "DANGER_DARK":  "#A81810",
        "SUCCESS":      "#18A090",
        "SUCCESS_DARK": "#108078",
        "GHOST_BG":     "#E8C458",
        "GHOST_DARK":   "#D4B040",
        "TEXT":         "#2A2008",
        "SIDEBAR_TEXT": "#F4D878",
        "TEXT_DIM":     "#584010",
        "TEXT_MUTED":   "#8C6C28",
        "BORDER":       "#B88830",
        "SEP":          "#E0C458",
        "CANVAS_BG":    "#18A0A8",
        "GRID_COLOR":   "#148088",
        "FRONT_BG":     "#E85028",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#F8E498",
        "TABLE_BORDER": "#E85028",
        "TABLE_SEL":    "#FF7840",
        "TABLE_LABEL":  "#2A2008",
        "STUDENT_FG":   "#2A2008",
        "SEAT_DOT":     "#E85028",
        "EMPTY_FG":     "#A88838",
        "BANNER_BG":    "#E0C458",
        "BANNER_FG":    "#884018",
        "BANNER_X_FG":  "#8C6C28",
        "font":         "Friendly",
        "TABLE_COLORS": [
            ("#18A0A8", "#FFFFE8"),
            ("#F8C050", "#2A2008"),
            ("#E85028", "#FFFFE8"),
            ("#98D830", "#1A3008"),
            ("#E02878", "#FFFFE8"),
            ("#2868C8", "#FFFFE8"),
            ("#F08838", "#2A1808"),
            ("#1DA878", "#FFFFE8"),
        ],
    },

    # Cream paper, navy ink, red margin line. Inspired by a spiral-bound
    # notebook: warm paper surface + dark navy ink + the classic red rule
    # used for margins and corrections. A little nostalgic, easy on the
    # eyes for long sessions.
    "Notebook": {
        "BG":           "#F5EFDF",
        "SIDEBAR_BG":   "#1E2A3E",
        "SIDEBAR_ACT":  "#14203A",
        "PANEL":        "#FDF9EC",
        "ACCENT":       "#C03030",
        "ACCENT_DARK":  "#9C2424",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#A83020",
        "DANGER_DARK":  "#882418",
        "SUCCESS":      "#3A7028",
        "SUCCESS_DARK": "#2C5820",
        "GHOST_BG":     "#E8DFC6",
        "GHOST_DARK":   "#D4CAAA",
        "TEXT":         "#1A2A44",
        "SIDEBAR_TEXT": "#F5EFDF",
        "TEXT_DIM":     "#4A5870",
        "TEXT_MUTED":   "#8A8878",
        "BORDER":       "#C8BC9C",
        "SEP":          "#E0D4B8",
        "CANVAS_BG":    "#EDE4CC",
        "GRID_COLOR":   "#D8CCA8",
        "FRONT_BG":     "#1E2A3E",
        "FRONT_FG":     "#F5EFDF",
        "TABLE_BG":     "#FDF9EC",
        "TABLE_BORDER": "#1E2A3E",
        "TABLE_SEL":    "#C03030",
        "TABLE_LABEL":  "#1A2A44",
        "STUDENT_FG":   "#1A2A44",
        "SEAT_DOT":     "#1E2A3E",
        "EMPTY_FG":     "#A89878",
        "BANNER_BG":    "#FFF4C8",
        "BANNER_FG":    "#806018",
        "BANNER_X_FG":  "#A08040",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#F8ECCC", "#5A3818"),
            ("#E8DDE8", "#582060"),
            ("#D8E8F0", "#1E3A6A"),
            ("#F0D8D8", "#802020"),
            ("#D8E8D8", "#285828"),
            ("#F0E4C8", "#705030"),
            ("#E8DCF0", "#402888"),
            ("#F8D8C8", "#8A3818"),
        ],
    },

    # Classroom chalkboard: cool slate-charcoal surface (not green) with
    # soft warm-white chalk text and pastel chalk accents (yellow, pink,
    # blue). Runs cooler and darker than Forest, which is warm-green-
    # toned. The "chalkiness" shows in the slight blue-gray cast.
    "Blackboard": {
        "BG":           "#1E2028",
        "SIDEBAR_BG":   "#0E1014",
        "SIDEBAR_ACT":  "#14161C",
        "PANEL":        "#252830",
        "ACCENT":       "#F0D860",
        "ACCENT_DARK":  "#C8B248",
        "ACCENT_TEXT":  "#1E2028",
        "DANGER":       "#E88890",
        "DANGER_DARK":  "#C06870",
        "SUCCESS":      "#90CCE0",
        "SUCCESS_DARK": "#70ACC0",
        "GHOST_BG":     "#2E3240",
        "GHOST_DARK":   "#242730",
        "TEXT":         "#F4EED8",
        "SIDEBAR_TEXT": "#F4EED8",
        "TEXT_DIM":     "#A8ACB8",
        "TEXT_MUTED":   "#5C606C",
        "BORDER":       "#3A3E4C",
        "SEP":          "#282A34",
        "CANVAS_BG":    "#14161C",
        "GRID_COLOR":   "#1E2028",
        "FRONT_BG":     "#3A3E4C",
        "FRONT_FG":     "#F4EED8",
        "TABLE_BG":     "#1E2028",
        "TABLE_BORDER": "#A8ACB8",
        "TABLE_SEL":    "#F0D860",
        "TABLE_LABEL":  "#F4EED8",
        "STUDENT_FG":   "#F4EED8",
        "SEAT_DOT":     "#F0D860",
        "EMPTY_FG":     "#484C58",
        "BANNER_BG":    "#3A3420",
        "BANNER_FG":    "#F0D070",
        "BANNER_X_FG":  "#A89438",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#2A2C38", "#F0D860"),
            ("#38282C", "#F0A8C0"),
            ("#282C38", "#A8C8E8"),
            ("#2C3628", "#C0D890"),
            ("#382E28", "#F0B888"),
            ("#2A2A38", "#B0A8E0"),
            ("#28342E", "#90D8B8"),
            ("#38302C", "#F0C890"),
        ],
    },

    # Bright clean whiteboard — nearly pure white surface with real dry-
    # erase marker colors as accents. The lightest, cleanest preset.
    # Designed for maximum contrast and minimum distraction.
    "Whiteboard": {
        "BG":           "#FAFAFA",
        "SIDEBAR_BG":   "#2B2B2B",
        "SIDEBAR_ACT":  "#1E1E1E",
        "PANEL":        "#FFFFFF",
        "ACCENT":       "#0670D4",
        "ACCENT_DARK":  "#0558A8",
        "ACCENT_TEXT":  "#FFFFFF",
        "DANGER":       "#D8302C",
        "DANGER_DARK":  "#B02420",
        "SUCCESS":      "#1C8838",
        "SUCCESS_DARK": "#156A2C",
        "GHOST_BG":     "#F0F0F0",
        "GHOST_DARK":   "#E0E0E0",
        "TEXT":         "#1A1A1A",
        "SIDEBAR_TEXT": "#FFFFFF",
        "TEXT_DIM":     "#5A5A5A",
        "TEXT_MUTED":   "#989898",
        "BORDER":       "#D8D8D8",
        "SEP":          "#E8E8E8",
        "CANVAS_BG":    "#F5F5F5",
        "GRID_COLOR":   "#E0E0E0",
        "FRONT_BG":     "#2B2B2B",
        "FRONT_FG":     "#FFFFFF",
        "TABLE_BG":     "#FFFFFF",
        "TABLE_BORDER": "#2B2B2B",
        "TABLE_SEL":    "#0670D4",
        "TABLE_LABEL":  "#1A1A1A",
        "STUDENT_FG":   "#1A1A1A",
        "SEAT_DOT":     "#0670D4",
        "EMPTY_FG":     "#C0C0C0",
        "BANNER_BG":    "#FFF4CC",
        "BANNER_FG":    "#886A14",
        "BANNER_X_FG":  "#A8891C",
        "font":         "Modern",
        "TABLE_COLORS": [
            ("#FFFFFF", "#0670D4"),
            ("#FFFFFF", "#D8302C"),
            ("#FFFFFF", "#1C8838"),
            ("#FFFFFF", "#6A32B8"),
            ("#FFFFFF", "#D87810"),
            ("#FFFFFF", "#1A1A1A"),
            ("#FFFFFF", "#AC1864"),
            ("#FFFFFF", "#148C8C"),
        ],
    },

    # Reading-room library: deep bottle-green leather, brass accents,
    # cream page-edges. Evokes a Carnegie reading room or a classic
    # college library. Green-dominant to differentiate from warm-brown
    # Autumn — the warmth in Library comes from brass and parchment,
    # not wood.
    "Library": {
        "BG":           "#14241E",
        "SIDEBAR_BG":   "#0A1612",
        "SIDEBAR_ACT":  "#0F1E18",
        "PANEL":        "#1C302A",
        "ACCENT":       "#C89848",
        "ACCENT_DARK":  "#A67C34",
        "ACCENT_TEXT":  "#14241E",
        "DANGER":       "#B03828",
        "DANGER_DARK":  "#8C2A1C",
        "SUCCESS":      "#68A850",
        "SUCCESS_DARK": "#4E8038",
        "GHOST_BG":     "#284038",
        "GHOST_DARK":   "#1E302A",
        "TEXT":         "#EDE1C4",
        "SIDEBAR_TEXT": "#D8C49C",
        "TEXT_DIM":     "#A89878",
        "TEXT_MUTED":   "#6E6048",
        "BORDER":       "#30483E",
        "SEP":          "#1F2E28",
        "CANVAS_BG":    "#0E1C16",
        "GRID_COLOR":   "#18241E",
        "FRONT_BG":     "#5A2A1C",
        "FRONT_FG":     "#EDE1C4",
        "TABLE_BG":     "#1A2C26",
        "TABLE_BORDER": "#C89848",
        "TABLE_SEL":    "#E8B860",
        "TABLE_LABEL":  "#EDE1C4",
        "STUDENT_FG":   "#EDE1C4",
        "SEAT_DOT":     "#C89848",
        "EMPTY_FG":     "#3A4A40",
        "BANNER_BG":    "#2E2810",
        "BANNER_FG":    "#D8AC58",
        "BANNER_X_FG":  "#887838",
        "font":         "Classic",
        "TABLE_COLORS": [
            ("#1E3028", "#C89848"),
            ("#2A1E1A", "#D08858"),
            ("#1A2A30", "#98B8D0"),
            ("#281820", "#C890A0"),
            ("#1E2E20", "#A0C880"),
            ("#28241E", "#D8B878"),
            ("#1A2228", "#8898C0"),
            ("#2A2018", "#C89880"),
        ],
    },

    # Clinical research lab: cool blue-gray surfaces like stainless
    # steel benches under fluorescent light, with a single cyan-green
    # accent (pH indicator / biohazard sign). Runs cooler and chromier
    # than the warm paper-white Whiteboard theme.
    "Lab": {
        "BG":           "#E6ECF0",
        "SIDEBAR_BG":   "#1A242E",
        "SIDEBAR_ACT":  "#14202A",
        "PANEL":        "#F4F7F9",
        "ACCENT":       "#18B8A0",
        "ACCENT_DARK":  "#109080",
        "ACCENT_TEXT":  "#0A1A1E",
        "DANGER":       "#D83848",
        "DANGER_DARK":  "#B02838",
        "SUCCESS":      "#18B8A0",
        "SUCCESS_DARK": "#109080",
        "GHOST_BG":     "#D2DADF",
        "GHOST_DARK":   "#B8C2C8",
        "TEXT":         "#14202A",
        "SIDEBAR_TEXT": "#CED6DE",
        "TEXT_DIM":     "#586874",
        "TEXT_MUTED":   "#8E9AA4",
        "BORDER":       "#BCC6CE",
        "SEP":          "#D0D8DE",
        "CANVAS_BG":    "#DCE4EA",
        "GRID_COLOR":   "#C4CED6",
        "FRONT_BG":     "#1A242E",
        "FRONT_FG":     "#E6ECF0",
        "TABLE_BG":     "#F4F7F9",
        "TABLE_BORDER": "#1A242E",
        "TABLE_SEL":    "#18B8A0",
        "TABLE_LABEL":  "#14202A",
        "STUDENT_FG":   "#14202A",
        "SEAT_DOT":     "#18B8A0",
        "EMPTY_FG":     "#A4AEB8",
        "BANNER_BG":    "#FDE8D0",
        "BANNER_FG":    "#805020",
        "BANNER_X_FG":  "#A8783C",
        "font":         "Modern",
        "TABLE_COLORS": [
            ("#D4EAE6", "#0E6858"),
            ("#D4DCE8", "#243878"),
            ("#E4D8E8", "#58207C"),
            ("#E8D8D8", "#802028"),
            ("#E4E4D8", "#585020"),
            ("#D8E4E4", "#105868"),
            ("#E8DCD0", "#704010"),
            ("#D8E4D4", "#285018"),
        ],
    },

    # Classic CRT terminal: phosphor green on black. Monospace throughout
    # via the Sharp font pairing. A tight palette because real VT100s
    # didn't have many colors. Accents are bright phosphor green; danger
    # is amber (the "second color" on some old terminals).
    "Retro Terminal": {
        "BG":           "#0A0F08",
        "SIDEBAR_BG":   "#000000",
        "SIDEBAR_ACT":  "#081008",
        "PANEL":        "#101810",
        "ACCENT":       "#48D848",
        "ACCENT_DARK":  "#38B038",
        "ACCENT_TEXT":  "#000000",
        "DANGER":       "#E8A818",
        "DANGER_DARK":  "#B08410",
        "SUCCESS":      "#48D848",
        "SUCCESS_DARK": "#38B038",
        "GHOST_BG":     "#18241C",
        "GHOST_DARK":   "#101810",
        "TEXT":         "#58E858",
        "SIDEBAR_TEXT": "#48D848",
        "TEXT_DIM":     "#389038",
        "TEXT_MUTED":   "#1C5020",
        "BORDER":       "#203828",
        "SEP":          "#162018",
        "CANVAS_BG":    "#050905",
        "GRID_COLOR":   "#101C10",
        "FRONT_BG":     "#1C4020",
        "FRONT_FG":     "#58E858",
        "TABLE_BG":     "#0E1810",
        "TABLE_BORDER": "#48D848",
        "TABLE_SEL":    "#A0F8A0",
        "TABLE_LABEL":  "#58E858",
        "STUDENT_FG":   "#A0F8A0",
        "SEAT_DOT":     "#48D848",
        "EMPTY_FG":     "#1C4020",
        "BANNER_BG":    "#2A2010",
        "BANNER_FG":    "#E8A818",
        "BANNER_X_FG":  "#887018",
        "font":         "Sharp",
        "TABLE_COLORS": [
            ("#0E1810", "#48D848"),
            ("#0E1810", "#A0F8A0"),
            ("#0E1810", "#88E888"),
            ("#0E1810", "#68C868"),
            ("#0E1810", "#70E070"),
            ("#0E1810", "#50C858"),
            ("#0E1810", "#90F090"),
            ("#0E1810", "#40B040"),
        ],
    },
}

# ── Active theme state (module-level globals) ─────────────────────────────────
# These are the names imported by ui.py and room_canvas.py.
# Calling apply() rewrites them in-place.

BG           = ""
SIDEBAR_BG   = ""
SIDEBAR_ACT  = ""
PANEL        = ""
ACCENT       = ""
ACCENT_DARK  = ""
ACCENT_TEXT  = ""
DANGER       = ""
DANGER_DARK  = ""
SUCCESS      = ""
SUCCESS_DARK = ""
GHOST_BG     = ""
GHOST_DARK   = ""
TEXT         = ""
TEXT_DIM     = ""
TEXT_MUTED   = ""
SIDEBAR_TEXT = ""
BORDER       = ""
SEP          = ""
CANVAS_BG    = ""
GRID_COLOR   = ""
FRONT_BG     = ""
FRONT_FG     = ""
TABLE_BG     = ""
TABLE_BORDER = ""
TABLE_SEL    = ""
TABLE_LABEL  = ""
STUDENT_FG   = ""
SEAT_DOT     = ""
EMPTY_FG     = ""
BANNER_BG    = ""
BANNER_FG    = ""
BANNER_X_FG  = ""
TABLE_COLORS: list = []

# Font tuples — rebuilt by apply()
FONT_TITLE: tuple = ()
FONT_HEAD:  tuple = ()
FONT_BODY:  tuple = ()
FONT_SMALL: tuple = ()
FONT_BOLD:  tuple = ()

# Current names (readable by UI)
ACTIVE_PRESET = "Midnight"
ACTIVE_FONT   = "Classic"
ACTIVE_FONT_SIZE = "Medium"

# Font size scale multipliers. Names are user-facing; values are multipliers
# applied to the base font sizes.
FONT_SIZES: dict[str, float] = {
    "Small":  0.85,
    "Medium": 1.00,
    "Large":  1.15,
    "XL":     1.30,
}


def _build_fonts(pairing_name: str, size_name: str = "Medium"):
    """Populate FONT_* tuples from the named pairing at the given size."""
    global FONT_TITLE, FONT_HEAD, FONT_BODY, FONT_SMALL, FONT_BOLD
    p = FONT_PAIRINGS.get(pairing_name, FONT_PAIRINGS["Classic"])
    d = p["display"]
    b = p["body"]
    scale = FONT_SIZES.get(size_name, 1.00)
    def sz(base: int) -> int:
        return max(1, int(round(base * scale)))
    FONT_TITLE = (d, sz(22), "bold")
    FONT_HEAD  = (d, sz(13), "bold")
    FONT_BODY  = (b, sz(11))
    FONT_SMALL = (b, sz(10))
    FONT_BOLD  = (b, sz(11), "bold")


def apply(preset_name: str, font_name: str | None = None,
          font_size: str | None = None, persist: bool = True):
    """
    Switch to a named preset (and optionally a named font pairing and size).
    Rewrites all module-level colour globals in-place.
    Persists the choice to the DB unless persist=False (used by the module
    bootstrap to avoid overwriting saved preferences before load_from_db
    has had a chance to read them).
    """
    global BG, SIDEBAR_BG, SIDEBAR_ACT, PANEL, ACCENT, ACCENT_DARK
    global ACCENT_TEXT, DANGER, DANGER_DARK, SUCCESS, SUCCESS_DARK
    global GHOST_BG, GHOST_DARK, TEXT, TEXT_DIM, TEXT_MUTED, SIDEBAR_TEXT, BORDER, SEP
    global CANVAS_BG, GRID_COLOR, FRONT_BG, FRONT_FG
    global TABLE_BG, TABLE_BORDER, TABLE_SEL, TABLE_LABEL
    global STUDENT_FG, SEAT_DOT, EMPTY_FG
    global BANNER_BG, BANNER_FG, BANNER_X_FG, TABLE_COLORS
    global ACTIVE_PRESET, ACTIVE_FONT, ACTIVE_FONT_SIZE

    p = PRESETS.get(preset_name, PRESETS["Midnight"])

    BG           = p["BG"]
    SIDEBAR_BG   = p["SIDEBAR_BG"]
    SIDEBAR_ACT  = p["SIDEBAR_ACT"]
    PANEL        = p["PANEL"]
    ACCENT       = p["ACCENT"]
    ACCENT_DARK  = p["ACCENT_DARK"]
    ACCENT_TEXT  = p["ACCENT_TEXT"]
    DANGER       = p["DANGER"]
    DANGER_DARK  = p["DANGER_DARK"]
    SUCCESS      = p["SUCCESS"]
    SUCCESS_DARK = p["SUCCESS_DARK"]
    GHOST_BG     = p["GHOST_BG"]
    GHOST_DARK   = p["GHOST_DARK"]
    TEXT         = p["TEXT"]
    TEXT_DIM     = p["TEXT_DIM"]
    TEXT_MUTED   = p["TEXT_MUTED"]
    SIDEBAR_TEXT = p.get("SIDEBAR_TEXT", "#FFFFFF")
    BORDER       = p["BORDER"]
    SEP          = p["SEP"]
    CANVAS_BG    = p["CANVAS_BG"]
    GRID_COLOR   = p["GRID_COLOR"]
    FRONT_BG     = p["FRONT_BG"]
    FRONT_FG     = p["FRONT_FG"]
    TABLE_BG     = p["TABLE_BG"]
    TABLE_BORDER = p["TABLE_BORDER"]
    TABLE_SEL    = p["TABLE_SEL"]
    TABLE_LABEL  = p["TABLE_LABEL"]
    STUDENT_FG   = p["STUDENT_FG"]
    SEAT_DOT     = p["SEAT_DOT"]
    EMPTY_FG     = p["EMPTY_FG"]
    BANNER_BG    = p["BANNER_BG"]
    BANNER_FG    = p["BANNER_FG"]
    BANNER_X_FG  = p["BANNER_X_FG"]
    TABLE_COLORS = p["TABLE_COLORS"]

    # Font: explicit override > preset default > keep current
    chosen_font = font_name or p.get("font", "Classic")
    chosen_size = font_size or ACTIVE_FONT_SIZE or "Medium"
    _build_fonts(chosen_font, chosen_size)

    ACTIVE_PRESET = preset_name
    ACTIVE_FONT   = chosen_font
    ACTIVE_FONT_SIZE = chosen_size

    # Persist (unless called from the bootstrap before load_from_db)
    if persist:
        try:
            db.set_setting("theme_preset", preset_name)
            db.set_setting("theme_font",   chosen_font)
            db.set_setting("theme_font_size", chosen_size)
        except Exception:
            pass  # DB may not be initialised yet on first import


def load_from_db():
    """Read saved preferences and apply them. Call once at startup after init_db()."""
    try:
        preset = db.get_setting("theme_preset", "Midnight")
        font   = db.get_setting("theme_font",   "Classic")
        size   = db.get_setting("theme_font_size", "Medium")
    except Exception:
        preset, font, size = "Midnight", "Classic", "Medium"
    apply(preset, font, size)


# Bootstrap with defaults so module globals are never empty strings.
# persist=False ensures this doesn't clobber saved user preferences before
# load_from_db() has a chance to read them at app startup.
apply("Midnight", "Classic", "Medium", persist=False)