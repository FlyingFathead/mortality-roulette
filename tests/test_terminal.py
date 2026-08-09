from __future__ import annotations

import unittest

from mortality_roulette_core.terminal import (
    terminal_display_width,
    terminal_emphasis,
    terminal_pad,
    terminal_rule,
    terminal_truncate,
    terminal_wrap,
)


class TerminalFormattingTests(unittest.TestCase):
    def test_ascii_and_wide_character_width(self) -> None:
        self.assertEqual(terminal_display_width("abc"), 3)
        self.assertEqual(terminal_display_width("死亡"), 4)

    def test_rule_width(self) -> None:
        self.assertEqual(terminal_rule(7), "─" * 7)

    def test_padding_uses_display_cells(self) -> None:
        self.assertEqual(terminal_pad("死亡", 6), "死亡  ")

    def test_truncate_preserves_requested_width(self) -> None:
        value = terminal_truncate("abcdefghijkl", 6)
        self.assertEqual(value, "abcde…")
        self.assertEqual(terminal_display_width(value), 6)


    def test_bold_bright_white_emphasis_on_tty(self) -> None:
        class FakeTTY:
            def isatty(self) -> bool:
                return True

        styled = terminal_emphasis(
            "CANADA",
            bold=True,
            bright_white=True,
            stream=FakeTTY(),
            environ={"TERM": "xterm-256color"},
        )
        self.assertEqual(styled, "\x1b[1;97mCANADA\x1b[0m")

    def test_wrap_long_token_does_not_drop_characters(self) -> None:
        wrapped = terminal_wrap("abcdefghij", 4)
        self.assertEqual("".join(wrapped), "abcdefghij")
        self.assertTrue(all(terminal_display_width(line) <= 4 for line in wrapped))


if __name__ == "__main__":
    unittest.main()
