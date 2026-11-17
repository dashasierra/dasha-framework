"""The ANSI/VT escape sequences used to control the terminal."""

ESC = "\x1b"
CSI = ESC + "["

ENTER_ALT_SCREEN = CSI + "?1049h"
LEAVE_ALT_SCREEN = CSI + "?1049l"
HIDE_CURSOR = CSI + "?25l"
SHOW_CURSOR = CSI + "?25h"

# The terminal's own scroll bar (private mode 30, from rxvt; xterm and urxvt
# support it too). Dasha Framework saves the current setting (XTSAVE, "s"), hides the
# bar, and on exit restores whatever was there before (XTRESTORE, "r"), so a
# terminal that had no scroll bar does not gain one. Terminals without mode
# 30 ignore all three.
HIDE_SCROLLBAR = CSI + "?30s" + CSI + "?30l"
RESTORE_SCROLLBAR = CSI + "?30r"
CLEAR_SCREEN = CSI + "2J"
RESET_ATTRIBUTES = CSI + "0m"
BOLD = CSI + "1m"

# Mouse reporting: button presses and releases (1000), movement while a button
# is held (1002), any movement at all (1003, for hovering), reported in the
# SGR format (1006), which has no size limit and tells presses from releases.
# The terminal, not the remote computer, generates these reports, so they
# work over SSH too.
ENABLE_MOUSE = CSI + "?1000h" + CSI + "?1002h" + CSI + "?1003h" + CSI + "?1006h"
DISABLE_MOUSE = CSI + "?1006l" + CSI + "?1003l" + CSI + "?1002l" + CSI + "?1000l"

# Bracketed paste (2004): the terminal wraps text pasted into it (its own
# Ctrl+V, right-click or middle-click) in ESC[200~ ... ESC[201~, so Dasha Framework can
# tell a paste from typing. Like mouse reports, this works over SSH.
ENABLE_BRACKETED_PASTE = CSI + "?2004h"
DISABLE_BRACKETED_PASTE = CSI + "?2004l"


SPACE_RELEASED = CSI + "32;1:3u"
"""What the Windows backend puts in the input when Space is released. This
is how the kitty keyboard protocol writes a release (code 32, no modifiers,
event 3), and ``dasha.events`` decodes it as ``KeyReleaseEvent(" ")``."""


def move_to(row: int, column: int) -> str:
    """Return the sequence that moves the cursor to a row and column, both
    counted from 0."""
    return f"{CSI}{row + 1};{column + 1}H"
