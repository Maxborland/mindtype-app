"""
Design Tokens для MindType UI.

Централизованные константы дизайн-системы.
Вдохновлено Apple System OS (1984-1991) / system.css.

Использование:
    from .tokens import COLORS, TYPOGRAPHY, SPACING, BORDERS, RADII
"""

from typing import Dict, Any


# =============================================================================
# COLOR SYSTEM
# =============================================================================

COLORS: Dict[str, Dict[str, str]] = {
    # Surface colors (backgrounds)
    "surface": {
        "primary": "#ffffff",      # Main background
        "secondary": "#f8f8f8",    # Subtle sections
        "tertiary": "#dddddd",     # Info boxes, disabled bg
        "elevated": "#ffffff",     # Cards, dialogs
        "inverse": "#000000",      # Inverted elements
    },

    # Border colors
    "border": {
        "default": "#000000",      # Standard border
        "subtle": "#808080",       # Subtle separators
        "muted": "#c0c0c0",        # Disabled borders
    },

    # Text colors
    "text": {
        "primary": "#000000",      # Main text
        "secondary": "#606060",    # Less important text
        "muted": "#808080",        # Placeholders, hints
        "disabled": "#b0b0b0",     # Disabled text
        "inverse": "#ffffff",      # Text on dark bg
    },

    # Interactive states
    "interactive": {
        "hover": "#f0f0f0",        # Hover background
        "active": "#e0e0e0",       # Active/pressed light
        "pressed": "#000000",      # Pressed/selected bg
        "pressed_text": "#ffffff", # Text when pressed
        "focus_ring": "#000000",   # Focus outline
    },

    # Semantic colors (minimal - B&W aesthetic)
    "semantic": {
        "recording": "#ff3c3c",    # Recording indicator only
        "recording_bg": "#ffeeee", # Recording background tint
    },
}


# =============================================================================
# TYPOGRAPHY SYSTEM
# =============================================================================

# Font stack - ChicagoFLF для ретро-эстетики, fallback на системные
FONT_FAMILY = '"ChicagoFLF", "Chicago", "Geneva", "Segoe UI", "Arial", sans-serif'
FONT_FAMILY_MONO = '"Consolas", "Courier New", "Monaco", monospace'

# Type scale (ratio 1.25 - Major Third)
TYPOGRAPHY: Dict[str, Dict[str, Any]] = {
    "display": {
        "size": 24,
        "weight": "bold",
        "line_height": 1.2,
    },
    "title": {
        "size": 18,
        "weight": "bold",
        "line_height": 1.3,
    },
    "subtitle": {
        "size": 14,
        "weight": "bold",
        "line_height": 1.4,
    },
    "body": {
        "size": 12,
        "weight": "normal",
        "line_height": 1.5,
    },
    "body_bold": {
        "size": 12,
        "weight": "bold",
        "line_height": 1.5,
    },
    "caption": {
        "size": 11,
        "weight": "normal",
        "line_height": 1.4,
    },
    "small": {
        "size": 10,
        "weight": "normal",
        "line_height": 1.4,
    },
}


# =============================================================================
# SPACING SYSTEM (4px base grid)
# =============================================================================

SPACING: Dict[str, int] = {
    "none": 0,
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
    "xxxl": 48,
}


# =============================================================================
# BORDER SYSTEM
# =============================================================================

BORDERS: Dict[str, str] = {
    "none": "none",
    "thin": "1px",
    "default": "1.5px",
    "thick": "2px",
    "accent": "3px",
}

BORDER_STYLES: Dict[str, str] = {
    "solid": "solid",
    "dashed": "dashed",
    "dotted": "dotted",
}


# =============================================================================
# BORDER RADIUS
# =============================================================================

RADII: Dict[str, str] = {
    "none": "0",
    "sm": "4px",
    "md": "6px",              # Standard button radius
    "button": "6px",          # System 7 button radius
    "lg": "8px",
    "button_default": "8px",  # Primary/default button radius
    "xl": "12px",
    "full": "9999px",
}


# =============================================================================
# SYSTEM 7 DIMENSIONS
# =============================================================================

SYSTEM7: Dict[str, Any] = {
    "button": {
        "min_width": 59,
        "min_height": 20,
        "radius": 6,
        "padding_x": 16,
        "padding_y": 4,
    },
    "button_default": {
        "outer_border": 2,
        "inner_border": 3,
        "radius": 8,
    },
    "checkbox": {
        "size": 12,
        "border": 1.5,
    },
    "radio": {
        "size": 12,
        "dot_size": 6,
        "border": 1.5,
    },
    "title_bar": {
        "height": 19,
        "stripe_height": 2,
        "stripe_gap": 2,
    },
    "modal": {
        "outer_border": 2,
        "inner_border": 3.5,
    },
    "window_control": {
        "size": 13,
        "border": 2,
    },
}


# =============================================================================
# SHADOWS (minimal for B&W aesthetic)
# =============================================================================

SHADOWS: Dict[str, str] = {
    "none": "none",
    # System 7 style - no drop shadows, use borders instead
    "inset": "inset 1px 1px 0 #000000",
}


# =============================================================================
# Z-INDEX SCALE
# =============================================================================

Z_INDEX: Dict[str, int] = {
    "base": 0,
    "dropdown": 100,
    "sticky": 200,
    "modal": 300,
    "overlay": 400,
    "tooltip": 500,
}


# =============================================================================
# ANIMATION (minimal)
# =============================================================================

ANIMATION: Dict[str, str] = {
    "duration_fast": "100ms",
    "duration_normal": "200ms",
    "duration_slow": "300ms",
    "easing": "ease-out",
}


# =============================================================================
# COMPONENT SIZES
# =============================================================================

SIZES: Dict[str, Dict[str, int]] = {
    "button": {
        "height_sm": 24,
        "height_md": 32,
        "height_lg": 40,
        "padding_x": 16,
        "padding_x_sm": 10,
    },
    "input": {
        "height": 28,
        "padding_x": 8,
        "padding_y": 4,
    },
    "icon": {
        "sm": 12,
        "md": 16,
        "lg": 20,
        "xl": 24,
    },
    "card": {
        "padding": 16,
        "padding_sm": 12,
        "padding_lg": 24,
    },
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_color(category: str, variant: str = "primary") -> str:
    """Get color by category and variant.

    Example:
        get_color("text", "muted") -> "#808080"
        get_color("surface") -> "#ffffff"
    """
    return COLORS.get(category, {}).get(variant, "#000000")


def get_spacing(size: str = "md") -> int:
    """Get spacing value in pixels.

    Example:
        get_spacing("lg") -> 16
    """
    return SPACING.get(size, 12)


def get_font_style(variant: str = "body") -> str:
    """Get QSS font style string.

    Example:
        get_font_style("title") -> "font-size: 18px; font-weight: bold;"
    """
    style = TYPOGRAPHY.get(variant, TYPOGRAPHY["body"])
    parts = [f'font-size: {style["size"]}px']
    if style.get("weight") == "bold":
        parts.append("font-weight: bold")
    return "; ".join(parts) + ";"


def px(value: int) -> str:
    """Convert int to px string."""
    return f"{value}px"


# =============================================================================
# QSS GENERATION HELPERS
# =============================================================================

def make_border(width: str = "default", color: str = "default", style: str = "solid") -> str:
    """Generate border CSS string.

    Example:
        make_border("thick", "subtle") -> "2px solid #808080"
    """
    w = BORDERS.get(width, BORDERS["default"])
    c = COLORS["border"].get(color, COLORS["border"]["default"])
    s = BORDER_STYLES.get(style, "solid")
    return f"{w} {s} {c}"


def make_padding(top: str = "md", right: str = None, bottom: str = None, left: str = None) -> str:
    """Generate padding CSS string.

    Example:
        make_padding("lg") -> "16px"
        make_padding("sm", "lg") -> "8px 16px"
        make_padding("xs", "sm", "md", "lg") -> "4px 8px 12px 16px"
    """
    t = px(SPACING.get(top, 12))

    if right is None:
        return t

    r = px(SPACING.get(right, 12))

    if bottom is None:
        return f"{t} {r}"

    b = px(SPACING.get(bottom, 12))

    if left is None:
        return f"{t} {r} {b}"

    l = px(SPACING.get(left, 12))
    return f"{t} {r} {b} {l}"
