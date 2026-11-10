"""Design tokens — copied verbatim from reference/react-ui/app/globals.css (and Tailwind v4 / shadcn
defaults the React app relies on). Swap brand values here and in assets/theme.css together.
"""

from __future__ import annotations

# --- colors (globals.css :root) -------------------------------------------------------------
BRAND_PRIMARY = "#00A0DF"
BRAND_PRIMARY_DARK = "#0072AE"
BRAND_NAVY = "#003D5C"
INK_900 = "#1A1A1A"
INK_600 = "#5B6670"
INK_300 = "#C5CBD1"
SURFACE_0 = "#FFFFFF"
SURFACE_50 = "#F5F7F9"
SURFACE_100 = "#EBEFF2"
POSITIVE = "#2E8540"
NEGATIVE = "#C8102E"
WARNING = "#E8A317"
WARNING_TEXT = "#9A6A00"  # drifting status pill text (app/page.tsx)
LOGIN_ACCENT = "#7FCFEF"  # login illustration stroke (app/login/page.tsx)
TEAL = "#00857C"  # login glow rgba(0,133,124,.45)

# --- shape / elevation ----------------------------------------------------------------------
RADIUS_BUTTON = "8px"  # Tailwind rounded-lg
RADIUS_CARD = "12px"  # Tailwind rounded-xl
SHADOW_CARD = "0 1px 3px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.04)"
SHADOW_SM = "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)"
SPACING_UNIT = 4  # Tailwind --spacing: 0.25rem (layouts use the 8px grid)

# --- type -----------------------------------------------------------------------------------
FONT_FAMILY = "Inter, 'Helvetica Neue', Arial, sans-serif"
TYPE_SCALE = {  # px size / line-height (Tailwind defaults used by the reference)
    "xs": (12, 16),
    "sm": (14, 20),
    "base": (16, 24),
    "lg": (18, 28),
    "xl": (20, 28),
    "2xl": (24, 32),
    "3xl": (30, 36),
    "5xl": (48, 52),
}

# --- charts -----------------------------------------------------------------------------------
COLORWAY = [BRAND_PRIMARY, BRAND_NAVY, TEAL, "#7FCFEF", "#8C8279"]  # blue, navy, teal, light blue, warm gray

# DMC/Mantine needs a 10-shade palette; index 5 = brand primary, 7 = brand primary dark
BRAND_SCALE = [
    "#E5F6FC", "#CCEDF9", "#99DBF2", "#66C9EC", "#33B7E5",
    "#00A0DF", "#0089C6", "#0072AE", "#005A87", "#003D5C",
]
