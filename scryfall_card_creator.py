#!/usr/bin/env python3
"""
Scryfall Card Creator for Card Conjurer

This script uses the Scryfall API to fetch card information and creates
Magic: The Gathering cards using Fourth Edition frames with custom art.

Usage:
    python scryfall_card_creator.py "Card Name" path/to/art.png [output.png]

Example:
    python scryfall_card_creator.py "Island" my_island_art.png island_card.png
"""

import argparse
import sys
import os
import requests
from PIL import Image
from io import BytesIO
from typing import Optional, Tuple, Dict, Any

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

# Frame directory path (relative to this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRAME_DIR = os.path.join(SCRIPT_DIR, 'img', 'frames', 'old', 'fourth')

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


def create_card(frame_path: str, art_path: str, output_path: str) -> bool:
    """
    Create a card by compositing art with a frame.

    Args:
        frame_path: Path to the frame image
        art_path: Path to the art image
        output_path: Path for the output image

    Returns:
        True if successful, False otherwise
    """
    try:
        # Load images
        frame = load_image(frame_path)
        art = load_image(art_path)

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

        # Save the result
        card.save(output_path, 'PNG')
        print(f"Card saved to: {output_path}")
        return True

    except Exception as e:
        print(f"Error creating card: {e}")
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
        print(f"Running in offline mode (skipping Scryfall API)")
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
    success = create_card(frame_path, args.art_path, output_path)

    if success:
        print(f"\nSuccess! Card created: {output_path}")
        print(f"Card: {card_data.get('name', 'Unknown')} ({frame_type} frame)")
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
