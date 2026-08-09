"""Terminal presentation primitives used by Mortality Roulette.

This is intentionally dependency-free: display-cell handling is approximate
but stable, and keeps the main simulation module free of low-level rendering
helpers.
"""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from typing import Mapping, TextIO


def terminal_display_width(text: str) -> int:
    """Approximate terminal cell width without adding a wcwidth dependency."""
    width = 0
    for char in text:
        if unicodedata.combining(char) or char in {"\ufe0e", "\ufe0f", "\u200d"}:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def terminal_pad(text: str, width: int) -> str:
    """Pad a UTF-8 terminal string to an exact display-cell width."""
    return text + " " * max(0, int(width) - terminal_display_width(text))


def terminal_truncate(text: str, width: int) -> str:
    """Truncate to terminal-cell width, using an ellipsis when needed."""
    width = max(0, int(width))
    if terminal_display_width(text) <= width:
        return text
    if width <= 0:
        return ""
    if width == 1:
        return "…"
    target = width - 1
    out: list[str] = []
    used = 0
    for char in text:
        char_width = terminal_display_width(char)
        if used + char_width > target:
            break
        out.append(char)
        used += char_width
    return "".join(out) + "…"


def terminal_wrap(text: str, width: int) -> list[str]:
    """Word-wrap text to a terminal-cell width without external dependencies."""
    width = max(1, int(width))
    words = str(text).split() or [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if terminal_display_width(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while terminal_display_width(word) > width:
            chunk = terminal_truncate(word, width)
            if chunk.endswith("…"):
                raw_target = max(1, width)
                raw: list[str] = []
                used = 0
                for char in word:
                    char_width = terminal_display_width(char)
                    if used + char_width > raw_target:
                        break
                    raw.append(char)
                    used += char_width
                piece = "".join(raw)
                if not piece:
                    piece = word[0]
                lines.append(piece)
                word = word[len(piece):]
            else:
                break
        current = word
    if current or not lines:
        lines.append(current)
    return lines


def terminal_rule(width: int | None = None) -> str:
    """Return the canonical solid rule, defaulting to current terminal width."""
    if width is None:
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
    return "─" * max(1, int(width))


def terminal_emphasis(
    text: str,
    *,
    bold: bool = False,
    blink: bool = False,
    bright_white: bool = False,
    stream: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Apply ANSI emphasis only when the selected output stream is interactive."""
    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    if not getattr(stream, "isatty", lambda: False)():
        return text
    if "NO_COLOR" in environ or environ.get("TERM") == "dumb":
        return text
    codes: list[str] = []
    if bold:
        codes.append("1")
    if blink:
        codes.append("5")
    if bright_white:
        codes.append("97")
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"
