# Architecture

## Guiding constraints

- **Standard library only.** No runtime dependencies. Platform-specific
  terminal access goes through `ctypes` (Windows console API) and the POSIX
  modules (`termios`, `tty`, `fcntl`, `signal`, `select`).
- **Local and remote.** Dasha Framework must work correctly both in a local
  terminal and in a terminal connected over SSH, where only the stream of
  bytes (VT/ANSI escape sequences) is available.

## Terminal layer (`dasha.terminal`)

`Terminal` is a context manager that runs a full-screen session:

1. The platform backend prepares the console (`enable`).
2. Dasha Framework switches to the **alternate screen** (`ESC[?1049h`) and hides
   the cursor, so that the screen the user started from is preserved.
3. It hides the terminal's scroll bar where it can (see
   [Scroll bars](#scroll-bars) below).
4. It turns on bracketed paste (`ESC[?2004h`; see
   [Pasting through the terminal](#pasting-through-the-terminal) below).
5. It turns on mouse reporting (`ESC[?1000h`, `ESC[?1002h`, `ESC[?1003h`,
   `ESC[?1006h`; see [Mouse](#mouse) below). Pass `Terminal(mouse=False)` to
   leave it off.
6. On exit, even after an exception, it turns mouse reporting and bracketed
   paste off (`ESC[?2004l`), shows the cursor, leaves the alternate screen
   (`ESC[?1049l`), restores the scroll bar and restores the original console
   modes.

`Terminal.suspended()` does step 6 and then, once it is let go, steps 1 to 5
again, onto a cleared alternate screen. The desktop uses it for the command
prompt.

### The command prompt (`dasha.shell`)

Command prompt in the system menu, or Alt+F12 (the `command_prompt`
shortcut), lets the user run commands without shutting Dasha Framework down.
`PresentationManager.command_prompt` does the following:

1. It gives the terminal back (`Terminal.suspended`), so the user's own
   screen returns. Dasha Framework does not need to save that screen: leaving the
   alternate screen brings it back, and on the classic Windows console
   `ScrollBarHider` already saves and restores the buffer.
2. It runs the user's shell there in the foreground (`shell.run_shell`).
   The shell is `%COMSPEC%` (or `cmd.exe`) on Windows, and `$SHELL` (or
   `/bin/sh`) elsewhere.
3. When the user types `exit`, it takes the terminal again and draws every
   cell afresh.

Applications carry on in their own processes the whole time, and their
messages wait in the inbox.

**Redrawing everything.** Dasha Framework never relies on the terminal to have kept
its screen. A program run at the prompt (vim, less or top, say) may use the
alternate screen too, and draw over it. The desktop already holds everything
it draws:
- its own windows;
- each hosted application's last painted rows, which its `RemoteWindow`
  keeps;
- the last frame drawn, `_on_screen`.

So afterwards it forgets that frame. The next frame is then written cell by
cell onto the cleared screen, at the terminal's size at that moment, in case
it was resized meanwhile. It also forgets where the mouse was, so the shown
mouse is not drawn where it used to be. Nothing is written to disk.

**Signals.** Keys such as Ctrl+C, Ctrl+\ and Ctrl+Z typed at the shell are
signals sent to the whole foreground process group, which includes the
desktop. On Windows, Ctrl+C and Ctrl+Break go to every process attached to
the console. While the shell runs, the desktop catches SIGINT, SIGQUIT,
SIGTSTP and SIGBREAK, whichever exist, and does nothing with them.

They are caught rather than ignored (`SIG_IGN`) because a child inherits an
ignored signal across `exec`. Ctrl+C would then be dead in the shell and in
everything it runs. A caught signal goes back to its default in a child.

**Job control.** A shell with job control, such as bash, makes its own
process group the terminal's foreground group. When it exits, it hands the
terminal back. If it did not, the desktop takes the terminal back itself
(`os.tcsetpgrp`, with SIGTTOU ignored meanwhile). Otherwise the desktop would
be stopped as soon as it set the terminal up again.

**Not inside itself.** The shell's environment has `DASHA_SUSPENDED` set,
and `dasha desktop` refuses to start a desktop where it is. It says that one is
already running and that typing `exit` returns to it. The key test, and
applications run on their own, still start.

`GuardedTerminal` turns a failure to give the terminal back or take it again
into `TerminalFailed`. A failure in between, such as a shell that cannot be
started, is not the terminal's, so the user is told in a dialog instead.

### Pseudo-terminals (`dasha.pseudoterminal`) and the VT emulator (`dasha.vt`)

The command prompt hands the whole screen over. To run a program inside a
window instead, it runs in a pseudo-terminal, so that it sees a terminal of
its own (with prompts, line editing, colours and Ctrl+C), and what it writes
is read back and interpreted.

- **`dasha.pseudoterminal`.** `open_pty()` gives a `PseudoTerminal` for
  the system it runs on. On Linux and macOS (`_posix.py`) it is
  `os.forkpty`, with the child execing the program at once, `TERM` set to
  `xterm-256color` and the size set with `termios.tcsetwinsize`. On
  Windows (`_windows.py`) it is a pseudoconsole (ConPTY, Windows 10
  version 1809 or later), through ctypes: `CreatePseudoConsole`, then
  `CreateProcessW` with the `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`
  attribute. The child is started with `STARTF_USESTDHANDLES` and no
  handles. Without that, a child of a process whose own standard handles
  are redirected, as a hosted application's are, writes to those rather
  than to the pseudoconsole. The common part (`base.py`) reads the
  program's output on one thread (`on_output`) and writes its input on
  another, so that writing never holds up the desktop. When the program
  ends, `on_exit` follows its last output. On Windows a waiting thread
  closes the pseudoconsole once the program ends, which is what ends its
  output.
- **`dasha.vt`.** A `Screen` is fed what the program writes, as text or
  as UTF-8 in any pieces, and keeps what an xterm would show: a grid of
  cells, each a character and a `Style` (16, 256 and 24-bit colours), the
  cursor, scroll regions, wrapping, the alternate screen, the scrollback,
  the title, and the DEC modes for the cursor, application cursor keys and
  bracketed paste. Anything else is read and dropped, never shown. A wide
  character takes two cells and is drawn as `?`, as everywhere else.
  `encode_key` goes the other way, from a key name to the bytes a terminal
  sends for it, and `encode_mouse` from a `MouseEvent` to a mouse report, in
  the SGR form (mode 1006) or the original one, for the modes the program
  turned on (1000, 1002, 1003).

### Scroll bars

A terminal's scroll bar belongs to the terminal program, not to Dasha Framework,
so whether Dasha Framework can hide it depends on the terminal:

- **Classic Windows console** (cmd.exe or PowerShell in conhost). Scroll
  bars appear when the screen buffer is larger than the window, and the
  normal buffer is usually much taller (often 9,001 lines). The alternate
  screen alone does not remove them: the window keeps showing the normal
  buffer's scroll bar. So the Windows backend (`_winbuffer.ScrollBarHider`)
  shrinks the screen buffer to exactly the window's size
  (`SetConsoleScreenBufferSize`), and puts the original size back on exit.
  A buffer can never be smaller than its window, so if the window has grown
  meanwhile (and is still maximised), the buffer is put back at least as
  large as the window.

  The console grows that buffer when the window grows (maximising it, or
  going full screen with Alt+Enter), but does not shrink it when the window
  is restored. The larger buffer then needs scroll bars, which take lines
  and columns from the window, and the alternate screen is left at the
  larger size, scrolled to its bottom. While the alternate screen shows,
  the console API acts on it rather than on the normal buffer, and
  shrinking it does not help: the console goes on drawing as though it
  were still scrolled, so every line lands in the wrong place. So when a
  resize leaves the screen larger than its window, `Terminal` leaves the
  alternate screen, has the backend shrink the normal buffer to the window
  again, and enters the alternate screen afresh, which the console makes
  the window's size. That clears the screen, so the desktop draws every
  cell again (`Terminal.take_cleared()`).

  Shrinking the buffer on its own would destroy the user's history. In a
  test with lines 1–80 in a 300-line buffer, shrinking it and growing it
  again kept only the 29 lines that were on screen, moved to the top, and
  lost lines 1–51 for good. So before shrinking the buffer, Dasha Framework
  copies the rows in use, with their characters and colours
  (`ReadConsoleOutputW`, in chunks), along with the cursor and scroll
  position. On exit it writes them all back (`WriteConsoleOutputW`). After
  a Dasha Framework session, the buffer size, scroll position, cursor, text and
  colours were all exactly as before.

  If the buffer already fits the window, nothing is changed. That is always
  so in Windows Terminal and in SSH sessions into Windows, which give
  programs a buffer the size of the window. Hiding the scroll bars is
  purely cosmetic, so if any step fails, Dasha Framework carries on with them
  showing.
- **xterm, rxvt and urxvt.** Dasha Framework saves the scroll bar setting
  (`ESC[?30s`), hides the bar (`ESC[?30l`) and on exit restores what was
  there (`ESC[?30r`). A terminal that had no scroll bar does not gain one.
  Terminals without this mode, including the classic Windows console,
  ignore all three sequences without printing any stray characters.
- **Windows Terminal, GNOME Terminal, Konsole, macOS Terminal, iTerm2.** The
  scroll bar is a user preference that programs cannot change. The
  alternate screen has no scrollback, though, so there is nothing to
  scroll, and macOS's overlay scroll bars hide themselves.
- **Over SSH**, the scroll bar belongs to the user's local terminal, and
  the same rules apply.

All drawing is done with ANSI/VT escape sequences
(`dasha.terminal.ansi`), which work the same way locally and over SSH.
Only the setup differs between platforms:

| Backend | Module | Setup |
| --- | --- | --- |
| Windows | `_windows.py` | `ctypes` calls to `kernel32` `GetConsoleMode`/`SetConsoleMode`: turns on `ENABLE_VIRTUAL_TERMINAL_PROCESSING` for output (the console ignores ANSI codes without it) and `DISABLE_NEWLINE_AUTO_RETURN` (so writing the bottom-right cell does not scroll the screen). For input it turns off line input, echo, Ctrl+C processing and QuickEdit (which would otherwise use the mouse to select text), and turns on `ENABLE_VIRTUAL_TERMINAL_INPUT` so keys arrive as the same escape sequences as on POSIX. It also turns on `ENABLE_WINDOW_INPUT`, so resizes arrive as input records. Input is read with `ReadConsoleInputW`, with `WaitForSingleObject` for timeouts. |
| POSIX | `_posix.py` | `termios`/`tty` raw mode. Input is read straight from the stdin file descriptor, with `select` for timeouts. A `SIGWINCH` handler writes to a pipe that `select` also watches, so a resize wakes the wait. |

The backend is chosen using `sys.platform`, and each module asserts its
platform at the top, so mypy checks each one only for its own platform. To
type-check the other platform's code, run, for example,
`python -m mypy --platform linux`.

If the terminal reports a size of 0x0, as some serial lines and SSH setups
do, `Terminal.size()` falls back to 80x24.

## Colours (`dasha.theme`)

Every colour is a named role (`window.frame`, `menu.selected`,
`button.face` and so on), backed by a class attribute. A theme maps every
role to a `Style`. There are three built-in themes: `default` (blue windows
and grey dialogs), `dark` (light text on black and dark grey) and
`monochrome` (bold, underline and reverse only). A user's
`~/.dasha/colours.json` chooses one of these and overrides any roles it
likes; each file in `~/.dasha/themes/` adds another theme; and
`--monochrome` or `NO_COLOR` selects the monochrome theme.

The theme can be changed while Dasha Framework is running, from the system menu's
Themes or by an application calling `set_theme`.
`PresentationManager.set_theme` installs the theme, redraws the screen, and
sends the theme to each application running in its own process (in a
`theme` message). Widgets read their colours from their class each time
they are drawn, so they pick up a new theme automatically. A window that
keeps its own copy of a style updates it in `theme_changed`. See
[Colours](colours.md) for the roles, the themes and the file format.

## Desktop (`dasha.desktop`)

`Desktop` draws the background that fills the whole screen. By default it
is the traditional text-mode desktop: every cell holds a light shade
character (`░`, code page 437 character 176), drawn in cyan on black
(the `desktop` colours). The source writes it as the Unicode escape
`\u2591`, and any UTF-8 terminal can show it.

Nothing about the desktop is hard-coded. There are three ways to change it,
from simplest to most flexible:

```python
from dasha.desktop import Desktop
from dasha.style import BLUE, Style

# 1. Per instance
Desktop(pattern="\u2592", style=Style(foreground=BLUE))

# 2. For every instance, by subclassing
class DottedDesktop(Desktop):
    pattern = "\u00b7"

# 3. Full control over each cell
class StripedDesktop(Desktop):
    def character_at(self, row: int, column: int) -> str:
        return "\u2592" if row % 2 else "\u2591"
```

`pattern` is repeated across each row, and must contain only characters
that take up a single cell. `style` is a `Style` (colours and attributes)
applied to the whole desktop.

## Composition (`dasha.canvas`, `dasha.style`)

Nothing draws directly on the terminal. Each frame is painted onto a
`Canvas`, an off-screen grid of cells, each holding a character and a
`Style`. Painting goes from back to front, first the desktop and then each
window, so whatever is painted later covers what was painted before. Writes
are clipped to the canvas and, optionally, to a `Rect`, so a window that
hangs off the edge of the screen is simply cut off.

`Canvas.render(previous)` compares the new frame with the one on screen and
outputs only the cells that have changed, using as few cursor moves and
style changes as it can. The first frame, and the first after a resize, are
drawn in full. This keeps redrawing free of flicker, and cheap enough for
SSH.

**Control characters are shown, never sent.** A cell holds whatever
character it was given, whether from a file's text, a file name or an
application's title, but `render` sends each character as `canvas.shown`
translates it. Control characters become their code page 437 pictures
(`CONTROL_GLYPHS`: escape appears as `←`, and bell as `•`), and characters
that cannot occupy exactly one cell (surrogates, wide characters,
zero-width characters and direction overrides) become `?`. So no text on
the screen can carry an escape sequence to the terminal, whichever widget
displays it, and widgets do not need to clean their text for safety. A text
area keeps a file's control characters, for instance, so Notepad saves the
file back exactly as it was, and a text box accepts any text except a line
break. The only other output is Dasha Framework's own fixed sequences (for the
alternate screen, the mouse and bracketed paste), and messages printed by
the command line, which go through `dasha.printing.say` and are made
safe in the same way.

The terminal's cursor stays hidden unless something calls
`Canvas.place_cursor(row, column)` while painting, as a focused text box
does; `render` then finishes by moving the cursor there and showing it. A
cursor outside the current clipping area is not placed, and the
presentation manager hides the cursor while a menu is open, or when it
would land on the menu bar or the status bar.

`Style` holds a foreground colour, a background colour, and the bold,
underline and reverse attributes. Colours 0 to 15 are the standard ANSI
colours (`dasha.style` has named constants for them, such as `BLUE` and
`BRIGHT_WHITE`), and colours 16 to 255 use the 256-colour palette. A
colour can also be an `Rgb`, a 24-bit colour, which is drawn as it is where
the terminal can show it, and as the nearest 256-palette colour where it
cannot. On a terminal with only the 16 standard colours, every colour (RGB
colours and colours 16 to 255) is drawn as the nearest of those, as the CGA
showed them (`style.set_colour_depth`, with `DRAWN_DEPTH` holding the
outcome).
In messages, a style is `[foreground, background, bold, reverse,
underline]`, with each colour a number, `"#rrggbb"` for an `Rgb`, or `null`
for the terminal's own.

## Windows (`dasha.window`)

A `Window` is a framed rectangle with a title centred in its top edge. The
active window has a double frame, and the others a single frame. Its
appearance comes from class attributes (`border`, `inactive_border`,
`frame_style`, `inactive_frame_style` and `body_style`), so a subclass can
restyle it, and setting one on a window restyles only that window. It makes
no difference whether that is before or after `super().__init__()`. In an
application in its own process the desktop draws the frame, so the window
sends it any of these colours that differ from the theme's
(`protocol.WINDOW_STYLES`); the window's borders and shadow stay the desktop's.
To draw something other than lines of text, override `paint_content`.

Each window casts a **drop shadow**: a strip two columns wide down the
right side, starting one row below the top, and a strip one row high along
the bottom, starting two columns in. Together they look square in a typical
terminal font. The shadow keeps the characters beneath it (the desktop, or
other windows) and redraws them dark grey on black (`Canvas.cast_shadow`,
built on `Canvas.restyle`). Open drop-down menus cast the same kind of
shadow, but the menu bar itself casts none. Block characters under a shadow
(`▄ ▀ █ ▌ ▐`, listed in `canvas.SHADOW_BLANKS`) are drawn as spaces
instead, so that a button's shadow does not appear as a bright patch
beneath a window's shadow.

Each window's shadow is painted just before the window itself, so windows
in front cover it, and it falls on everything behind. The status bar and
the menus are painted after all the windows, so shadows never touch them.
The class attributes `shadow_style` (`None` for no shadow), `shadow_width`
and `shadow_height` control the shadow. It is purely decorative: clicks on
it go to whatever lies beneath.

### Resizable windows

Windows are fixed-size unless they are created with `resizable=True` (or
have `resizable` set later):

```python
Window(
    title="Editor",
    rect=Rect(row=2, column=4, height=12, width=40),
    resizable=True,
)
```

- **The grip.** The last two cells of a resizable window's bottom edge are
  its grip, `─┘`, drawn in bright green while the window is active, where
  the double `═╝` of the active frame makes it stand out. The grip uses
  plain single-line box characters (196 and 217), which every code page
  437 font has, and it is two cells wide so that it is easy to see and to
  grab. On an inactive window it takes the frame's colours and blends into
  the single-line `─┘` corner.
- **Resizing.** Pressing on either cell of the grip brings the window to
  the front, and dragging resizes it. The top-left corner stays where it
  is, and the corner stays under the pointer, whichever cell was grabbed.
  Only the front-most window under the pointer can be grabbed.
- **Limits.** A window is never smaller than `min_width` by `min_height`
  (12 by 3). As with moving, resizing can take a window partly off the
  screen or under the status bar. The shadow follows the new size.
- **Settings.** The grip's characters and colour (`resize_grip`,
  `resize_grip_style`) and the minimum size are class attributes.
  `Window.resize(width, height)` resizes a window from code, whether or not
  it is `resizable`; that setting only controls resizing with the mouse.

The constructor's options after `lines` are keyword-only:
`Window(title, rect, lines, menus=..., status=..., resizable=...)`.

### Maximising, minimising and restoring

A window can be made `maximisable=True` and `minimisable=True`; both are
off by default. While such a window is active, buttons appear at the right
of its title bar. The title is centred on the whole top edge, whichever
buttons the window has, so it does not move when the window becomes active
and its buttons appear. It moves aside only if a button would otherwise
cover it.

| Button | Action |
| --- | --- |
| `[↓]` | Minimise |
| `[↑]` | Maximise |
| `[↕]` | Restore (shown instead of `[↑]` while maximised) |
| `[■]` | Close (at the left end, `closable=True`) |

Double-clicking the title bar of a maximisable window does the same as
`[↑]` and `[↕]`: it maximises the window, or restores it if it is already
maximised. A window that cannot be maximised ignores the double-click. (See
`MouseEvent.clicks` under [Mouse](#mouse) for what counts as a
double-click.)

The close button sits two cells in from the left corner
(`╔═[■]═══ Title`). `■` is code page 437 character 254, and the arrows are
code page 437 glyphs 25, 24 and 18. Code page 437 draws its lowest byte
values as symbols, so every code page 437 font has these, even though
Python's `cp437` codec treats those bytes as control codes. Buttons are
drawn only on the active window, so clicking where an inactive window's
buttons would be simply brings that window to the front. Each button's
brackets are drawn in the frame's colours, and only the symbol between them
in `button_style`.

- **Maximise** (`PresentationManager.maximise`). The window fills the work
  area between the menu bar and the status bar, and is fitted to it again
  whenever the terminal is resized. It remembers its previous position and
  size. A maximised window can still be moved and resized, which stops it
  being maximised:
  - **Moving** it, by dragging its title bar (or with Alt+F7 and an arrow
    key), returns it to its previous size, with the pointer on the same
    part of its title bar, and it moves on from there.
  - **Resizing** it, by dragging its grip, which a maximised window keeps
    (or with Alt+F8 and an arrow key), resizes it from its current size,
    which fills the screen. There is then no earlier size to restore
    (`Window.release`).

  A click or double-click on its own does neither, and pressing Escape after
  Alt+F7 or Alt+F8 leaves the window maximised. `Window.restored_rect` is
  where restoring the window would put it.
- **Minimise** (`minimise`). The window leaves the screen and the stacking
  order. The manager keeps it in `minimised`, so Tab skips it. An
  application's minimised windows are listed in its Window menu, marked
  "(minimised)". A window that belongs to no application is listed at the
  top of the system menu instead, as `1 Notes`, `2 Files` and so on, with
  the mnemonics 1 to 9. Either way, the menu bar is always there, so no
  window can be lost.
- **Restore** (`restore`). A minimised window comes back to the front in
  the state it was in when it was minimised. If it was maximised, it is
  fitted to the screen as it is now. A maximised window returns to its
  earlier position and size. `toggle_maximise` switches a window between
  maximised and its normal size.

From the keyboard, F5 maximises or restores the active window
(`maximise_window` in the shortcuts file). `minimise_window` has no key by
default, but one can be assigned. Both keys act only on windows that offer
that option, whereas calling the manager's methods from code works on any
window.

### Animations

With animations turned on (`PresentationManager.animations`), changes of
position are drawn over a few frames rather than all at once:

- A window that is **minimised** shrinks into the middle of the status
  bar. When it is **restored**, or **maximised** while minimised, it grows
  back out of the status bar into its place.
- A window that is **maximised** or **restored** grows or shrinks between
  its two sizes.
- A **menu** opened from the menu bar drops down from under the bar (see
  the `shown` argument of `MenuBar.paint`).

Each animation draws `animation_frames` intermediate frames (2 by default),
each shown for `animation_frame_time` seconds (0.02), before the ordinary
frame that shows the finished result. The frames are drawn before any
further input is read. During an animation, only the window's frame moves
(`Window.paint_between`). Its contents stay exactly as they were when the
animation began: they are not laid out again or scrolled, but are cut off
where the frame is smaller and left blank where it is bigger. The frame
shows only the scroll bars that the window has at its full size, at the end
of the animation (`dasha.animation`). Dragging a maximised window by its
title bar restores it under the pointer without an animation.

Animations are off unless something turns them on. The desktop
(`dasha desktop`) turns them on, unless the user last turned them off, and so
does an application running on its own in a terminal. While Dasha Framework is
running, the system menu's **Animations: On** (or **Off**) item switches
them, and the desktop remembers the choice (`set_animations`,
`remember_animations`) by writing `animations = false` to
`~/.dasha/settings.toml`.

### Scrolling contents

A window's content is its lines and widgets, and it can be bigger than the
window. `Window.content_size` is how far the furthest line or widget
reaches; override it if `paint_content` draws something else. The window
shows the part of its content starting at `scroll_row` and `scroll_column`.
Lines and widgets are drawn at their positions in the content, and the
canvas clips them to the inside of the frame (`Canvas.clipped`). Clicks on
widgets take the scroll position into account.

**Scroll bars** appear on the frame only in a direction in which the
content does not fit:

| Bar | Where | Looks like |
| --- | --- | --- |
| Vertical | The right edge of the frame, between the corners | `▲`, a `▒` track with a `■` thumb, `▼` |
| Horizontal | The bottom edge, from two cells in (or after the footer) to two cells short of the corner, clear of the resize grip | `◄`, the track and thumb, `►` |

All of the scroll bars' characters are code page 437 glyphs (30, 31, 17,
16, 177 and 254). The bars are worked out each time the window is drawn, so
they appear and disappear by themselves as the window is resized or
maximised, or as widgets are added. The scroll position is kept within
range, so a window that grows big enough to show all its content scrolls
back to the top.

**A footer** is a short piece of text at the left of the frame's bottom
edge, made up of one or more parts (`╚═ ☼ ═ 12:3 ═◄▒▒■►─┘`). It is set
with `Window.footer`, a list of strings, or worked out each time the window
is drawn by overriding `footer_parts`, as Notepad's windows do to show
unsaved changes and the cursor position. Windows have no footer by default.
The frame draws its own line between each pair of parts, in its current
border and colours (double while the window is active, single while it is
not, and the moving frame's style while it is being moved), so the parts
themselves are only ever text. The horizontal scroll bar starts after the
footer. If the window is too narrow for the whole footer and a scroll bar
of at least two cells, the footer is hidden until the window is wide
enough again. An application running in its own process sends its footer
with its window, limited to `MAX_FOOTER_PARTS` parts of at most
`MAX_FOOTER` characters each, on one line.

| Input | Scrolls |
| --- | --- |
| Click an arrow | One line (`Window.scroll_step`); held down, it repeats |
| Click the track | A page, less one line, so that a line stays in view |
| Drag the thumb | To where it is dragged |
| Mouse wheel over a window | Three lines (sideways with Shift, or a sideways wheel), unless a widget under the pointer (a list box) scrolls instead |
| Up / Down / Left / Right, PgUp / PgDn | The active window, if no widget uses the key (`scroll_up`, ... in the shortcuts file) |

Moving the focus to a widget that is out of view (with Tab, for example)
scrolls it into view, by as little as possible. A widget bigger than the
window, such as a long text area, stays where it is as long as part of it
is showing. A click focuses the widget under the pointer without scrolling,
so a text area scrolled with the wheel and then clicked stays where it is.
From code, use `scroll_to`, `scroll_by`, `scroll_into_view`, `max_scroll`
and `scroll_bars`. The bars' colours are the `window.scrollbar` and
`dialog.scrollbar` roles.

Frame scroll bars and the `ScrollBar` widget are both drawn and hit-tested
by `dasha.scrollbar.ScrollBarLayout`, which describes a single bar in
its current state. It paints the bar, and reports which part is at a given
position (`part_at`), how far a click on that part scrolls (`step`), and
what value a dragged thumb sets (`value_at`).

**Auto-repeat.** Holding the mouse button down on an arrow or on the track
repeats the click, first after `AutoRepeat.delay` seconds (0.4) and then
every `AutoRepeat.interval` seconds (0.05), as long as the pointer stays on
the part first pressed. On the track, the repeating stops once the thumb
reaches the pointer. `dasha.scrollbar.AutoRepeat` handles the timing
for both window frames and `ScrollBar` widgets, so changing those two class
attributes changes it for a whole project. The repeats run on the
presentation manager's timers, so they happen even while the mouse is
still.

### Moving and resizing from the keyboard

Alt+F7 (`move_window`, or Ctrl+F5) starts moving the active window, and
Alt+F8 (`resize_window`) starts resizing it. The Window menu has Move and
Size items for the same thing, and code can call
`manager.start_moving(window=window)` or
`manager.start_resizing(window=window)`.

While it lasts, the window's frame shows in the `window.frame.adjusting`
colours, the status bar lists the keys, and every key goes to it:

| Key | Action | What it does |
| --- | --- | --- |
| Arrows | `adjust_left`, `adjust_right`, `adjust_up`, `adjust_down` | Move a cell, or resize: Right and Down make it bigger, Left and Up smaller |
| Tab | `adjust_switch` | Switch between moving and resizing |
| Enter | `adjust_accept` | Keep the window where it is |
| Esc | `adjust_cancel` | Put the window back as it was |

A mouse click also leaves the window where it is, and then acts as a normal
click. The same limits apply as with the mouse: the title bar stays between
the menu bar and the status bar, a window is never smaller than its
`min_width` by `min_height`, and only a `resizable` window can be resized.
However far the arrow keys push a window, at least `manager.rescue_margin`
(4) of its columns stay on screen. The window stops at the edge, so that it
can always be found again, and resizing a window that is partly off the
left edge moves it back on screen rather than losing it.
`manager.keep_reachable(window)` enforces this rule, which also applies to a
window added once the screen size is known (when an application positions
it, for example) and to a window moved by an application running in its
own process.

A maximised window stays maximised until the first arrow key is pressed.
Moving it then returns it to its previous size, while resizing it starts
from its current size. Escape maximises it again. `adjust_accept` and
`adjust_cancel` cannot both be left without keys.

### Closing

`PresentationManager.close(window)` closes a window if the window's
`request_close()` agrees. Override `request_close` to ask the user first,
about unsaved work for example. The `[■]` button and Alt+F4
(`close_window`) close the active window, if it is `closable`. Alt+F3 works
too, in terminals that pass it on: some terminals and desktop environments
keep Alt with F1, F2, F3, F9 or F10 for themselves, and
`dasha --key-test` shows which.

## Widgets (`dasha.widgets`)

Widgets are the controls inside a window. `Window.add(widget)` places a
widget in the window and returns it. Positions are relative to the window's
interior, so row 0, column 0 is the first cell inside the frame.

{py:mod}`dasha.widgets` is a package with a module for each kind of
widget (see the [API reference](api.rst)), and everything in those modules
can be imported from `dasha.widgets` itself.

**Growing with the window.** By default, a widget keeps the position and
size it was given, whatever happens to its window. A widget's `grow`
setting makes it follow the window instead: it names which of the widget's
edges move with the window's right and bottom edges when the window is
resized, maximised or restored.

| `grow` | When the window gets bigger |
| --- | --- |
| `Grow.NONE` (the default) | The widget stays as it is |
| `Grow.WIDTH` (`RIGHT`) | It gets wider |
| `Grow.HEIGHT` (`BOTTOM`) | It gets taller |
| `Grow.ALL` (`RIGHT \| BOTTOM`) | It fills the room the window gains |
| `Grow.STICK_RIGHT` (`LEFT \| RIGHT`) | It moves right, keeping its size (a button in a corner) |
| `Grow.STICK_BOTTOM` (`TOP \| BOTTOM`) | It moves down, keeping its size |

```python
files.add(
    widget=ListBox(items=names, row=0, column=0, width=32, height=7, columns=2),
    grow=Grow.ALL,
)
files.add(
    widget=Label(text="Selected: ...", row=7, column=1),
    grow=Grow.STICK_BOTTOM,
)
```

The flags can be combined (`Grow.STICK_RIGHT | Grow.STICK_BOTTOM` keeps a
widget in the bottom right corner). Set `grow` with
`Window.add(widget, grow=...)` or on the widget itself. Positions and sizes
are always worked out from where the widget was originally laid out, not
from where it was last, so shrinking a window and growing it again puts
everything back exactly as it was. No widget is made smaller than its
`min_size()`, which leaves room for a text box's arrows, a button's label,
a list box's columns, and the options of check boxes and radio buttons. If
code moves a widget, it is laid out afresh from its new position. After a
widget grows, its `on_resize()` is called; a list box uses this to keep its
highlighted item in view.

These are the widgets, each linked to its reference page:

```{eval-rst}
.. autosummary::
   :nosignatures:

   ~dasha.widgets.base.Widget
   ~dasha.widgets.label.Label
   ~dasha.widgets.button.Button
   ~dasha.widgets.textbox.TextBox
   ~dasha.widgets.textarea.TextArea
   ~dasha.widgets.checkbox.CheckBoxes
   ~dasha.widgets.radiobutton.RadioButtons
   ~dasha.widgets.cluster.Cluster
   ~dasha.widgets.switch.Switch
   ~dasha.widgets.container.Container
   ~dasha.widgets.collapsible.Collapsible
   ~dasha.widgets.groupbox.GroupBox
   ~dasha.widgets.paragraph.Paragraph
   ~dasha.widgets.password.PasswordBox
   ~dasha.widgets.tabs.Tabs
   ~dasha.widgets.tabs.TabPage
   ~dasha.widgets.splitter.Splitter
   ~dasha.widgets.splitter.SplitPane
   ~dasha.widgets.table.Table
   ~dasha.widgets.table.Column
   ~dasha.widgets.tree.TreeView
   ~dasha.widgets.tree.TreeNode
   ~dasha.widgets.listbox.ListBox
   ~dasha.widgets.combobox.ComboBox
   ~dasha.widgets.autocomplete.AutoCompleteBox
   ~dasha.widgets.spinbox.SpinBox
   ~dasha.widgets.slider.Slider
   ~dasha.widgets.progressbar.ProgressBar
   ~dasha.widgets.progressbar.ColumnBar
   ~dasha.widgets.scrollbar.ScrollBar
```

Any widget can have a `name`, by which it can be found again
(`window.widget(name)`, `window.values`). It can also have `status` text,
which the status bar shows while the widget has the focus.

**Focus.** One focusable widget at a time has the keyboard focus. The first
one added starts with it, and it is shown highlighted while the window is
active. When a window has two or more focusable widgets, Tab and Shift+Tab
move the focus between them (`next_widget`, `previous_widget`). Tab never
moves to another window; F6 and Shift+F6 do that.

**Pressing a button.** Enter, Space, the button's letter or a click presses
a {py:class}`~dasha.widgets.button.Button`. In a dialog, Enter presses
the `default` button wherever the focus is, unless the focus is on another
button.

### Check boxes and radio buttons

`CheckBoxes` (any number of options can be checked) and `RadioButtons`
(exactly one option is selected) are groups of options, known as clusters.
They share the base class {py:class}`~dasha.widgets.cluster.Cluster`,
whose reference describes the keys, columns and disabled options. See also
{py:class}`~dasha.widgets.checkbox.CheckBoxes` and
{py:class}`~dasha.widgets.radiobutton.RadioButtons`.

### Switches

A {py:class}`~dasha.widgets.switch.Switch` is an on-or-off setting,
drawn as a knob sliding along a three-cell track (`█░░` when off, `░░█` when
on), raised with a button's shadow.

### Collapsible areas

A {py:class}`~dasha.widgets.collapsible.Collapsible` is a header,
`► Label` or `▼ Label`, above an area of widgets that are shown only while
it is expanded. When it expands, the widgets below it move down out of the
way, and they move back when it collapses. It is the only container that
takes up room below itself (see [Containers](#containers)).

### Containers

Some widgets hold other widgets: collapsible areas, group boxes, tab pages
and the panes of a splitter. These are **containers**
(`dasha.widgets.container.Container`), and they all work in the same
way.

- **Adding widgets.** First add the container to its window, then call
  `container.add(widget)`. This places the widget relative to the start of
  the container's content (`content_origin()`), such as the first row below
  a collapsible area's header, or the first cell inside a group box's
  frame.
- **They are still ordinary widgets.** A widget in a container is also in
  `window.widgets`, after its container (so that it is drawn on top of it).
  Its `widget.parent` is set to the container, and `container.children`
  lists the container's widgets. Tab, mnemonics, `window.widget(name)` and
  `dialog.values` find them just like any other widget.
- **Showing.** A widget is shown (`widget.is_shown`) only while every
  container it is in is showing its widgets (`is_showing_children`). The widgets
  of a collapsed area are not shown, for example, and neither are those of
  a tab page that is not selected. A widget that is not shown is not drawn
  and receives no keys, clicks or timers, but it keeps its value.
- **Moving.** Each container belongs to a widget, its `anchor` (either the
  container itself, or the widget that owns it, such as the tabs of a tab
  page), and its widgets move with that widget. Only a collapsible area
  takes up room below itself (`opens_below`); every other kind keeps its
  widgets within its own rectangle. `dasha.widgets.container.lay_out`
  keeps everything in place, and `Window.lay_out()` runs it.
- **Nesting.** Containers of any kind can be nested: a group box in a
  collapsible area, a collapsible area in a group box, and so on.

To create a new kind of container, subclass `Container` (and `Widget` too,
if the container is a widget), and provide `anchor`, `content_origin()`
and, if its widgets can be hidden, `is_showing_children`.

### Group boxes

A {py:class}`~dasha.widgets.groupbox.GroupBox` is a titled single-line
frame around widgets that belong together. It is a container, and pressing
the letter of its title moves the focus into it.

### Paragraphs

A {py:class}`~dasha.widgets.paragraph.Paragraph` is static text wrapped
over several lines, aligned left, centred, aligned right or justified. It
scrolls when it is given less height than it needs.

### Password boxes

A {py:class}`~dasha.widgets.password.PasswordBox` is a text box that
shows `•` for each character and does not allow its contents to be copied
or cut.

### Tabs

{py:class}`~dasha.widgets.tabs.Tabs` shows several pages of widgets
(each a {py:class}`~dasha.widgets.tabs.TabPage` container) in the same
place, with a row of tabs above them to choose which page is shown.

### Splitters

A {py:class}`~dasha.widgets.splitter.Splitter` holds two panes of
widgets (each a {py:class}`~dasha.widgets.splitter.SplitPane`
container), either side by side or one above the other, with a divider
between them that can be dragged. A pane moves and stretches its widgets
according to their `grow` setting, just as a window does
(`Container.sizes_children`).

### Tables

A {py:class}`~dasha.widgets.table.Table` shows rows of fields under
column headings ({py:class}`~dasha.widgets.table.Column`). Clicking a
heading sorts the rows by that column, and columns can be resized by
dragging.

### Tree views

A {py:class}`~dasha.widgets.tree.TreeView` is an outline of items
({py:class}`~dasha.widgets.tree.TreeNode`) that can be expanded and
collapsed, with lines joining each item to the one above it in the outline.
It suits any hierarchy, such as folders on a drive.

```python
def subfolders(node):
    return [
        TreeNode(label=name, data=path, load=subfolders)
        for name, path in folders_in(folder=node.data)
    ]

roots = [TreeNode(label="C:\\", data="C:\\", load=subfolders)]
picker = window.add(
    widget=TreeView(roots=roots, row=0, column=0, width=30, height=12)
)  # multiple=True to pick several
```

- **Items.** The application supplies the items. An item's children can be
  given from the start, or found only when it is first expanded: its `load`
  callback is called with the item then, and returns the children. Until
  then, the item is marked as one that can be expanded.
- **Keys and the mouse.** Right (`tree_expand`) expands the highlighted
  item, or goes to its first child; Left (`tree_collapse`) collapses it, or
  goes to its parent; Enter (`tree_choose`) chooses it, or expands or
  collapses it. A click on `►` or `▼` expands or collapses an item. The
  rest is as in a list box: the arrow keys, PgUp, PgDn, Home and End, typing
  to find an item, the scroll bar and the mouse wheel.
- **Selection.** As in a list box, a tree view selects one item (the
  highlighted one) by default, or with `multiple=True` any number of them,
  with Space (`list_toggle`), Ctrl+A (`list_select_all`), a click, or Shift
  and a click. Items stay selected while the items above them are
  collapsed. `selected_node` is the highlighted item, `selected_nodes` the
  selected ones, and `set_selected_nodes(nodes)` selects others from code.

In the Demo application, File > Choose folder... picks a folder from a tree
of the computer's own folders, each folder's folders found only when it is
first expanded.

### Context menus

A widget or a window can have a menu that pops up for it, called a
**context menu**.

```python
files.context_menu = Menu(
    title="File",
    items=[
        MenuItem(label="&Open", action=open_file),
        separator(),
        MenuItem(label="&Delete", action=delete_file),
    ],
)
window.context_menu = Menu(
    title="Window", items=[MenuItem(label="&Refresh", action=refresh)]
)
```

- **Opening one.** A right-click brings the window to the front and pops up
  the menu of the widget under the pointer, which takes the focus, or, if
  the widget has none, the window's menu, at the pointer. On a list box,
  table or tree, a right-click first highlights the item under the pointer
  (`Widget.point_at`), so that the menu acts on what was clicked. Shift+F10
  (`context_menu`) pops up the focused widget's menu just below it, or the
  window's menu at the top left of its interior.
- **Using the menu.** Items are drawn as in the menu bar's menus: greyed out
  where they cannot be chosen, and with their shortcuts on the right. Down
  and Up (`menu_down`, `menu_up`) move between the items that can be
  chosen. Enter (`menu_choose`), an item's letter or a click chooses an
  item, and Right (`menu_right`) opens a submenu beside it. Escape, Left in
  a submenu, or a click outside closes the menu. The chosen item runs once
  the menu has closed, so it can show dialogs of its own.
- **Built-in menus.** Text boxes and text areas have a menu of their own
  unless they are given another: Undo, Cut, Copy, Paste and Select all, each
  greyed out when it would do nothing. A password box's menu has no Cut or
  Copy.
- **How it works.** `Widget.popup_menu(shortcuts)` returns the menu to pop
  up (by default, the widget's `context_menu`).
  `PresentationManager.context_menu(menu, row, column)` shows it in a
  `MenuPopup`, which is a popup like a combo box's list, so context menus
  also work for applications running in their own processes.
  `place_popup` puts any popup at a given place on the screen, keeping it
  within the screen.

In the Demo application, File > Explorer shows a tree of folders beside a
table of their files, with a context menu for the files.

### Combo boxes

A {py:class}`~dasha.widgets.combobox.ComboBox` shows the current choice
in a one-row field, with `▼` to drop down the whole list and choose another.
The list is a popup (see [Popups](#popups)).

### Progress bars and column bars

A {py:class}`~dasha.widgets.progressbar.ProgressBar` fills from left to
right to show how far a task has progressed, with text in the middle that
changes colour as the bar passes it.
{py:class}`~dasha.widgets.progressbar.ColumnBar` is the same, but
vertical.

### Sliders

A {py:class}`~dasha.widgets.slider.Slider` is a knob that slides along
a horizontal or vertical track to choose a whole number within a range.

### Spin boxes

A {py:class}`~dasha.widgets.spinbox.SpinBox` holds a whole number within
a fixed range, which can be typed in or stepped up and down with `▼▲`. A
typed number outside the range is discarded.

### Autocomplete boxes

An {py:class}`~dasha.widgets.autocomplete.AutoCompleteBox` is a text
box that shows a drop-down list of suggestions as you type, while still
accepting any text. The suggestions are a popup (see [Popups](#popups)).

### List boxes

A {py:class}`~dasha.widgets.listbox.ListBox` is a list of items from
which one or several can be chosen, laid out in one or more columns. It
scrolls when the items do not fit, and typing jumps to a matching item. Its
scroll bars are {py:class}`~dasha.widgets.scrollbar.ScrollBar` widgets
of its own, which can also be placed in a window on their own.

### Terminal views

A {py:class}`~dasha.widgets.terminalview.TerminalView` runs a
command-line program (the user's shell by default) in a pseudo-terminal the
size of the widget, and shows its `Screen`. Its reading thread hands output
to the desktop with `call_from_thread`, at most `FEED_LIMIT` bytes at a
time, so a flood of output cannot freeze the screen. Keys go to the program
through `encode_key`, except those the desktop keeps (`RESERVED_ACTIONS`),
which a view declines even on a desktop of its own, so that it behaves as
it does in a hosted application. Pastes are wrapped as bracketed pastes for
a program that asks. The mouse wheel scrolls back through the scrollback,
and a drag selects text to copy, except for a program that asks to be told
of the mouse (`Screen.is_tracking_mouse`): then presses, drags, releases and
the wheel go to it through `encode_mouse`, and so does a right-click (the
view offers no menu meanwhile), unless `send_mouse` is off or Shift is
held. A drag's release goes wherever its press went. Moving with no button
held never reaches a widget, so it is not reported. `on_output` and
`on_exit` tell its owner
when output has been shown and when the program has ended. The Terminal
example application is a window around one.

The view covers the inside of its window, so the window's `body_style` does
not show through it. Whatever the program leaves in its default colours,
blank cells included, takes the view's `default_style`. By default that has
no colours, so the terminal Dasha Framework is running in chooses them. Colours the
program asks for are kept.

### Text areas

A {py:class}`~dasha.widgets.textarea.TextArea` holds many lines of text
to edit: put one in an otherwise empty window, and the window becomes a text
editor. It grows with its text, so the window's own scroll bars scroll it.

- **Word wrap.** With `word_wrap=True` (off by default, and changeable at
  any time), a line too long for the window continues on the rows below,
  broken after a space where possible. The text area then stays as wide as
  the window and only scrolls up and down.
- **Line numbers.** With `line_numbers=True` (also off by default), each
  line's number is shown at its left, right-aligned, followed by a `│`. A
  wrapped line is numbered on its first row only. The column of numbers is
  three digits wide, and widens when there are more lines than that
  (to four digits at line 1000). It stays in view as the window scrolls
  sideways, and uses the `textarea.numbers` colours.

### Text boxes

A {py:class}`~dasha.widgets.textbox.TextBox` holds a single line of
text, which scrolls sideways, with an optional `max_length` and an optional
`pattern` that the text must match. A click puts the cursor under the
pointer, a drag or Shift+click selects, and a double-click selects all the
text, as Ctrl+A does (a double-click in a text area selects its line). The
boxes built on a text box, such as a spin box's number, a password box and
an autocomplete box, do the same.

### Popups

A combo box's list, an autocomplete box's suggestions and context menus are
all **popups** (`dasha.dialog.Popup`): dialogs placed next to something,
which are cancelled by a click outside them. The desktop frames them with
single lines, including for applications running in their own processes.

The list is shown by `PresentationManager.pick(items, selected, below)`,
which any widget can use. `below` is a rectangle on the screen
(`window.screen_rect(widget)` gives a widget's), and the method returns the
index of the chosen item, or `None`. It runs a `ListPopup` dialog through
`execute`, so it only shows anything while `run` is going; a window can
reach its presentation manager as `window.manager`. A dialog with
`centred = False` stays where it was placed, and one with
`close_on_outside_click = True` is cancelled by a click outside it.

An autocomplete box's suggestions are a `SuggestionPopup`, shown by
`PresentationManager.suggest(box, items)` in the list box's colours, and a
context menu is a `MenuPopup` (see [Context menus](#context-menus)).

### Writing a widget

To make a new kind of control, subclass
{py:class}`~dasha.widgets.base.Widget` and override `paint` (and
`handle_key`, `handle_mouse`, `value` and `activate` as needed). A new kind
of widget belongs in a module of its own, added to
`dasha/widgets/__init__.py`. Its colours are class attributes, listed as
roles in `dasha.theme`, and its key actions belong in
`dasha.shortcuts`.

- **Keys.** Keys go first to the menu bar, then to the active window's
  widgets, and then to the presentation manager. `handle_key(key,
  shortcuts)` receives the shortcuts in effect, so a widget's own keys can
  be remapped too.
- **Keys anywhere in the window.** Keys that work anywhere in a window, as
  Ctrl+PgDn does for tabs, are handled by `Widget.window_key(key,
  shortcuts)`. A key that no widget has used is offered to every widget
  that is shown, starting with the focused widget and the widgets it is
  inside.
- **Mnemonics.** A widget with more than one mnemonic letter, such as a
  group of check boxes or radio buttons, returns them all from
  `mnemonics()`, and the window calls `activate_mnemonic(letter)` on it.
- **Focus.** `focus_changed(focused)` tells a widget when the keyboard
  focus arrives, or leaves it for another widget in the same window. The
  spin box uses this to select its number, and to accept what was typed.
- **Sizing to the window.** Widgets that size themselves to their window,
  as a text area does, use two hooks: `on_add()`, called once `Window.add`
  has placed the widget in its window, and `follow_resize(before, after)`,
  which a text area overrides to fit the window whatever its `grow`
  setting.
- **Timers.** A widget that needs to act when no input arrives, such as a
  text box that scrolls while the mouse is held still, returns a time (from
  `time.monotonic()`) from `wake_time()`. The presentation manager waits for
  input only until the earliest wake time of any widget, both in `run` and
  in dialogs, and then calls that widget's `on_timer(now)`. A widget that
  returns `None`, as widgets do by default, costs nothing: the manager
  simply waits for input for as long as it takes.
- **Other threads.** Only the thread the desktop runs on may touch windows
  and widgets. Another thread (one reading a program's output, say) hands
  work to it with `manager.call_from_thread(callback)`, which may be called
  from any thread. The callback is queued and the loop is woken
  (`manager.wake`): on a desktop of its own, `Terminal.wake` cuts short the
  wait for input (through the self-pipe that resizes use on POSIX, and an
  event waited on with the console's input on Windows); in an application
  hosted by the desktop, a byte down a pipe of its own ends the wait for
  the desktop's next message. The loop then calls the queued callbacks, in
  order, before drawing. A wake that lands while the rest of an escape
  sequence is awaited does not cut that wait short (`read_events`), so a
  key's sequence is never split.

## Clipboard (`dasha.clipboard`)

Dasha Framework has a single clipboard, `CLIPBOARD`, shared by everything running
in it. It holds one `ClipboardItem` at a time, made up of a `type` (written
like a MIME type), the `data`, and any `metadata` (a mapping) that the code
pasting it may need. Dasha Framework's own widgets cut and copy text, as `TEXT`
(`"text/plain"`, whose data is a `str`). Other types, such as binary data or
files, can also be put on the clipboard, and code that pastes asks only
for the types it understands:

```python
from dasha.clipboard import CLIPBOARD, ClipboardItem

CLIPBOARD.copy_text(text="hello", source="notes")
CLIPBOARD.text                             # "hello"
CLIPBOARD.copy(
    item=ClipboardItem(type="text/uri-list", data=["file:///tmp/notes.txt"])
)
CLIPBOARD.text                             # None: not text any more
CLIPBOARD.get("text/uri-list")             # the item (types, so by position)
```

`get(*types)` returns the item only if it is one of the given types, and
`text` gives only text. `clear()` empties the clipboard, and the
functions in `listeners` are told about every change.

**In a text box.** Ctrl+X and Ctrl+C cut and copy the selection, and do
nothing if nothing is selected. Ctrl+V pastes over the selection, or at the
cursor. Before a paste changes anything, the box checks two things, and if
either check fails, nothing happens at all:

- **The type.** Only `TEXT` is pasted, so a file, for example, is ignored.
- **The result.** The text after the paste must be text that the box
  accepts: within `max_length`, matching `pattern`, and on one line.
  Pasting `"hello"` into a box for numbers changes nothing, and neither does
  pasting `"3a4"`. Text is never partly pasted.

Likewise, a cut that would leave text the box would refuse does nothing at
all: it neither copies nor deletes. Code can call `cut()`, `copy()` and
`paste()`, which return whether they did anything, and `insert(text)`,
which inserts any text in the same way as a paste. Each box uses
`TextBox.clipboard`, which is `CLIPBOARD` unless the box or a subclass is
given another.

This is Dasha Framework's own clipboard, not the operating system's; a program
running over SSH could not reach the system clipboard in any case. Some
terminals use Ctrl+V (or Ctrl+C when text is selected in the terminal) for
their own paste and copy, so those keys never reach Dasha Framework. In that case,
remap `text_paste` and the related actions in `shortcuts.json`.

**Pasting through the terminal.** Text pasted by the terminal itself (with
its own Ctrl+V or right-click, from the system clipboard) does not go
through `CLIPBOARD`, but a text box handles it in the same way:
`TextBox.handle_paste` calls `insert`, so either the whole result is
accepted or nothing changes. A single line break at the end is removed
first, because copying a whole line in a terminal often copies its line
break too. This relies on bracketed paste (see
[Input](#pasting-through-the-terminal)). In a terminal without it, pasted
text arrives as if it were typed, and each character is checked separately.

## Dialog boxes (`dasha.dialog`)

A `Dialog` is a modal window, grey.
`PresentationManager.execute(dialog)` shows it in the middle of the work
area, on top. Until it is answered, nothing else responds: other windows,
the menu bar and window keys are all out of reach, and clicks outside it
are ignored.

`execute` waits and **returns the answer** to the code that called it:

- **A button.** The `result` of the button pressed: `"ok"`, `"cancel"`, or
  any string a button was given.
- **Cancelled.** The dialog's `cancel_result` (`"cancel"`), if it was
  cancelled with Escape (`dialog_cancel`) or its `[■]` button.

The dialog then leaves the screen, but the caller still holds it and can
read **every component** in it before deciding what to do:

```python
dialog = Dialog(title="Save changes?", width=40, height=9)
dialog.add(
    widget=Label(text="notes.txt has changed.", row=1, column=2, name="message")
)
dialog.add(
    widget=Button(label="&Save", row=3, column=2, result="save", default=True)
)
dialog.add(widget=Button(label="&Discard", row=3, column=14, result="discard"))
dialog.add(widget=Button(label="Cancel", row=3, column=26, result="cancel"))

answer = manager.execute(dialog=dialog)
if answer == "save":
    save()
elif answer == "discard":
    close_without_saving()
print(dialog.values)   # every named widget's value, by name
```

`confirm(title, message)` builds the common OK / Cancel dialog. Its widgets
are named `"message"`, `"ok"` and `"cancel"`, and its button labels can be
changed (`ok_label="&Yes"`). `information(title, message)` builds a dialog
with only an OK button, to tell the user something. Its widgets are
`"message"` and `"ok"`, and it answers `"ok"` (or `"cancel"` if it is closed
with Escape).

Both functions accept `align=` for the message: `"left"` (the default),
`"centre"`, `"right"` or `"justify"`. Lines are aligned
across the message area, which is as wide as the longest line or the row of
buttons, whichever is wider. Justified lines have the spaces between their
words widened to fill the width, as in print, except for the last line of
each paragraph (before a blank line, or at the end) and lines of a single
word, which are left as they are. Lines are never rewrapped: the message's
own line breaks decide where lines end. `align_lines(lines, width, align)`
does the same for any text.

Dialogs can open further dialogs, because calls to `execute` can be nested.
`execute` reads the terminal itself, so it only works while `run` is
going. Code that runs before then, such as an application's `start`, can
pass a function that shows the dialog to `call_when_running(callback)`,
which calls it straight away if the desktop is already running, and
otherwise as soon as `run` starts.

**Exit confirmation.** Choosing Shutdown from the system menu (so named to
distinguish it from an application's own File > Exit), double-clicking the
system menu's `≡` on the menu bar, and pressing the `exit` key (Ctrl+Q) all
call `request_exit()`. This shows the warning "Warning: Shutting down Dasha
Desktop will close all open applications." (`exit_message`) in a `confirm`
dialog whose
OK button is labelled Shutdown, and quits only if that button is pressed,
just as any other code would use a dialog. Set `confirm_exit = False` to
quit without asking.

### File dialogs (`dasha.filedialog`)

`FileDialog(title, directory=..., filters=..., name=..., must_exist=...)`
lets the user choose a file. It only chooses a path: whether the file is to
be opened or saved depends on its title and on what the calling code does
with the path.

```python
dialog = FileDialog(
    title="Open", filters=[("Text files", "*.txt")], must_exist=True
)
if manager.execute(dialog=dialog) == "ok":
    load(path=dialog.path)

dialog = FileDialog(title="Save as", name="notes.txt")
if manager.execute(dialog=dialog) == "ok":
    save(path=dialog.path)   # ask about overwriting with confirm(), if wanted
```

```
╔═[■]═══════════════════ Open ═══════════════════════╗
║ Name                                               ║
║  notes.txt                                OK    ▄  ║
║ Files                                  ▀▀▀▀▀▀▀▀▀▀  ║
║ ..\              │ notes.txt                       ║
║ docs\            │ readme.txt           Cancel  ▄  ║
║ src\             │                     ▀▀▀▀▀▀▀▀▀▀  ║
║                  │                                 ║
║ Type   Text files (*.txt)      ▼  Drive  C:    ▼   ║
║ C:\GitHub\dasha                                    ║
║ notes.txt  1,204 bytes  17 Oct 2026 10:30          ║
╚════════════════════════════════════════════════════╝
```

- **The list** shows `..` (except at the top of a drive), then the folders,
  marked with `os.sep`, and then the files that the selected type allows,
  with each group sorted alphabetically, ignoring case. It is a two-column
  `ListBox` that scrolls sideways.
- **Highlighting** an item puts its name in the Name box, and its size and
  date (or "Folder") on the bottom line.
- **OK, or Enter** anywhere in the dialog, reads the Name box. A folder
  (`..`, `docs\`, or a typed path to a folder) is opened, and going back up
  highlights the folder you left. A name containing `*` or `?` becomes the
  filter until the type is changed. Anything else is the answer, and the
  dialog answers `"ok"`. With `must_exist`, the file must already exist
  (otherwise the dialog says "No such file"), and its folder must always
  exist ("No such folder"). Typed paths can be absolute, or relative to the
  folder shown.
- **A double-click** on an item is the same as choosing it and pressing OK.
  Cancel or Escape answers `"cancel"`.
- **Types.** `filters` is a list of (label, pattern) pairs, shown as
  `Text files (*.txt)`, and a pattern can combine several with `;`
  (`"*.py;*.pyw"`). "All files (*)" is added unless one of the filters
  already matches everything.
- **Drives.** On Windows (`FileDialog.show_drives`), a Drive box lists the
  drives (`list_drives()`, which uses `os.listdrives` where Python has it,
  and otherwise every drive letter that exists), and choosing one opens the
  top of that drive.
- **A folder that cannot be read** shows "Cannot read this folder", and the
  list stays as it was.

Afterwards, `path` is the full path of the chosen file, and `directory` and
`name` are its folder and name. `refresh()` reads the folder again, and
`change_directory(path)` shows another folder. Notepad's File menu uses the
file dialog for Open... and Save as..., and so does the Demo application.

**About.** About in the system menu calls `about_box()`, which shows
`about_message` (by default the name and version) in an `information`
dialog titled `about_title`. Set these two attributes on the manager to give
an application its own About box.

## Settings (`dasha.settings`)

Settings... in the system menu (`PresentationManager.settings_dialog`)
changes, from within Dasha Framework, everything that the command line and the
settings files configure. It is a `SettingsDialog`, with a tab for each of
four pages:

- **Appearance** (`AppearancePage`): the theme to start from, and a list of
  every role (`theme.ROLES`), with the highlighted role's description,
  foreground, background, bold, underline and reverse, whether a shadow is
  drawn at all, and the button shadow's shape. The last colour offered,
  Custom..., asks for an RGB colour (`ColourDialog`). Load... and Save as...
  read and write theme files.
- **Shortcuts** (`ShortcutsPage`): a table of every action and its keys.
  Add key... asks for a key by having it pressed (`KeyDialog`, which takes
  every key, Escape and Enter included, as the key to add). Remove keys,
  Default and Reset all change the keys, and Load... and Save as... read and
  write shortcuts files. Every change is checked by `Shortcuts` itself, so a
  set that would leave no way out by keyboard is refused, with the reason.
- **Desktop** (`DesktopPage`): animations, how colours are drawn
  (`colour_depth` in `settings.toml`), showing the mouse (`show_mouse`),
  how long Escape waits for the rest of a key (`escape_timeout`), and the
  applications to start with the desktop (`autostart`).
- **Applications** (`ApplicationsPage`): the installed applications.
  Install... (`InstallDialog`) is Run...'s dialog with the name, group and
  single-instance choice of `dasha install-app` added, and Uninstall can
  also delete a virtual environment that install-app made. Making a virtual
  environment and installing packages into it are left to the command
  line, which shows pip's progress as it works.

Changes show at once. A new theme or colour is put on the screen with
`use_theme`, and new shortcuts take effect with `set_shortcuts`, which also
sends them to every application running in its own process (a `shortcuts`
message). OK keeps the changes and closes the dialog, and Apply keeps them
without closing it. Each page saves only what has changed, to the files the
desktop reads when it starts:

- changed colours to the colours file (`colours_path`), and a theme chosen
  unchanged to `settings.toml` by name, as the Themes menu does;
- the shortcuts to the shortcuts file (`shortcuts_path`), keeping only the
  actions that differ from the defaults (`Shortcuts.overrides`);
- animations, how colours are drawn, showing the mouse, how long Escape
  waits, and the applications to start with the desktop to `settings.toml`
  (`registry.save_animations_setting`, `save_colour_depth_setting`,
  `save_show_mouse_setting`, `save_escape_timeout_setting` and
  `save_autostart_setting`).

Both paths are those the command line chose (`--colours` and
`--shortcuts`), or the default files. Every settings file (and Notepad's
files) is written with `config.write_atomically`: whole, or not at all. The
text goes to a temporary file beside the real one, flushed to the disk,
which then takes the real file's place in one step (`os.replace`), so a
full disk or a crash part-way leaves the old file as it was rather than
empty, which for the shortcuts or colours file would stop Dasha Framework
starting. The file keeps its permissions, and a symbolic link is written
through. On Windows a file held open by another program cannot be
replaced, and is then written in place, once the text has been written
safely beside it. Cancel puts back the colours, shortcuts, animations,
colour depth, showing of the mouse and Escape wait that were in use when
the dialog opened, or when Apply was last pressed. Installing and uninstalling happen at once, and
are not undone by Cancel.

## Applications (`dasha.application`)

Dasha Framework is a presentation manager: it starts with an empty desktop, and
**applications** run on it. An application owns a menu bar, any number of
windows, and the dialogs it opens from them. To write one, subclass
`Application`, and in `start`, set its `menus` and open its first windows:

```python
from dasha.application import Application
from dasha.canvas import Rect
from dasha.menu import Menu, MenuItem
from dasha.window import Window


class Hello(Application):
    name = "Hello"

    def start(self) -> None:
        self.menus = [
            Menu(
                title="&File",
                items=[
                    MenuItem(label="&New window", action=self.new_window),
                    MenuItem(
                        label="&Close",
                        action=self.close_window,
                        enabled=self.has_window,
                    ),
                    MenuItem(label="E&xit", action=self.exit),
                ],
            )
        ]
        self.new_window()

    def new_window(self) -> None:
        self.open(
            window=Window(
                title="Hello",
                rect=Rect(row=2, column=2, height=6, width=30),
                lines=["Hello, world"],
                closable=True,
            )
        )

    def close_window(self) -> None:
        if self.active_window is not None:
            self.close(window=self.active_window)


if __name__ == "__main__":
    raise SystemExit(Hello().run())
```

**Menus belong to the application.** While an application is the *active
application*, the menu bar shows the system menu (`≡`), the application's
`menus`, and a Window menu that Dasha Framework adds. A menu with
`after_window=True`, as a Help menu usually is, goes after the Window menu
instead of before it. The application's menu items act on its
`active_window`, the one of its windows nearest the front. An item that needs
a window is created with `enabled=self.has_window`, so that it is greyed out
while there is none. (`MenuItem(enabled=...)` accepts any check, which is
called each time the menu is shown or the item is chosen.)

- **The active application** (`manager.active_application`) follows the
  front window: clicking a window, pressing F6 or bringing a window forward
  makes its application the active one. Closing or minimising a window
  brings forward that application's next window. When it has none left,
  the application stays active, with its menu bar still showing. If an
  application with no windows is switched to (`manager.switch_to`), no
  other application's window has the keyboard (`manager.active_window` is
  `None`).
- **The Window menu** is the same for every application, and Dasha Framework
  fills it in. It has Maximise / Restore, Minimise, Move, Size, Send to
  back, Next window and Close for the active window (each greyed out if
  that window does not allow it, or if there is no window), followed by a
  list of all the application's windows, with minimised ones marked, to
  bring forward or restore.
- **The system menu** lists the running applications at the top, to switch
  between them, with the active one marked (`√ 1 Notepad`, `2 Demo` and so
  on; a second Notepad is listed as `Notepad (2)`).
- **Windows without an application.** A window that belongs to no
  application (because it was added directly to the manager) shows its own
  `menus` while it is in front. A dialog, which has no menus, leaves the
  active application's menu bar showing, but inert (`manager.inert_menus()`;
  `MenuBar.set_menus(menus, inert=...)`): its menus cannot be opened by key
  or mouse, and their shortcuts do not work, until the dialog is answered.
  The system menu stays usable, because other applications carry on
  running.

- **Standalone.** `Hello().run()` runs the application on a desktop of its
  own, which closes when the application ends. Nothing else is needed, so a
  developer can write an application with nothing but `import dasha`.
  That desktop belongs to the application alone, so it has no system menu
  (`≡`), which exists for Dasha Framework to manage applications
  (`manager.show_system_menu` is false). The menu bar holds just the
  application's menus and its Window menu, and the exit key (Ctrl+Q) asks,
  for example, "Close Notepad?" rather than warning about shutting Dasha Framework
  down (`exit_title`, `exit_message`, `exit_button`, `exit_status`). While
  `dasha notepad` waits for Notepad's process to load, there is nothing
  yet to put on the bar, so its row shows the desktop's pattern (see
  "Loading" below).
- **On the desktop.** `manager.start(application=Hello)` starts an
  application as the desktop does, in its own process (see below), while
  `manager.launch(application=Hello)` (given a class or an instance) starts
  it in the current process and returns it.
  `manager.register(applications=Hello)` (or a dict mapping names to classes)
  lists it in the system menu's Applications submenu, which appears once
  something has been registered. `manager.applications` lists the running
  applications, and `manager.application_of(window)` (or
  `window.application`) returns the application a window belongs to.
- **Its windows.** `open(window)` shows a window and records it in
  `windows`, and `close(window)` closes one as the user would (the window's
  `request_close` can refuse, to offer to save first). Windows added
  directly to the manager, and dialogs, belong to no application.
- **Ending.** An application runs until it ends itself, not until its
  windows are closed: closing them all leaves it running, with its menus
  still on the bar. So every application provides a way to quit, typically
  File > Exit. `exit()` ends the application if `can_close()` agrees (Notepad
  offers to save each changed file), and `quit()` ends it immediately,
  removing its windows from the desktop. An application that never opens a
  window still runs, with just its menus.
- **New shortcuts.** When the user changes the shortcuts while it runs,
  `shortcuts_changed()` is called, with `manager.shortcuts` already the new
  ones. Menu items keep the key hints they were made with, so an
  application that shows hints makes its menus again there, as Terminal
  does.
- **One at a time.** With `single_instance = True`, launching an
  application again switches to the running one instead of starting
  another.
- **Shutting down.** After the Shutdown question, Exit asks each
  application's `can_close()`, and any of them can stop the shutdown
  (Notepad offers to save each changed file, and choosing Cancel keeps it
  running).

`dialog.question(title, message, answers)` asks a question with a button for
each answer, as Notepad's "Save the changes?" does with Save, Don't save and
Cancel.

**No applications come with Dasha Framework.** The package contains only the
framework and the desktop. `dasha desktop` starts an empty desktop that offers
the installed applications (see
[Installing applications](#installing-applications-dasharegistry-dashainstall)),
and when there are none, its Applications submenu shows "(None installed)",
greyed out. The repository's `apps/` folder, which is not part of the
package, holds three example applications as plain scripts. Each can be run
on its own (`python apps/notepad.py`) or installed on the desktop
(`dasha install-app apps/notepad.py`), and each has its own tests (see
`apps/README.md`):

| Script | Application | What it is |
| --- | --- | --- |
| `apps/notepad.py` | `Notepad` | A plain text editor with a window for each file. It reads and writes UTF-8 files, and has File, Edit, Insert and Format menus, with word wrap, line numbers, the cursor position and an unsaved-changes marker. |
| `apps/terminal.py` | `Terminal` | The user's shell (or another command) in a window for each: a `TerminalView` in a window, with menus to send the keys the desktop keeps, copy and paste. |
| `apps/demo.py` | `Demo` | Widgets, More widgets and Files windows: labels, text boxes, buttons, a switch, and a dialog of radio buttons and check boxes; a collapsible area, progress and column bars, sliders, a spin box and an autocomplete box; a list box in columns, the file dialogs, and choosing several files at once; a tree of the computer's folders to choose one from; an Explorer window of folders and files; a Settings dialog of tabs, group boxes, a paragraph and a password box; and help from pages of Markdown. |

### Applications in processes of their own

On the Dasha Desktop (`dasha desktop`), every application runs in **its own
process**, so an application that crashes, hangs or needs different
libraries cannot bring down the others, or the desktop. The application
code is the same either way: `Application.run()` runs on the desktop that
started the process, or on its own if nothing did.

```
desktop process (dasha)                      application process
---------------------------                 -------------------
terminal, desktop, Z-order                  Application, its windows, dialogs
frames, moving, resizing, minimising        and widgets, and their callbacks
menu bar, status bar, clipboard             draws each window's inside
AppServer, an AppHost per application  <->  ClientManager
              JSON messages over multiprocessing.connection
```

- **Starting.** When `manager.use_processes` is set, as the desktop sets
  it, `manager.start(cls)` (used by the Applications menu and by
  `dasha notepad`) runs `python -P -m dasha.host MODULE:CLASS` with
  the same interpreter. `-P` keeps the desktop's working folder off the
  application's import path, where `-m` would otherwise put it first, so a
  `json.py` planted there is not imported in place of the real one. This
  means that a module an application is started from must be installed or
  on `PYTHONPATH`, while a script is found wherever it is, with its own
  folder on the path. `manager.launch` still runs an application in the
  current process, as a standalone application and the tests do.

  The desktop listens on a named pipe (on Windows) or a Unix socket, through
  `multiprocessing.connection`. The child process learns the address from
  `DASHA_ADDRESS`, and receives the key to connect with, and a launch
  token, on its standard input. It sends `hello` with the range of protocol
  versions it speaks, and the desktop replies with the version they agree
  on, the screen size, the colours and the shortcuts. Each
  connection proves that it knows the key in a thread of its own, within
  `AppServer.handshake_timeout` (10 seconds), so a connection that stalls
  holds up no other. The `hello` also gives the application's name, but
  this is used only in place of a name the desktop guessed (Run... names an
  application after its script or class). An installed or built-in
  application's name is decided by the desktop, so no application can
  impersonate another, and none may call itself Dasha Framework.
- **Loading.** An application has connected well before it has anything to
  show, since its `start` runs after the `welcome`. It becomes the active
  application only when it sends its first message that shows or does
  something (`AppHost.loaded`), which is its menus: its first flush always
  sends them, even with none, ahead of any window. (A `pong`, an `answer` or a
  `bye` does not count, and a ping left waiting by a slow `start` is answered
  first.) Until then (`AppHost.is_loading`), it is not in
  `manager.applications`, so the menu bar, the status bar and the system menu
  all stay as they were, and work, and then all change together. No frame
  shows a Window menu with nothing of the application's. On a desktop with no
  system menu the bar has nothing to show until then, so `compose` paints its
  row in the desktop's pattern (`Desktop.paint_row`).

  An application that ends while loading leaves the bar as it was, and is
  reported as usual. One that connects and then shows nothing for
  `AppServer.load_timeout` (30 seconds) may only be slow, so the user is asked
  whether to end it or to wait, and asked again after each wait. The exit key
  still works throughout, and a loading application is not asked whether it may
  close: it has no work to lose, and may be too busy to answer.
  `AppServer.stop_all` ends it with the others. With `dasha a b`, the
  desktop stays while `b` is loading, even if `a` has ended.
- **Messages** (`dasha.protocol`) are JSON objects with a `type`, never
  pickles, so the two ends do not need to run the same version of Python.
  The application sends each window's frame settings (its title, position
  and buttons, any colours of its own, and whether it is a dialog, is
  waiting, or is a drop-down list), its menus as data, its status text and
  key hints, its footer, and the rows of its interior that have changed, as
  runs of text in one style.
  The desktop sends keys, mouse events, pastes, menu choices, moves and
  resizes, scrolling from the frame's scroll bars, which window is active,
  requests to close, and the screen size.
- **On the desktop**, each application window is a `RemoteWindow`
  (`dasha.remote`). To the manager it is an ordinary window, whose
  interior is drawn from what the application sent. The desktop keeps its
  own keys (`exit`, `next_window`, `close_window` and the other window keys)
  and passes every other key on. An application's menu item cannot use any
  of those keys, or `open_menu`, as its shortcut, because the desktop
  removes it, so no application can stop the user from switching away,
  closing it, or opening the menus.
- **In the application**, `ClientManager` (`dasha.client`) stands in for
  the presentation manager, with the same methods: `execute` waits for a
  dialog's answer, and `pick` drops down a list. The application's menus are
  sent to the desktop as data (including whether each item can be chosen,
  which is sent again whenever it changes), and a choice comes back as the
  item's position in them. The Window menu belongs to the desktop, which
  acts on its windows directly. Application and widget code cannot tell the
  difference.
- **Dialogs block only their own application.** While a dialog is waiting
  for an answer, input to the application's other windows brings the dialog
  forward instead, and typing sent to those windows before the desktop knew
  about the dialog goes to the dialog. Every other application carries on.
  A dialog belongs to no application as a window, but it has an `owner`:
  when the dialog is in front, it makes its owner the active application,
  so that the status bar and menu bar name it.
- **Dialogs wait their turn.** A dialog that arrives while another
  application's dialog (or one of the desktop's own, such as Shutdown) is in
  front and waiting for an answer does not take the keyboard. Instead it
  waits just behind (`manager.must_wait`, `add_waiting`), with the status
  bar saying so (`Notepad │ Worker waiting`), and comes forward once the
  other dialog has been answered. A second dialog from the same application
  (Save as, followed by "Replace it?") opens on top as usual, and clicking a
  waiting dialog brings it forward.
- **Only the active application comes to the front.** The active
  application is the one the user chose most recently. A window opened by
  any other application goes just behind the front window
  (`manager.add_behind`), so that it cannot capture what the user is
  typing. A dialog opened in this way is listed as waiting on the status
  bar, and switching to its application brings it forward. The same applies
  to an application's requests: coming to the front, moving or resizing
  from the keyboard, switching windows and quitting the desktop are allowed
  only for the active application (`AppHost.can_take_front`), or for one
  that the desktop has asked whether it may close, so that it can ask about
  unsaved work.
- **The clipboard is shared, with care.** Text cut or copied in the active
  application goes to the desktop's clipboard. An application receives the
  clipboard, ready to paste, once one of its windows is active, and never
  while it is in the background. An application in the background cannot
  change the clipboard.
- **Shutting down.** Exit sends `may_close` to every application, and each
  one calls its own `can_close()` (Notepad offers to save). Any application
  that answers no stops the shutdown. An application that does not answer
  within `AppServer.close_timeout` (10 seconds), without asking the user
  anything itself, is treated as not responding, and the user is asked
  whether to end it, wait, or stop shutting down. When the desktop ends, it
  tells every application to `quit`, waits up to two seconds, and then ends
  any that are still running.
- **Crashes.** Each application's standard error goes to its own log in
  `~/.dasha/logs/` (`dasha.logs`), never to the terminal. A log that
  an application wrote nothing to is deleted once the application has
  ended, and only the newest `logs.LOG_KEEP` (50) logs are kept. If an
  application's connection drops without a goodbye (or it ends before it
  connects), its windows are removed, and the desktop reports "Notepad
  stopped unexpectedly." together with the last line of its log, clearly
  labelled and read from the end of the log only.
- **What an application cannot do.** Everything an application sends is
  checked before the desktop keeps it, and an application that sends
  something the desktop cannot use is ended, without affecting the others.
  A message can be at most `MAX_MESSAGE` (16 MiB). Sizes and positions are
  kept within reach (`protocol.bounded`), colours must be valid
  (`protocol.decode_colour`), and titles, status lines and hints are kept
  to one line of at most 1,000 characters (`dasha.remote.one_line`).
  An application can have at most 100 windows and 2,000 menu items, with
  submenus at most 16 levels deep. Characters that would not take up exactly
  one cell on the screen (wide or zero-width characters, or characters that
  cannot be written at all) are drawn as `?` (`canvas.shown`), so nothing an
  application draws can reach outside its window. The desktop handles at
  most `AppServer.max_messages` messages at a time, so a flood of messages
  cannot stop it drawing the screen or reading the keyboard. It also never
  waits for an application to read: everything sent to an application goes
  through an outbox, which is sent from a thread of its own.
- **Memory for waiting messages.** Messages an application has sent wait
  in the desktop's inbox (`AppServer.inbox`, `dasha.inbox.Inbox`) until
  the desktop handles them, kept as the bytes that were sent and decoded
  only then, so that what is counted is what is held. At most
  `Inbox.max_bytes_per_application` (64 MiB) may wait for one application:
  beyond that, the thread reading its connection waits for the desktop to
  catch up, the connection's pipe fills, and the application's own sends
  wait, so an application sending in a tight loop is slowed to the
  desktop's pace instead of using up its memory. At most `Inbox.max_bytes`
  (256 MiB) may wait in all; beyond that, every application with something
  already waiting waits, while one with nothing waiting can still send a
  message, so one application's flood never holds up the others. A single
  message larger than the cap is still taken when nothing else of its
  application is waiting. `Inbox.waiting_bytes()` gives the count, for one
  connection or in all.
- **Waiting for messages.** While applications are running, the desktop
  checks for their messages at least every `AppServer.poll_interval`
  (20 ms), because their messages cannot interrupt its wait for terminal
  input. An application process waits on its connection, waking up for its
  widgets' timers.

### Installing applications (`dasha.registry`, `dasha.install`)

The desktop offers every **installed** application. Each installed
application has a manifest file in `~/.dasha/apps/`, named after its
id.

```toml
# ~/.dasha/apps/textstats.toml
name = "Text Stats"            # what the Applications menu says
module = "textstats.app"       # an importable module ...
class = "TextStats"            # ... and the Application class in it
# script = "C:/apps/stats.py"  # or a script (class optional if it has one)
venv = "C:/venvs/textstats"    # optional: run with this venv's Python
group = "Tools"                # optional: an Applications submenu
single_instance = false        # optional
```

Manifests are written and removed from the command line:

```
dasha install-app games/snake.py --name Snake --group Games
dasha install-app textstats.app:TextStats --create-venv --pip nltk==3.8.1
dasha install-app stats.py --venv C:/venvs/textstats --single-instance
dasha uninstall-app textstats --remove-venv
dasha list-apps
```

- **`install-app SOURCE`** takes a script (`path/app.py`, with `--class` if
  the script holds more than one application) or a `module:Class`.
  `--name` sets the name shown in the menu (by default, the class or file
  name), `--id` sets the name used on the command line (by default, derived
  from the name), `--group` puts the application in a submenu, and
  `--single-instance` allows only one copy to run at a time. The command
  checks that the script exists, or that the module can be imported by the
  Python that will run it. Reusing an id that is already installed needs
  `--force`.
- **A virtual environment of its own.** `--venv DIR` runs the application
  with an existing environment's Python. `--create-venv` creates one (in
  `~/.dasha/venvs/<id>`, or at the `--venv` path) using Dasha Framework's own
  Python, or the one given with `--python PATH`. (A build of dasha has no
  Python of its own, so it uses one found on `PATH`.) `--pip REQUIREMENT`,
  which can be repeated, and `-r requirements.txt` install packages into
  it. Two applications can therefore need different versions of the same
  library: each has its own, and neither is installed in Dasha Framework's
  environment.
- **Lending Dasha Framework.** An application in a virtual environment still
  needs Dasha Framework to draw its windows. Unless the environment has Dasha Framework
  installed itself, the desktop lends it a copy: Dasha Framework alone, in
  `~/.dasha/lend/<version>-<hash>/` (where the hash is of its files'
  contents), placed on `PYTHONPATH`. Nothing else from the desktop's
  environment is passed on (`PYTHONPATH` and `PYTHONHOME` are cleared, and
  `VIRTUAL_ENV` is set). If an environment has its own Dasha Framework that has
  no protocol version in common with the desktop's, it is refused when it
  says hello, and the desktop explains why.
- **`uninstall-app ID`** removes the manifest, and with `--remove-venv` also
  removes the environment, if `install-app` created it. **`list-apps`**
  lists every installed application (or says that none are installed).
- A manifest that cannot be read is skipped, and its problems are reported
  before the screen is taken over.

**Starting them.** `dasha` needs to be told what to run, and with nothing
shows its usage and an error (exit code 2), as for any mistake in its
arguments; the key test and `--init-...` need nothing. `dasha desktop`
starts the desktop together with any applications listed in
`~/.dasha/settings.toml`:

```toml
autostart = ["notepad", "textstats"]
```

Applications are named on the command line by id, or by name
(`__main__._find`): the application with that id; failing that, the one
whose id it is in another case (`NOTEPAD`); failing that, the one called
it, ignoring case (`git` for an application `dasha-github` called "Git"). A
name that more than one application has is refused, listing their ids,
and nothing starts. The ids in `autostart` are ids only.

`dasha desktop ID ...` starts the applications named on the desktop too,
after those (one that is in both starts once), and so does `dasha-desktop ID
...`, which is `dasha desktop` under a name of its own (in a PyInstaller
build, a copy of the program named `dasha-desktop`). No application can have
the id `desktop`: `install-app` and Settings... refuse it
(`registry.DESKTOP_ID`).

`dasha ID ...` runs only the applications named, by id or name, just as an
application's script runs it on its own (`Application.run`): there is no
system menu and no `autostart`, the exit key asks to close them
(`Close Notepad?`), and Dasha Framework ends when they do
(`PresentationManager.stand_alone`). Each still runs in its own process. If
one fails to start, so that Dasha Framework ends at once, the reason is printed
on the terminal once the screen has been given back.

The Applications menu lists the installed applications by name, followed
by those with a `group`, in a submenu named after the group. **Run...** in
the system menu starts a script or a `module:Class` once, without
installing it. Usually, naming the script (by typing it, or with
Browse...) is all it takes:

- **Its class.** The dialog reads the script, without ever running it, to
  find the classes it defines (`rundialog.find_classes`), and fills in the
  most likely one: the first class that inherits from `Application`,
  directly or through another class in the script (`likely_class`). The
  Class box is an autocomplete box offering the script's classes, with
  applications first.
- **Its virtual environment.** The dialog fills in a virtual environment
  found next to the script (`find_venv`): the script's own folder, if it has
  a `pyvenv.cfg`, or else a `.venv`, `venv` or `env` folder inside it, as
  long as it contains a Python. Failing that, it looks in the same way one
  folder up, for projects that keep their code in `src` and their virtual
  environment in the project's root.
- **What will run.** The line below the program describes what will run,
  for example "Runs Notepad, with the virtual environment .venv".
- **Options.** The class and the virtual environment are in a collapsible
  Options area, to open when the guess is not what you want. The dialog
  grows to show them, and its Browse... button chooses a `pyvenv.cfg`. A
  field is filled in automatically only while you have not typed in it,
  and it is updated when another script is named.

A script runs as a module of its own (so its `if __name__ == "__main__"`
block does not run), with its folder on `sys.path` so that it can import the
modules beside it. A script inside a package (its folder has an
`__init__.py`, as `pgh/app.py` does) is imported as part of that package
instead, as `pgh.app`, with the folder above the outermost package on
`sys.path`, so that `from pgh.git import ...` works. This is the same as running
`python -m dasha.host path/app.py[:Class]`.

An application that cannot start at all (a virtual environment without a
Python, for example) is reported as "Cannot start ...". One that fails while
starting is reported as stopped, with the last line of its log, wrapped to
fit.

### Hangs, crashes and shutting down (`dasha.processes`)

The desktop never waits for an application, and an application never
outlives its desktop.

- **Never blocked.** Messages to an application are placed in its outbox,
  which a thread of its own sends, so an application that has stopped
  reading blocks only that thread. Messages from applications arrive on
  reader threads.
- **Not responding.** An application that has been silent for
  `AppServer.ping_interval` (1 second) is sent a `ping`, which its
  `ClientManager` answers with a `pong` whatever it is doing, even while it
  shows a dialog; any message counts as an answer. An application that
  leaves a ping unanswered for `hang_timeout` (5 seconds) is not
  responding. Its windows' titles then say "(Not responding)" and their
  interiors stay as they were, but they can still be moved, resized,
  minimised and stacked. The mark disappears as soon as the application
  answers again. An application that is waiting for the user (with a "Save
  changes?" dialog, for example) counts as responding.
- **End now.** Closing a window of an application that is not responding
  (with its `[■]` button, Alt+F4 or the Window menu) cannot ask the
  application, so the desktop asks the user instead: **End now** ends the
  application (and anything it started), and **Wait** gives it more time.
- **Shutting down** sends `may_close` to every application that has
  finished loading, and waits for their answers, however long the user
  takes over them. If one is not
  responding, the desktop asks whether to **End now**, **Wait** (asking
  again after another `hang_timeout`), or **Cancel** the shutdown.
- **Process trees.** Each application is started as a `ProcessTree`. On
  Windows, it starts suspended, joins a job object of its own (set to end
  everything in it when the job is closed), and only then runs, so nothing
  it starts can escape. There, a virtual environment's `python.exe` is a
  launcher that starts the real Python as its child, and ending the job
  ends both. On other platforms, each application leads a process group of
  its own. Ending an application ends its whole tree, and waits until
  nothing in it is still running.
- **When the desktop dies.** `run` ends its applications however it is
  left: normally, through an exception, or through SIGTERM or SIGHUP (when
  the terminal closes), which end it as Exit would, without asking, and
  restore the terminal. If the desktop is killed outright, Windows closes
  its jobs, which ends their applications. On other platforms, each
  application watches its desktop (`watch_parent`, given the desktop's
  process id in `DASHA_DESKTOP_PID`) and ends itself, hung or not, once
  that process has gone. It watches the desktop's own process rather than
  its parent, because in a one-file build of dasha there is a launcher
  process between them.
- **Starting.** An application that has not connected within
  `start_timeout` (30 seconds) is ended and reported. One that has connected
  but shows nothing is asked about instead (see "Loading" above).
- **Protocol version.** `PROTOCOL_VERSION` is 1, the version of the first
  release. It is increased whenever a message changes in a way the other end
  would notice. `MINIMUM_VERSION` is the oldest version still understood,
  and is raised only when support for an old version is dropped. An
  application's `hello` gives the range it speaks (`"versions": [oldest,
  newest]`), and the desktop chooses the highest version both ends speak
  (`agree_version`), names it in `welcome`, and refuses only an application
  with which it has none in common. Each end keeps the agreed version
  (`AppHost.version`, `ClientManager.version`), so that a later release can
  speak to an older one: it adds what the older version leaves out of a
  message, and leaves out what the older version would not understand.

Window contents still travel through the connection rather than through
shared memory: only changed rows are sent, and drawing has kept up well
without it.

## Help (`dasha.help`)

An application offers help by saying where its pages are, and a widget or a
window by naming the page about it:

```python
class MyApp(Application):
    help_folder = Path(__file__).parent / "help"

    def start(self) -> None:
        window = Window(
            title="Details",
            rect=Rect(row=2, column=2, height=12, width=50),
            closable=True,
        )
        box = window.add(widget=TextBox(row=1, column=2, width=30))
        box.help = "user_name"      # help/user_name.md
        window.help = "details"     # for its other widgets
        self.open(window=window)
```

Help is off by default. An application with no `help_folder`, or with no
pages in it, has no help (`has_help()`), and F1 does nothing.

F1 (`help` among the [shortcuts](shortcuts.md)) goes to the first of these
that has a topic: the focused widget, the containers it is in (a tab page,
say, with `TabPage.help`, or a group box), and its window. With none, it goes
to the default page, `index.md`. A topic is the name of a page relative to
the folder, without `.md`, and can name a heading too
(`"guide/editing#saving"`). A topic with no page shows a page that says so,
with a link to the index, so that a mistake shows and the reader is not
stranded. `Application.show_help()` does just what F1 does, so that it can be
given to a menu item as it is, and `show_help(topic="topic")` goes to a topic.

### The help window

`HelpWindow` is an ordinary window of the application, cyan to show that it
is for reading rather than for filling in. Each application has one at most.
It stays open beside the application's other windows, and F1 brings it
forward and goes to the new topic, adding to its history.

In a dialog, nothing else can respond until the dialog is answered, so help
opens in front of it instead, as a dialog itself (`HelpDialog`, in the same
colours). Closing it goes back to the dialog as it was. A drop-down list has
no help.

Both hold a `HelpView`, which holds the top row (Back, Forward, Index and
Search), the page, its scroll bar and the history. Back and Forward come back
to the same place on a page, with the same link highlighted.

Tab and Shift+Tab move between links, and Enter follows one. A link outside
the help (a web address, say) is not opened, because the program may well be
running on another computer: its address shows on the status bar, and Enter
copies it to the clipboard. Links are relative to the page they are on,
unless they start with `/`, and anything that leads out of the folder is
treated as not being there.

Search (Ctrl+F) asks for words, and shows a page of links to the topics that
have all of them: first those with one of the words in their title, and then
those with the most matches. Each link goes to the heading above the first
match. As the results are a page of Markdown, written by `HelpBook` and shown
like any other, they have their place in the history.

### Where it runs

Help runs in the application's own process, as its other windows do, so the
protocol hardly comes into it. F1 reaches a hosted application as any key
does (it is not in `DESKTOP_KEYS`, so a widget that uses it comes first, such
as a terminal), and the window's cyan frame crosses the connection as any
window's own colours do (`colours_of`). The application reads its own files,
and the desktop only ever sees rows of text.

The one addition is the `help` message, which the desktop sends to the active
application when it has no window to send the key to. An application that
does not know it ignores it, as it does any message it does not know, so
`PROTOCOL_VERSION` did not change.

The desktop has help of its own, in the package's `helppages` folder, which
`PresentationManager.use_own_help` turns on. A `PresentationManager` has none
by default, nor does the desktop of an application running on its own. It is
for when no application is active, and for the desktop's own dialogs
(Settings... has a topic for each page). Otherwise, F1 belongs to the active
application, so one with no help has none, whatever the desktop has.

### Pages (`dasha.markdown`)

`parse` turns Markdown into blocks, and `lay_out` wraps them to a width, as a
`Document` of lines, each of them pieces of text of one kind (`BOLD`, `LINK`
and so on). `HelpView` chooses a style for each kind, so a change of theme
needs no new layout, and it lays the page out again only when the width
changes. The module draws nothing, and knows nothing of windows.

A text screen cannot do everything that Markdown can:

| In a page | On the screen |
| --- | --- |
| `# Heading` | `═══ Heading ═══`, bold |
| `## Heading` | Bold, with a line under it |
| `### Heading` | `── Heading`, bold |
| `#### Heading`, and those below | Bold |
| `**bold**` | `help.bold` |
| `*italics*` | `help.emphasis`, underlined by default |
| `` `code` `` and fenced blocks | `help.code` |
| Lists | `•`, then `○`, then `-`, or numbers, nested as written |
| `> quotes` | A line down the left |
| `---` | A line across the page |
| Tables | Box characters, with text wrapped in each cell to fit. A table with too many columns is written out as `Heading: value` lines. |
| `[text](other.md#heading)` | A link, in `help.link` and `help.link.focused` |
| `![description](picture.png)` | `[Image: description]` |
| `<b>HTML</b>` | The tags are removed, leaving the text. `<br>` breaks the line. |
| Dashes, curly quotes and ellipses | Their plain equivalents, which code page 437 has |

Pages are read as text from anywhere. Nothing in one raises an error, and
what is not understood shows as it was written. What reaches the screen goes
through the canvas, as all text does, so control characters in a page cannot
reach the terminal.

## Presentation manager (`dasha.manager`)

`PresentationManager` owns the desktop, the menu bar (see
[Menus](#menus-dashamenu)) and a stack of windows in **Z-order**, from
back to front. The menu bar takes the top row and the status bar the bottom
row. Windows live in the work area between them (`workspace`) and pass
underneath both bars. The front window is the active one: it is painted
last, so it covers the others, and it receives keyboard input. Clicking a
window brings it to the front, and dragging its top row (the title bar)
moves it.

| Method | Effect |
| --- | --- |
| `add` / `remove` | Put a window on the desktop (in front) or take it off |
| `bring_to_front` / `send_to_back` | Restack one window |
| `activate_next` / `activate_previous` | Cycle the windows (the front one goes to the back, or the reverse) |
| `window_at(row, column)` | The front-most window at a screen position, for mouse clicks |
| `compose(canvas)` | Paint the desktop and all the windows |
| `handle_key` / `handle_mouse` | React to one key or mouse event; override to add behaviour |
| `handle_resize(columns, lines)` | React to a new screen size (see below) |
| `bar_menus()` | The menus on the bar: `system_menu`, then the active application's `menus` and its Window menu |
| `status()` | The status bar text for whatever has focus (see below) |
| `run(terminal)` | The main loop: compose, render the changes, read input, repeat |

These are the default keys, and users can remap every one of them in
`~/.dasha/shortcuts.json` (see [Keyboard shortcuts](shortcuts.md)).

| Input | Action |
| --- | --- |
| Left click on a window | Bring it to the front |
| Drag a window's top row | Move the window |
| Drag a resizable window's `─┘` corner | Resize the window |
| Click `[↓]` / `[↑]` / `[↕]` on the active window | Minimise / maximise / restore |
| Double-click a title bar | Maximise, or restore (maximisable windows) |
| Double-click `≡` on the menu bar | Shut down, after the Shutdown dialog, as Exit does |
| F5 | Maximise or restore the active window |
| F6 | Next window |
| Shift+F6 | Previous window |
| F10, Alt+letter | Open the menus (see below) |
| Ctrl+Q | Exit, after an OK / Cancel dialog |
| Esc | Close an open menu, or cancel a dialog |
| Alt+F4, Alt+F3 | Close the active window |
| Alt+F7 / Alt+F8 | Move / resize the active window with the arrow keys |
| Tab, Shift+Tab | Move the focus between a window's widgets (with two or more) |
| Enter, Space | Press the focused or default button |

### Failing softly (`dasha.recovery`)

A bug in the desktop's own code (a menu action, a dialog, a widget, a
timer) need not end the desktop, and with it every application and their
unsaved work. With `survive_errors` on, as the command line and
`Application.run` turn it on in the real terminal, each step of the loop in
`run` and `execute` is guarded: handling one event, running the timers,
taking in applications' messages, drawing a frame, and the start-up
callbacks. When a step raises an unexpected exception:

1. Its traceback is written to `~/.dasha/logs/desktop-<time>.log`
   (`Recovery.record`), one log for each run, beside the applications'
   logs and pruned with them. An application running on its own
   (`dasha notepad`, or `Application.run`) writes `notepad-<time>.log`
   instead, where its system keeps programs' logs, in a folder named after
   it (`logs.app_log_folder`):

   | System | Notepad's logs |
   | --- | --- |
   | Windows | `%LOCALAPPDATA%\Notepad\logs` |
   | macOS | `~/Library/Logs/Notepad` |
   | Linux and others | `$XDG_STATE_HOME/notepad/logs` (`~/.local/state/notepad/logs` if it is not set) |

   An application can choose a folder of its own with
   `Application.log_folder`.
2. Whatever was under way is put aside: an open menu closed, a drag or a
   keyboard move or resize ended, an animation dropped, and the whole screen
   drawn afresh.
3. The user is told, in a dialog, that something went wrong, that their
   applications are still running, and where the log is: every time for a
   failure in handling their input, and at most once a minute
   (`Recovery.quiet`) for one that happened by itself, so that a bug that
   comes and goes cannot bury the screen in dialogs.
4. The desktop carries on.

If one kind of step (drawing, the timers, applications' messages, the
error dialog itself) fails `Recovery.limit` (5) times in a row, with no
success in between, carrying on is no use, and the desktop gives up: it
shuts down as Exit would, without asking. A step that fails only now and
then never makes it give up, and nor do failures in handling the user's
input, each of which they are told of. Once the screen has been given back,
the command line says how often something went wrong and where the log is,
and exits with 1 if it gave up.

Never caught: `KeyboardInterrupt` and `SystemExit` (ending on purpose, as
SIGTERM does), and `TerminalFailed`, the terminal itself failing to be read
or written (`GuardedTerminal` raises it in place of the `OSError`), after
which there is no screen to recover on. `survive_errors` is off by
default, so that code and tests using a `PresentationManager` fail at once
on a bug.

## Menus (`dasha.menu`)

The **menu bar** runs along the top row. On the desktop, it starts with the
**system menu**, shown as a burger icon (`≡`, `\N{IDENTICAL TO}`); an
application running on its own (`Application.run`, or `dasha APP`) has
no system menu. The active application's menus and its Window menu come
next, so the bar changes as the user moves between applications' windows.

The system menu holds the running applications to switch between, then
About, Applications (to start one), Run... (to run a script once),
Settings... (see [Settings](#settings-dashasettings)), Themes, Animations
(see [Animations](#animations)), Command prompt and, after a separator,
Shutdown; on the desktop, Help comes just before Settings.... Minimised
windows that belong
to no application are listed above all of these. A menu's `on_open` is called just before the menu opens, to
bring its items up to date; Themes uses it to list the theme files present
at that moment. The system menu is an ordinary `Menu`, stored in
`PresentationManager.system_menu`, so more items can be added to it:

```python
manager.system_menu.items.insert(0, MenuItem(label="&Help", action=show_help))
```

An application's menus are a plain list, `Application.menus`, and so are
those of a window that belongs to no application, `Window.menus`:

```python
from dasha.menu import Menu, MenuItem, separator

editor.menus = [
    Menu(
        title="&File",
        items=[
            MenuItem(label="&Open...", action=open_file, shortcut="F3"),
            MenuItem(label="&Save", action=save_file, shortcut="F2"),
            separator(),
            MenuItem(label="&Close", action=lambda: manager.remove(window=editor)),
        ],
    ),
]
```

- **Actions.** A `MenuItem` runs its `action` when it is chosen. An item
  without an action is greyed out, including its shortcut, and can be
  neither chosen nor highlighted: the arrow keys skip it, and hovering over
  it leaves the highlight where it was. A menu with nothing enabled opens
  with nothing highlighted.
- **Shortcuts.** `shortcut` is shown on the right, written in the style of
  `pretty_key` (`"Ctrl+Q"`, `"Alt+F3"`), usually taken from
  `shortcuts.hint(action)`. Pressing that key chooses the item, whether or
  not its menu is open, as long as the item is enabled. Plain characters
  never count as shortcuts, because they are used for typing and for
  choosing items by their letters.
- **Mnemonics.** `&` marks a mnemonic letter, which is drawn in a highlight
  colour. Write `&&` for a literal ampersand. A letter belongs to one item
  of a menu (and to one title on the bar): if a later item marks the same
  letter, in either case, the first keeps it and the later one is drawn
  and treated as having no letter, so pressing the letter never depends on
  which item is greyed out. `Menu.mnemonics()` gives each item's letter as
  it works. `Menu.check_mnemonics()` and `MenuBar.check_mnemonics()` raise
  `DuplicateMnemonicError` (a `ValueError`) instead, so a test can catch
  the mistake; Dasha Framework's tests check its own menus, and the
  example applications', this way.

| Input | Menu closed | Menu open |
| --- | --- | --- |
| F10 | Open the first menu (the system menu, on the desktop) | Close every open menu |
| Alt+letter | Open the menu with that mnemonic | Switch to that menu |
| Click a title | Open that menu | Close it, or switch menus |
| Right | | Open the highlighted item's submenu; otherwise the next menu |
| Left | | Close the innermost submenu; from the drop-down, the previous menu |
| Up / Down | | Move the highlight (separators and disabled items are skipped) |
| Enter, or the item's letter | | Choose the item, or open its submenu |
| An item's shortcut (Alt+F4 for Close) | Choose that item | Choose that item |
| Another menu's letter (no enabled item in an open menu uses it) | | Open that menu |
| Click an item | | Choose it, or open its submenu |
| Move the pointer over an enabled item | | Highlight it, and open its submenu |
| Move the pointer over another title | | Open that menu |
| Press a title, drag down, release on an item | | Choose it |
| Esc | | Close the innermost submenu, or the drop-down |
| A click outside every open menu | | Close them all |

**Submenus.** An item can open a menu of its own instead of running an
action: `MenuItem(label="&Recent", submenu=Menu(title="Recent", items=[...]))`.
Such an item is drawn with `►` (code page 437 glyph 16) on its right, and submenus can
have submenus of their own. A submenu opens beside its item, with its first
item level with it. It opens to the right of its parent menu if there is
room, otherwise to the left, and if there is room on neither side, as close
as it can while staying on the screen. It is moved up if it would run off
the bottom. Each open menu casts a shadow on the menus beneath it, but,
like every shadow, never on the status bar. `MenuBar.open_menus` lists the
open menus, starting with the drop-down, and `level_rects` gives where each
one is drawn.

**Letters with submenus.** When a letter is pressed, it is looked for first
in the innermost open submenu, then in each menu outside that in turn, and
finally among the titles on the menu bar. The first enabled item (or title)
with that mnemonic is chosen, and if none has it, the letter is ignored.
Submenus that are not open do not count. So with Edit > Insert > Box open in
Notepad, D chooses Box's Double line; with only Insert open, it chooses Date
and time; and with only Edit open, Delete line. Shortcut keys (such as
Ctrl+D) work for items in submenus too, whether or not any menu is open.

While a menu is open, it takes all input, so keys and clicks do not reach
the windows underneath. The drop-down has a blank column outside each side
of its frame (`MenuBar.frame_padding`). The open drop-down casts the same
drop shadow as a window (`MenuBar.shadow_style`, `None` for none). The
shadow is painted before the status bar and the drop-down after it, so that
even on a short screen no shadow falls on the status bar. The menu colours
(black on white, with green for the selection) are class attributes of
`MenuBar`. Windows cannot be dragged under the menu bar, and resizing the
terminal moves any window whose title bar would end up hidden beneath it.

## Status bar (`dasha.statusbar`)

The status bar runs along the bottom row and shows one line of help about
whatever has the focus:

- **While a menu is open:** the highlighted item's `status`. Moving the
  mouse over an item highlights it, so hovering over Open can show "Opens
  a file".
- **Otherwise:** the `status` of the active window's focused widget, or, if
  it has none, the active window's own.
- **With no windows:** nothing.

At its left, the bar always shows the active application's name followed by
a divider (`Notepad │ `; a second Notepad is shown as `Notepad (2)`), or
`Dasha Desktop` on the desktop when no application is active
(`manager.status_owner`, `no_application`). An application running on its
own (`dasha notepad`, or `Application.run`) shows no name and no divider
until it is active, not even while it loads. When space is short, the
status text gives way to the name, as it does to the key hints.

**Nothing on screen names Dasha Framework for an application running on its own**
(`PresentationManager.stand_alone`), so that it can be given to people who
have never heard of Dasha Framework. Its exit dialog asks to close the application,
and what the desktop would otherwise say in its own name (the command
prompt's "is still running", the dialog after something has gone wrong)
names the application instead (`program_name`, `Dasha Desktop` on the desktop),
and the log that dialog points to is in the system's folder for the
application's logs, not under `~/.dasha` (see above).

At its right, the bar first shows the key that opens the menu bar
(`F10 Menu`, or whatever key `open_menu` is bound to), whenever that key
would open it. That includes when there is no window or application, but
not while a dialog is open, while every menu is inert, or if `open_menu` has
no keys. Because it comes first, it is the last hint to be dropped. After
it, the bar lists the keys that do something particular to the focused
widget, such as `Up/Down Step` for a spin box, with the key names in the
`status.keys` colours. A widget provides these through
`key_help(shortcuts)`, as (key, description) pairs built from the
shortcuts in effect, so a remapped key is shown as it is currently bound.

Keys that only edit text (cut, copy, paste, select all, undo, redo, clear,
delete line, and moving and selecting) work in every text widget and can be
remapped, but are not listed. Only these widgets provide hints:

| Widget | Hints |
| --- | --- |
| `TextArea` | `Ctrl+Tab Next`, if another widget can take the focus (Tab types a tab) |
| `SpinBox` | `Up/Down Step` |

Hints that do not fit are dropped from the end, and the status text is
shortened to make room for the rest. No hints are shown while a menu is open
or while a window is being moved from the keyboard.

**Clicking a hint presses its key.** A left click anywhere on a hint, on
its key or its description, does exactly what pressing the key would: a
click on `F10 Menu` opens the menu bar, and a click on `Ctrl+Tab Next`
moves the focus. The key is handled just like a typed one
(`manager.hint_key_at`, which turns the hint back into a key with
`shortcuts.key_from_pretty`), so it reaches whatever would have received
it: the menu bar, the focused widget, a dialog waiting for an answer, or an
application running in its own process.

```python
MenuItem(label="&Open...", action=open_file, shortcut="F3", status="Opens a file")
Window(title="Editor", rect=rect, status="Editing notes.txt")
```

Status text is always **optional**. `MenuItem.status` and `Window.status`
default to `""`. `status_text(source)` reads a `status` attribute
defensively: a missing attribute, `None`, or a value that is not text all
count as nothing to show. A missing status therefore never raises an error,
and the bar is simply left blank. Future widgets need only a `status`
attribute to take part. Only the first line of the text is shown, cut to the
width of the screen.

Windows are painted before the bars, so they pass underneath them, and
their title bars cannot be dragged under either bar. Clicking a bar never
reaches a window hidden beneath it. An open drop-down is painted last of
all, so on a short screen it covers the status bar. The bar's colours are
the class attribute `StatusBar.style`.

## Input (`dasha.events`)

`InputDecoder` turns raw terminal input into events. Keys become names such
as `"a"`, `"enter"`, `"up"`, `"f6"`, `"shift+tab"`, `"ctrl+q"` and
`"alt+x"`, and mouse activity becomes a `MouseEvent`. Because Windows input
is switched to VT mode, the same decoder serves Windows, POSIX and SSH.

Input can arrive in pieces, especially over SSH, so an escape sequence may
be split between two reads. The decoder holds back an unfinished sequence
until the rest arrives. A lone ESC is ambiguous, because it is both the
Escape key and the start of every sequence. So when input stops just after
an ESC, the manager waits `escape_timeout` (100 ms, or `escape_timeout` in
`settings.toml`, in milliseconds, which Settings... changes) for more, and
then treats it as the Escape key. Over a slow or jittery connection, where
an arrow key's sequence can arrive later than that and be taken as Escape
followed by typing, raise it.

A bracketed paste is held back until its end marker arrives. Its pieces are
set aside as they come, and each read is searched for the marker once, so
decoding a paste takes time in proportion to its length (16 MB in about
0.02 s). On Windows, characters outside the Basic Multilingual Plane arrive
as two UTF-16 halves; a first half at the end of one console read is kept
back and joined to the second half in the next (`records_to_text`).

Most terminals send Alt with a function key as a single sequence with a
modifier (`ESC [ 1 ; 3 R` for Alt+F3), but PuTTY, rxvt and the Linux console
send ESC followed by the key's own sequence (`ESC ESC O R`) instead. Both
decode to `"alt+f3"`. Only function keys are read in this way: Escape and an
arrow key pressed quickly can arrive together over SSH, so ESC before any
other sequence is still read as Escape followed by that key.

### Key releases

Terminals report keys being pressed, but not released, so Dasha Framework usually
cannot tell how long a key is held down. The Windows console is an
exception, because its input records include key releases. The Windows
backend turns the release of Space into `ESC [ 32 ; 1 : 3 u`
(`ansi.SPACE_RELEASED`), which is how the kitty keyboard protocol writes a
release, and the decoder reads that sequence (from any terminal that sends
it) as a `KeyReleaseEvent`, in this case `KeyReleaseEvent(key=" ")`. Other
releases are not passed on.

`Terminal.can_report_key_releases` says whether releases arrive (true on
Windows, and false elsewhere and over SSH). When `run` starts, the
presentation manager copies this to `Widget.key_releases`. It passes each
`KeyReleaseEvent` to the active window (or to the dialog being answered),
which offers it to each of its widgets through
`handle_key_release(key, focused)`. A button uses this to stay pressed in
while Space is held down. `dasha --key-test` shows releases as
`release  space`, so it reveals whether a terminal sends them.

### Pasting through the terminal

Without special support, text pasted through the terminal (with its own
Ctrl+V, right-click or middle-click) cannot be told apart from fast typing:
each character arrives as a key, so a text box would check the characters
one at a time, and a pasted Ctrl+Q or line break would act as a key press.
So Dasha Framework turns on **bracketed paste** (`ESC[?2004h`), and the terminal
wraps each paste in `ESC[200~` ... `ESC[201~`. Like mouse reports, these
markers come from the terminal on the user's own machine, so they work over
SSH and through tmux.

The decoder turns everything between the markers into a single
`PasteEvent(text)`, exactly as pasted: line breaks (usually `"\r"`) and
other control characters in it are text, never keys or shortcuts. A large
paste may arrive over many reads, and the markers themselves may be split
between reads, so the decoder holds the paste back until `ESC[201~` arrives
(`InputDecoder.is_pasting` says whether a paste is under way). While it
waits, `read_events` allows up to `paste_timeout` (`PASTE_TIMEOUT`, 0.5
seconds) for each read. If the paste stops arriving, what has arrived so far
is delivered as one paste, and the remainder, up to the end marker, as
another.

The presentation manager passes a `PasteEvent` to `handle_paste(text)`,
which offers it to the active window (`Window.handle_paste`), which in turn
offers it to the focused widget (`Widget.handle_paste`, which ignores it
unless overridden). A paste is ignored while a menu is open, and goes to
the dialog while a modal dialog is open. `TextBox` accepts all of it or
none of it (see [Clipboard](#clipboard-dashaclipboard)).
`dasha --key-test` shows a paste as its length and the start of its
text. A terminal without bracketed paste ignores the request, and pasted
text arrives as typing.

### Mouse

Mouse support works the same way locally and over SSH, because the reports
come from the terminal program on the user's own machine, not from the
remote computer. Dasha Framework asks the terminal for these modes:

| Mode | Meaning |
| --- | --- |
| `ESC[?1000h` | Report button presses and releases |
| `ESC[?1002h` | Also report movement while a button is held (for dragging) |
| `ESC[?1003h` | Also report movement with no button held (for hovering over menus) |
| `ESC[?1006h` | Use the SGR format: decimal coordinates, no 223-column limit, and presses and releases told apart |

A report looks like `ESC [ < button ; column ; row M`, where `M` means a
press and `m` a release, and positions are counted from 1. A `MouseEvent`
has these attributes:

- **`action`:** `"press"`, `"release"`, `"drag"`, `"move"` or `"scroll"`.
- **`button`:** `"left"`, `"middle"`, `"right"`, `"none"`, or the scroll
  direction.
- **`row` and `column`:** counted from 0.
- **`shift`, `alt` and `ctrl`:** whether that modifier was held.
- **`clicks`:** for a left press, 2 for the second press of a double-click,
  3 for a triple-click, and so on. Terminals do not report this, so the
  presentation manager counts it: a press counts as another click if it is
  in the same cell as the previous press, within
  `PresentationManager.double_click_time` seconds (0.4).

Some further points:

- **The mouse is optional.** A terminal that cannot report the mouse
  ignores the request, and everything still works from the keyboard.
- **Selecting text.** While reporting is on, most terminals (xterm, Windows
  Terminal, iTerm2, GNOME Terminal) still let the user select text by
  holding Shift while dragging.
- **tmux and screen** pass mouse reports through to Dasha Framework.
- **Showing the mouse.** Some terminals (a Linux console without a mouse
  pointer, or a terminal over some remote tools) report the mouse but show
  no pointer. With `PresentationManager.show_mouse` on, the cell under the
  mouse is drawn inverted, after everything else (`_paint_mouse`, at the end
  of `compose`). The position comes from the last mouse report, noted
  before any event goes anywhere (`_notice`), and the `show_mouse` key
  (`` Alt+` `` by default) is taken there too, so it works wherever the focus is,
  dialogs included, except in a dialog that `takes_every_key` (Add key...).
  It is off by default; `-m` (`--show-mouse`), `show_mouse = true` in
  `settings.toml`, the key and Settings... turn it on, and each of them is
  remembered for next time, as `-d` (`--colour-depth`) is.

## Moving windows and resizing the terminal

**Dragging.** Pressing the left button on a window's top row
(`Window.title_bar`) brings the window to the front and starts a drag. While
the button is held, the window follows the pointer, keeping the point where
it was grabbed under the pointer. A window can be dragged partly off the
screen, and stays where it is left. While it is being dragged, or resized
by its grip, its frame is drawn with single lines
(`Window.adjusting_border`) in the `window.frame.adjusting` colours (bright
green), just as when it is moved or resized from the keyboard.
`Window.move_to(row, column)` moves a window from code.

**Resizing the terminal.** `Terminal.read` returns as soon as the terminal
is resized, even if there is no input, so the screen is redrawn at the new
size straight away:

- **POSIX:** the `SIGWINCH` signal ends the wait.
- **Windows:** the console's resize record ends the wait.

Before the first frame, and before each frame at a new size,
`PresentationManager.handle_resize` makes sure that every window can still
be reached:

- **Partly visible:** a window that is still at least partly on screen is
  left where it is, unless its title bar is hidden under the menu bar, in
  which case it is moved down to just below it.
- **Completely off screen:** a window that the resize has pushed entirely
  off the screen is pulled back to the nearest edge. Its title bar ends up
  on screen, between the menu bar and the status bar, with `rescue_margin`
  columns showing (4 by default), so that the user can drag it back into
  view.
