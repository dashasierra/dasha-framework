"""``dasha --key-test``: show the name of each key as it is pressed.

Over SSH, or in some terminals, keys such as Alt and a letter, or F10,
may never reach Dasha Framework, or may arrive as something else. This screen
shows exactly what arrives, using the same names as a shortcuts file, so
that users can choose keys that work for them. Press Ctrl+C, which every
terminal can send, to end it.
"""

from dasha.canvas import Canvas
from dasha.events import (
    Event,
    InputDecoder,
    KeyReleaseEvent,
    MouseEvent,
    PasteEvent,
    read_events,
)
from dasha.shortcuts import pretty_key
from dasha.statusbar import StatusBar
from dasha.terminal import Terminal

QUIT_KEY = "ctrl+c"
_ESCAPE_TIMEOUT = 0.05
_PASTE_PREVIEW = 40  # characters of a paste shown
_HEADER = (
    "Dasha Framework key test: press keys (or click, scroll, paste) to see the",
    "names it receives. Use these names in shortcuts.json. Press Ctrl+C to finish.",
)


def describe(event: Event) -> str:
    """One line describing an input event."""
    if isinstance(event, KeyReleaseEvent):
        return f"release  {'space' if event.key == ' ' else event.key}"
    if isinstance(event, PasteEvent):
        # repr shows line breaks and other control characters as escapes.
        preview = repr(event.text[:_PASTE_PREVIEW])
        more = "..." if len(event.text) > _PASTE_PREVIEW else ""
        count = len(event.text)
        return f"paste  {count} character{'' if count == 1 else 's'}: {preview}{more}"
    if isinstance(event, MouseEvent):
        modifiers = "".join(
            f"{name}+"
            for name, held in (
                ("shift", event.shift),
                ("alt", event.alt),
                ("ctrl", event.ctrl),
            )
            if held
        )
        return (
            f"mouse  {modifiers}{event.button} {event.action}"
            f" at row {event.row}, column {event.column}"
        )
    if event.startswith("unknown("):
        return f"{event}  (not recognised: this key cannot be used)"
    return f'"{event}"  ({pretty_key(event)})'


def run(terminal: Terminal) -> None:
    """Show the names of keys as they are pressed, until Ctrl+C is
    pressed."""
    decoder = InputDecoder()
    seen: list[str] = []
    on_screen: Canvas | None = None
    while True:
        columns, lines = terminal.size()
        if terminal.take_cleared():
            on_screen = None  # draw every cell again
        canvas = Canvas(columns, lines)
        for row, text in enumerate(_HEADER):
            # In the status bar's colours, so it follows the theme.
            canvas.write(row, 0, text.ljust(columns), StatusBar.style)
        room = max(0, lines - len(_HEADER) - 1)
        for offset, line in enumerate(seen[-room:] if room else []):
            canvas.write(len(_HEADER) + 1 + offset, 2, line)
        terminal.write(canvas.render(on_screen))
        terminal.flush()
        on_screen = canvas
        for event in read_events(terminal, decoder, _ESCAPE_TIMEOUT):
            if event == QUIT_KEY:
                return
            if isinstance(event, MouseEvent) and event.action == "move":
                continue  # plain pointer movement would flood the list
            seen.append(describe(event))
