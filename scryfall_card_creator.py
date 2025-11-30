#!/usr/bin/env python3
"""
Scryfall Card Creator for Card Conjurer

This script uses the Scryfall API to fetch card information and creates
Magic: The Gathering cards using Fourth Edition frames with custom art.
Renders complete cards with title, mana cost, type line, rules text,
power/toughness, and artist credits.

Usage:
    python scryfall_card_creator.py "Card Name" path/to/art.png [output.png]

Example:
    python scryfall_card_creator.py "Lightning Bolt" bolt_art.png bolt_card.png
"""

import argparse
import sys
import os
import re
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from typing import Optional, Tuple, Dict, Any, List
import cairosvg

# Card dimensions (standard Magic card proportions)
CARD_WIDTH = 1500
CARD_HEIGHT = 2100

# Art bounds for Fourth Edition frames (normalized 0-1 coordinates)
ART_BOUNDS = {
    'x': 0.1034,      # Left edge (10.34% from left)
    'y': 0.0886,      # Top edge (8.86% from top)
    'width': 0.794,   # Width (79.4% of card width)
    'height': 0.4543  # Height (45.43% of card height)
}

# Text positions for Fourth Edition frames (normalized 0-1 coordinates)
TEXT_BOUNDS = {
    'mana': {
        'x': 0.1067, 'y': 0.0362, 'width': 0.8174, 'height': 72/2100,
        'size': 72/1638, 'align': 'right', 'mana_cost': True, 'one_line': True
    },
    'title': {
        'x': 0.0827, 'y': 0.031, 'width': 0.8347, 'height': 0.041,
        'size': 0.041, 'font': 'goudymedieval', 'color': 'white',
        'shadow_x': 0.002, 'shadow_y': 0.0015, 'one_line': True
    },
    'type': {
        'x': 0.0827, 'y': 0.5486, 'width': 0.8347, 'height': 0.0543,
        'size': 0.032, 'color': 'white',
        'shadow_x': 0.002, 'shadow_y': 0.0015, 'one_line': True
    },
    'rules': {
        'x': 0.128, 'y': 0.6067, 'width': 0.744, 'height': 0.2724,
        'size': 0.0358, 'color': 'black', 'justify': 'center'
    },
    'pt': {
        'x': 0.82, 'y': 0.9058, 'width': 0.1367, 'height': 0.0429,
        'size': 0.0429, 'align': 'center', 'color': 'white',
        'shadow_x': 0.002, 'shadow_y': 0.0015, 'one_line': True
    },
    'artist': {
        'x': 0.1, 'y': 1894/2100, 'width': 0.8, 'height': 0.0267,
        'size': 0.0267, 'color': 'white',
        'shadow_x': 0.0021, 'shadow_y': 0.0015, 'one_line': True
    },
    'copyright': {
        'x': 0.1, 'y': 1955/2100, 'width': 0.8, 'height': 0.0172,
        'size': 0.0172, 'color': 'white',
        'shadow_x': 0.0014, 'shadow_y': 0.001, 'one_line': True
    }
}

# Frame directory path (relative to this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRAME_DIR = os.path.join(SCRIPT_DIR, 'img', 'frames', 'old', 'fourth')
FONT_DIR = os.path.join(SCRIPT_DIR, 'fonts')
MANA_DIR = os.path.join(SCRIPT_DIR, 'img', 'manaSymbols')

# Frame mapping based on color/type
FRAME_FILES = {
    'W': 'w.png',      # White
    'U': 'u.png',      # Blue
    'B': 'b.png',      # Black
    'R': 'r.png',      # Red
    'G': 'g.png',      # Green
    'M': 'm.png',      # Multicolored
    'A': 'a.png',      # Artifact
    'L': 'l.png',      # Land (colorless)
}

# Border files
BORDER_FILES = {
    'black': 'borderBlack.png',
    'white': 'borderWhite.png',
}

# Basic land to color mapping
BASIC_LAND_COLORS = {
    'plains': 'W',
    'island': 'U',
    'swamp': 'B',
    'mountain': 'R',
    'forest': 'G',
}

# Scryfall API base URL
SCRYFALL_API = 'https://api.scryfall.com'

# Font mapping
FONT_FILES = {
    'goudymedieval': 'goudy-medieval.ttf',
    'mplantin': 'mplantin.ttf',
    'mplantini': 'mplantin-i.ttf',
    'belerenb': 'beleren-b.ttf',
    'matrixb': 'matrix-b.ttf',
}

# Mana symbol cache
_mana_cache: Dict[str, Image.Image] = {}

# Font cache
_font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font from the fonts directory with caching."""
    cache_key = (font_name, size)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    font_file = FONT_FILES.get(font_name, f'{font_name}.ttf')
    font_path = os.path.join(FONT_DIR, font_file)

    if not os.path.exists(font_path):
        # Try data/fonts as fallback
        font_path = os.path.join(SCRIPT_DIR, 'data', 'fonts', font_file)

    if not os.path.exists(font_path):
        print(f"Warning: Font not found: {font_name}, using default")
        font = ImageFont.load_default()
    else:
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception as e:
            print(f"Warning: Could not load font {font_name}: {e}")
            font = ImageFont.load_default()

    _font_cache[cache_key] = font
    return font


def load_mana_symbol(symbol: str, size: int) -> Optional[Image.Image]:
    """
    Load a mana symbol image from the manaSymbols directory.
    Supports SVG and PNG formats. Caches loaded symbols.
    """
    cache_key = f"{symbol}_{size}"
    if cache_key in _mana_cache:
        return _mana_cache[cache_key]

    # Map Scryfall mana symbols to file names
    symbol_lower = symbol.lower()

    # Check for old-style symbols first (for Fourth Edition)
    old_path = os.path.join(MANA_DIR, 'old', f'old{symbol_lower}.svg')
    if os.path.exists(old_path):
        symbol_path = old_path
    else:
        # Try regular symbol
        svg_path = os.path.join(MANA_DIR, f'{symbol_lower}.svg')
        png_path = os.path.join(MANA_DIR, f'{symbol_lower}.png')

        if os.path.exists(svg_path):
            symbol_path = svg_path
        elif os.path.exists(png_path):
            symbol_path = png_path
        else:
            print(f"Warning: Mana symbol not found: {symbol}")
            return None

    try:
        if symbol_path.endswith('.svg'):
            # Convert SVG to PNG using cairosvg
            png_data = cairosvg.svg2png(url=symbol_path, output_width=size, output_height=size)
            img = Image.open(BytesIO(png_data)).convert('RGBA')
        else:
            img = Image.open(symbol_path).convert('RGBA')
            img = img.resize((size, size), Image.Resampling.LANCZOS)

        _mana_cache[cache_key] = img
        return img
    except Exception as e:
        print(f"Warning: Could not load mana symbol {symbol}: {e}")
        return None


def parse_mana_cost(mana_cost: str) -> List[str]:
    """
    Parse a mana cost string from Scryfall format into individual symbols.
    Example: "{2}{U}{U}" -> ["2", "U", "U"]
    """
    if not mana_cost:
        return []

    # Match {X} patterns
    pattern = r'\{([^}]+)\}'
    matches = re.findall(pattern, mana_cost)
    return matches


def fetch_card_data(card_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch card data from Scryfall API.

    Args:
        card_name: The name of the card to search for

    Returns:
        Card data dictionary or None if not found
    """
    url = f"{SCRYFALL_API}/cards/named"
    params = {'fuzzy': card_name}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            print(f"Error: Card '{card_name}' not found on Scryfall")
        else:
            print(f"Error fetching card data: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Scryfall API: {e}")
        return None


def determine_frame_type(card_data: Dict[str, Any]) -> str:
    """
    Determine which frame to use based on card data.

    Args:
        card_data: Card data from Scryfall API

    Returns:
        Frame type identifier (W, U, B, R, G, M, A, or L)
    """
    colors = card_data.get('colors', [])
    color_identity = card_data.get('color_identity', [])
    type_line = card_data.get('type_line', '').lower()
    name = card_data.get('name', '').lower()

    # Check for basic lands first
    for land_name, color in BASIC_LAND_COLORS.items():
        if land_name in name.lower():
            print(f"Detected basic land '{name}' -> using {color} frame")
            return color

    # Check for multicolored cards
    if len(colors) > 1:
        print(f"Detected multicolored card with colors {colors}")
        return 'M'

    # Check for single-colored cards
    if len(colors) == 1:
        color = colors[0]
        print(f"Detected single-color card: {color}")
        return color

    # Colorless cards
    if 'artifact' in type_line:
        print("Detected artifact card")
        return 'A'

    if 'land' in type_line:
        # Check if land has color identity (like dual lands)
        if len(color_identity) > 1:
            print(f"Detected multicolored land with identity {color_identity}")
            return 'M'
        elif len(color_identity) == 1:
            color = color_identity[0]
            print(f"Detected colored land with identity {color}")
            return color
        print("Detected colorless land")
        return 'L'

    # Default to artifact frame for other colorless
    print("Defaulting to artifact frame for colorless card")
    return 'A'


def get_frame_path(frame_type: str) -> str:
    """
    Get the full path to a frame image.

    Args:
        frame_type: Frame type identifier

    Returns:
        Full path to the frame image file
    """
    filename = FRAME_FILES.get(frame_type, 'l.png')
    return os.path.join(FRAME_DIR, filename)


def load_image(path: str) -> Image.Image:
    """
    Load an image from a file path.

    Args:
        path: Path to the image file

    Returns:
        PIL Image object
    """
    return Image.open(path).convert('RGBA')


def calculate_art_placement(art: Image.Image) -> Tuple[int, int, int, int]:
    """
    Calculate art placement coordinates using the same logic as the JS auto-fit.

    This implements the autoFitArt() algorithm from creator-23.js:
    - Compare aspect ratios of art and bounds
    - If art is wider: fit to height, center horizontally
    - If art is taller: fit to width, center vertically

    Args:
        art: The art image to place

    Returns:
        Tuple of (x, y, width, height) for art placement
    """
    # Calculate art bounds in pixels
    bounds_x = int(ART_BOUNDS['x'] * CARD_WIDTH)
    bounds_y = int(ART_BOUNDS['y'] * CARD_HEIGHT)
    bounds_width = int(ART_BOUNDS['width'] * CARD_WIDTH)
    bounds_height = int(ART_BOUNDS['height'] * CARD_HEIGHT)

    art_width, art_height = art.size
    art_aspect = art_width / art_height
    bounds_aspect = bounds_width / bounds_height

    if art_aspect > bounds_aspect:
        # Art is wider than bounds: fit to height, center horizontally
        new_height = bounds_height
        new_width = int(art_width * (bounds_height / art_height))
        x = bounds_x - (new_width - bounds_width) // 2
        y = bounds_y
    else:
        # Art is taller than bounds: fit to width, center vertically
        new_width = bounds_width
        new_height = int(art_height * (bounds_width / art_width))
        x = bounds_x
        y = bounds_y - (new_height - bounds_height) // 2

    return (x, y, new_width, new_height)


def draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    text: str,
    position: Tuple[int, int],
    font: ImageFont.FreeTypeFont,
    color: str = 'white',
    shadow_color: str = 'black',
    shadow_offset: Tuple[int, int] = (3, 3)
) -> None:
    """Draw text with a shadow effect."""
    x, y = position
    sx, sy = shadow_offset

    # Draw shadow
    if sx != 0 or sy != 0:
        draw.text((x + sx, y + sy), text, font=font, fill=shadow_color)

    # Draw main text
    draw.text((x, y), text, font=font, fill=color)


def get_text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """Get the width and height of text when rendered."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_mana_cost(
    card: Image.Image,
    mana_cost: str,
    bounds: Dict[str, float]
) -> None:
    """
    Draw mana cost symbols on the card.

    Args:
        card: The card image to draw on
        mana_cost: Scryfall mana cost string (e.g., "{2}{U}{U}")
        bounds: Text bounds dictionary
    """
    symbols = parse_mana_cost(mana_cost)
    if not symbols:
        return

    # Calculate positions
    symbol_size = int(bounds['size'] * CARD_HEIGHT * 0.78)
    spacing = int(symbol_size * 0.1)

    # Calculate total width of mana cost
    total_width = len(symbols) * symbol_size + (len(symbols) - 1) * spacing

    # Right-aligned position
    bounds_right = int((bounds['x'] + bounds['width']) * CARD_WIDTH)
    bounds_y = int(bounds['y'] * CARD_HEIGHT)

    x = bounds_right - total_width
    y = bounds_y

    for symbol in symbols:
        symbol_img = load_mana_symbol(symbol, symbol_size)
        if symbol_img:
            card.paste(symbol_img, (x, y), symbol_img)
        x += symbol_size + spacing


class TextToken:
    """Represents a token in parsed text (either text or mana symbol)."""
    def __init__(self, token_type: str, value: str):
        self.type = token_type  # 'text' or 'mana'
        self.value = value


def parse_text_with_mana(text: str) -> List[TextToken]:
    """
    Parse text containing mana symbols into tokens.
    Example: "{T}: Add {G}" -> [mana(T), text(": Add "), mana(G)]
    """
    tokens = []
    pattern = r'(\{[^}]+\})'
    parts = re.split(pattern, text)

    for part in parts:
        if not part:
            continue
        if part.startswith('{') and part.endswith('}'):
            # Mana symbol
            symbol = part[1:-1]  # Remove braces
            tokens.append(TextToken('mana', symbol))
        else:
            tokens.append(TextToken('text', part))

    return tokens


def measure_tokens(
    tokens: List[TextToken],
    font: ImageFont.FreeTypeFont,
    mana_size: int,
    draw: ImageDraw.ImageDraw
) -> int:
    """Measure the total width of a list of tokens."""
    total_width = 0
    for token in tokens:
        if token.type == 'text':
            width, _ = get_text_size(draw, token.value, font)
            total_width += width
        else:
            # Mana symbol width
            total_width += mana_size + int(mana_size * 0.1)  # Symbol + spacing
    return total_width


def wrap_tokens(
    tokens: List[TextToken],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    mana_size: int,
    draw: ImageDraw.ImageDraw
) -> List[List[TextToken]]:
    """
    Wrap tokens into lines that fit within max_width.
    Returns a list of token lists (one per line).
    """
    lines = []
    current_line = []
    current_width = 0

    for token in tokens:
        if token.type == 'text':
            # Split text by spaces for word wrapping
            words = token.value.split(' ')
            for i, word in enumerate(words):
                # Add space before word if not first word in line
                if i > 0 or (current_line and current_line[-1].type != 'mana'):
                    word_with_space = ' ' + word if current_line else word
                else:
                    word_with_space = word

                if not word_with_space.strip():
                    continue

                word_width, _ = get_text_size(draw, word_with_space, font)

                if current_width + word_width <= max_width or not current_line:
                    current_line.append(TextToken('text', word_with_space))
                    current_width += word_width
                else:
                    # Start new line
                    if current_line:
                        lines.append(current_line)
                    current_line = [TextToken('text', word.lstrip())]
                    current_width, _ = get_text_size(draw, word.lstrip(), font)
        else:
            # Mana symbol
            symbol_width = mana_size + int(mana_size * 0.1)
            if current_width + symbol_width <= max_width or not current_line:
                current_line.append(token)
                current_width += symbol_width
            else:
                # Start new line
                if current_line:
                    lines.append(current_line)
                current_line = [token]
                current_width = symbol_width

    if current_line:
        lines.append(current_line)

    return lines


def draw_token_line(
    card: Image.Image,
    tokens: List[TextToken],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    mana_size: int,
    color: str,
    draw: ImageDraw.ImageDraw
) -> None:
    """Draw a line of tokens (text and mana symbols) at the given position."""
    current_x = x
    font_ascent = font.getbbox('A')[3]  # Get font height for baseline

    for token in tokens:
        if token.type == 'text':
            draw.text((current_x, y), token.value, font=font, fill=color)
            width, _ = get_text_size(draw, token.value, font)
            current_x += width
        else:
            # Mana symbol - vertically center with text
            symbol_img = load_mana_symbol(token.value, mana_size)
            if symbol_img:
                # Center symbol vertically with text
                symbol_y = y + (font_ascent - mana_size) // 2
                card.paste(symbol_img, (current_x, symbol_y), symbol_img)
            current_x += mana_size + int(mana_size * 0.1)


def load_flavor_divider(width: int) -> Optional[Image.Image]:
    """Load and scale the flavor text divider bar."""
    bar_path = os.path.join(MANA_DIR, 'bar.png')
    if os.path.exists(bar_path):
        try:
            bar = Image.open(bar_path).convert('RGBA')
            # Scale to desired width while maintaining aspect ratio
            aspect = bar.width / bar.height
            new_height = int(width / aspect)
            if new_height < 4:
                new_height = 4
            return bar.resize((width, new_height), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"Warning: Could not load flavor divider: {e}")
    return None


def draw_rules_text(
    card: Image.Image,
    oracle_text: str,
    flavor_text: Optional[str],
    bounds: Dict[str, float]
) -> None:
    """
    Draw rules text (oracle text and flavor text) on the card.
    Handles mana symbols inline and auto-sizes text to fit.

    Uses Card Conjurer's text justification approach:
    - Lines are left-aligned within the text block
    - The entire text block is centered horizontally based on the widest line

    Args:
        card: The card image to draw on
        oracle_text: The oracle/rules text
        flavor_text: Optional flavor text
        bounds: Text bounds dictionary
    """
    if not oracle_text and not flavor_text:
        return

    draw = ImageDraw.Draw(card)

    # Calculate bounds in pixels
    bounds_x = int(bounds['x'] * CARD_WIDTH)
    bounds_y = int(bounds['y'] * CARD_HEIGHT)
    bounds_width = int(bounds['width'] * CARD_WIDTH)
    bounds_height = int(bounds['height'] * CARD_HEIGHT)

    # Start with the configured size and shrink if needed
    base_size = int(bounds['size'] * CARD_HEIGHT)
    font_size = base_size
    min_size = int(base_size * 0.5)  # Don't shrink below 50%

    # Get fonts
    regular_font_name = 'mplantin'
    italic_font_name = 'mplantini'

    # Parse oracle text - split by paragraphs (ability breaks)
    paragraphs = oracle_text.split('\n') if oracle_text else []

    # Load divider bar for flavor text
    divider_width = int(bounds_width * 0.3)
    divider = load_flavor_divider(divider_width) if flavor_text else None
    divider_height = divider.height if divider else 8

    # Auto-size: shrink font until text fits
    while font_size >= min_size:
        regular_font = load_font(regular_font_name, font_size)
        italic_font = load_font(italic_font_name, font_size)
        mana_size = int(font_size * 0.85)

        line_height = int(font_size * 1.2)
        total_height = 0
        all_lines = []  # List of (type, tokens_list or special, line_width)

        # Process oracle text paragraphs
        for para_idx, para in enumerate(paragraphs):
            if para.strip():
                tokens = parse_text_with_mana(para)
                wrapped_lines = wrap_tokens(tokens, regular_font, bounds_width, mana_size, draw)
                for line_tokens in wrapped_lines:
                    # Calculate line width
                    line_width = 0
                    for token in line_tokens:
                        if token.type == 'text':
                            w, _ = get_text_size(draw, token.value, regular_font)
                            line_width += w
                        else:
                            line_width += mana_size + int(mana_size * 0.1)
                    all_lines.append(('regular', line_tokens, line_width))
                    total_height += line_height
                if para_idx < len(paragraphs) - 1:
                    total_height += int(line_height * 0.3)  # Paragraph spacing

        # Process flavor text with divider
        if flavor_text:
            total_height += int(line_height * 0.3)  # Spacing before divider
            all_lines.append(('divider', None, 0))
            total_height += divider_height + int(line_height * 0.3)  # Divider + spacing after

            # Flavor text - wrap normally (no mana symbols)
            lines = []
            words = flavor_text.split()
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word])
                width, _ = get_text_size(draw, test_line, italic_font)
                if width <= bounds_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))

            for line in lines:
                line_width, _ = get_text_size(draw, line, italic_font)
                all_lines.append(('italic', [TextToken('text', line)], line_width))
                total_height += line_height

        if total_height <= bounds_height:
            break

        font_size -= 2

    # Vertical centering
    y_offset = bounds_y + (bounds_height - total_height) // 2

    # Now render the text
    regular_font = load_font(regular_font_name, font_size)
    italic_font = load_font(italic_font_name, font_size)
    mana_size = int(font_size * 0.85)
    line_height = int(font_size * 1.2)
    text_color = bounds.get('color', 'black')

    y = y_offset

    for idx, (line_type, line_data, line_width) in enumerate(all_lines):
        if line_type == 'divider':
            # Draw flavor divider - always centered
            if divider:
                divider_x = bounds_x + (bounds_width - divider_width) // 2
                card.paste(divider, (divider_x, y), divider)
            y += divider_height + int(line_height * 0.3)
            continue

        font = italic_font if line_type == 'italic' else regular_font
        line_tokens = line_data

        # Rules text (regular) is LEFT-aligned, flavor text (italic) is CENTER-aligned per line
        if line_type == 'italic':
            # Center flavor text lines individually
            x = bounds_x + (bounds_width - line_width) // 2
        else:
            # Left-align rules text
            x = bounds_x

        # Draw the line with inline mana symbols
        draw_token_line(card, line_tokens, x, y, font, mana_size, text_color, draw)

        y += line_height


def draw_text_element(
    card: Image.Image,
    text: str,
    bounds: Dict[str, float],
    font_override: str = None
) -> None:
    """
    Draw a text element (title, type line, P/T) on the card.

    Args:
        card: The card image to draw on
        text: The text to render
        bounds: Text bounds dictionary with position and style info
        font_override: Optional font name override
    """
    if not text:
        return

    draw = ImageDraw.Draw(card)

    # Calculate bounds in pixels
    bounds_x = int(bounds['x'] * CARD_WIDTH)
    bounds_y = int(bounds['y'] * CARD_HEIGHT)
    bounds_width = int(bounds['width'] * CARD_WIDTH)
    bounds_height = int(bounds['height'] * CARD_HEIGHT)

    # Get font settings
    font_name = font_override or bounds.get('font', 'mplantin')
    font_size = int(bounds['size'] * CARD_HEIGHT)
    color = bounds.get('color', 'black')

    # Shadow settings
    shadow_x = int(bounds.get('shadow_x', 0) * CARD_WIDTH)
    shadow_y = int(bounds.get('shadow_y', 0) * CARD_HEIGHT)

    # Load font
    font = load_font(font_name, font_size)

    # Auto-shrink if text is too wide (for one_line elements)
    if bounds.get('one_line', False):
        while font_size > 10:
            text_width, text_height = get_text_size(draw, text, font)
            if text_width <= bounds_width:
                break
            font_size -= 2
            font = load_font(font_name, font_size)
        text_width, text_height = get_text_size(draw, text, font)
    else:
        text_width, text_height = get_text_size(draw, text, font)

    # Calculate position based on alignment
    align = bounds.get('align', 'left')
    if align == 'right':
        x = bounds_x + bounds_width - text_width
    elif align == 'center':
        x = bounds_x + (bounds_width - text_width) // 2
    else:  # left
        x = bounds_x

    # Vertical centering within bounds
    y = bounds_y + (bounds_height - text_height) // 2

    # Draw with shadow
    draw_text_with_shadow(
        draw, text, (x, y), font,
        color=color,
        shadow_color='black',
        shadow_offset=(shadow_x, shadow_y)
    )


def get_border_path(border_type: str = 'black') -> str:
    """Get the full path to a border image."""
    filename = BORDER_FILES.get(border_type, 'borderBlack.png')
    return os.path.join(FRAME_DIR, filename)


def create_card(
    frame_path: str,
    art_path: str,
    output_path: str,
    card_data: Dict[str, Any],
    artist: str = "Unknown",
    border_color: str = "black"
) -> bool:
    """
    Create a card by compositing art with a frame and adding text.

    Args:
        frame_path: Path to the frame image
        art_path: Path to the art image
        output_path: Path for the output image
        card_data: Card data from Scryfall API
        artist: Artist name for credit
        border_color: Border color ('black' or 'white')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Load images
        frame = load_image(frame_path)
        art = load_image(art_path)

        # Load border
        border_path = get_border_path(border_color)
        border = None
        if os.path.exists(border_path):
            border = load_image(border_path)
            if border.size != (CARD_WIDTH, CARD_HEIGHT):
                border = border.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)

        # Resize frame to standard card dimensions if needed
        if frame.size != (CARD_WIDTH, CARD_HEIGHT):
            frame = frame.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)

        # Calculate art placement
        x, y, width, height = calculate_art_placement(art)
        print(f"Art placement: x={x}, y={y}, width={width}, height={height}")

        # Resize art to fit
        art_resized = art.resize((width, height), Image.Resampling.LANCZOS)

        # Create a new canvas
        card = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))

        # Paste art first (it goes behind the frame)
        # Handle negative coordinates by cropping the art
        paste_x = max(0, x)
        paste_y = max(0, y)

        # If art extends beyond canvas edges, we need to crop it
        if x < 0 or y < 0:
            crop_left = -min(0, x)
            crop_top = -min(0, y)
            crop_right = min(width, CARD_WIDTH - x)
            crop_bottom = min(height, CARD_HEIGHT - y)
            art_resized = art_resized.crop((crop_left, crop_top, crop_right, crop_bottom))

        card.paste(art_resized, (paste_x, paste_y))

        # Paste frame on top (frame has transparency for art area)
        card = Image.alpha_composite(card, frame)

        # Paste border on top of everything
        if border:
            card = Image.alpha_composite(card, border)

        # Draw text elements
        card_name = card_data.get('name', '')
        mana_cost = card_data.get('mana_cost', '')
        type_line = card_data.get('type_line', '')
        oracle_text = card_data.get('oracle_text', '')
        flavor_text = card_data.get('flavor_text', '')
        power = card_data.get('power', '')
        toughness = card_data.get('toughness', '')

        # Draw title
        print(f"Drawing title: {card_name}")
        draw_text_element(card, card_name, TEXT_BOUNDS['title'])

        # Draw mana cost
        if mana_cost:
            print(f"Drawing mana cost: {mana_cost}")
            draw_mana_cost(card, mana_cost, TEXT_BOUNDS['mana'])

        # Draw type line
        print(f"Drawing type line: {type_line}")
        draw_text_element(card, type_line, TEXT_BOUNDS['type'])

        # Draw rules text
        if oracle_text or flavor_text:
            print(f"Drawing rules text ({len(oracle_text or '')} chars)")
            draw_rules_text(card, oracle_text, flavor_text, TEXT_BOUNDS['rules'])

        # Draw power/toughness for creatures
        if power and toughness:
            pt_text = f"{power}/{toughness}"
            print(f"Drawing P/T: {pt_text}")
            draw_text_element(card, pt_text, TEXT_BOUNDS['pt'])

        # Draw artist credit
        artist_text = f"Illus. {artist}"
        draw_text_element(card, artist_text, TEXT_BOUNDS['artist'])

        # Draw copyright
        import datetime
        year = datetime.datetime.now().year
        copyright_text = f"™ & © {year} Wizards of the Coast, Inc."
        draw_text_element(card, copyright_text, TEXT_BOUNDS['copyright'])

        # Save the result
        card.save(output_path, 'PNG')
        print(f"Card saved to: {output_path}")
        return True

    except Exception as e:
        print(f"Error creating card: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Create MTG cards using Scryfall API and Fourth Edition frames',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s "Island" my_island_art.png
    %(prog)s "Lightning Bolt" bolt_art.png bolt_card.png
    %(prog)s "Sol Ring" --frame-type A ring_art.png
        """
    )

    parser.add_argument('card_name', help='Name of the card to look up on Scryfall')
    parser.add_argument('art_path', help='Path to the art PNG file')
    parser.add_argument('output_path', nargs='?', default=None,
                        help='Output path for the card image (default: <card_name>_card.png)')
    parser.add_argument('--frame-type', '-f', choices=['W', 'U', 'B', 'R', 'G', 'M', 'A', 'L'],
                        help='Override frame type (W=White, U=Blue, B=Black, R=Red, G=Green, M=Multi, A=Artifact, L=Land)')
    parser.add_argument('--show-card-info', '-i', action='store_true',
                        help='Display card information from Scryfall')
    parser.add_argument('--offline', '-o', action='store_true',
                        help='Offline mode: skip Scryfall API, requires --frame-type')
    parser.add_argument('--artist', '-a', default='Unknown',
                        help='Artist name for credit (default: Unknown)')
    parser.add_argument('--border', '-b', choices=['black', 'white'], default='black',
                        help='Border color (default: black)')

    args = parser.parse_args()

    # Validate art path
    if not os.path.exists(args.art_path):
        print(f"Error: Art file not found: {args.art_path}")
        sys.exit(1)

    # Offline mode validation
    if args.offline:
        if not args.frame_type:
            print("Error: --offline mode requires --frame-type to be specified")
            sys.exit(1)
        print("Running in offline mode (skipping Scryfall API)")
        card_data = {'name': args.card_name}
        frame_type = args.frame_type
    else:
        # Fetch card data from Scryfall
        print(f"Fetching card data for '{args.card_name}' from Scryfall...")
        card_data = fetch_card_data(args.card_name)

        if not card_data:
            print("\nTip: Use --offline -f <FRAME_TYPE> to skip the API")
            print("Frame types: W=White, U=Blue, B=Black, R=Red, G=Green, M=Multi, A=Artifact, L=Land")
            sys.exit(1)

        # Display card info if requested
        if args.show_card_info:
            print("\n--- Card Information ---")
            print(f"Name: {card_data.get('name', 'Unknown')}")
            print(f"Type: {card_data.get('type_line', 'Unknown')}")
            print(f"Colors: {card_data.get('colors', [])}")
            print(f"Color Identity: {card_data.get('color_identity', [])}")
            print(f"Mana Cost: {card_data.get('mana_cost', 'N/A')}")
            if 'oracle_text' in card_data:
                print(f"Text: {card_data['oracle_text']}")
            if 'flavor_text' in card_data:
                print(f"Flavor: {card_data['flavor_text']}")
            if 'power' in card_data:
                print(f"P/T: {card_data['power']}/{card_data['toughness']}")
            print("------------------------\n")

        # Determine frame type
        if args.frame_type:
            frame_type = args.frame_type
            print(f"Using overridden frame type: {frame_type}")
        else:
            frame_type = determine_frame_type(card_data)

    # Get frame path
    frame_path = get_frame_path(frame_type)
    if not os.path.exists(frame_path):
        print(f"Error: Frame file not found: {frame_path}")
        sys.exit(1)

    print(f"Using frame: {frame_path}")

    # Determine output path
    if args.output_path:
        output_path = args.output_path
    else:
        card_name_safe = card_data.get('name', 'card').replace(' ', '_').replace('/', '_')
        output_path = f"{card_name_safe}_card.png"

    # Create the card
    print(f"Creating card with art from '{args.art_path}'...")
    success = create_card(
        frame_path,
        args.art_path,
        output_path,
        card_data,
        artist=args.artist,
        border_color=args.border
    )

    if success:
        print(f"\nSuccess! Card created: {output_path}")
        print(f"Card: {card_data.get('name', 'Unknown')} ({frame_type} frame)")
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
