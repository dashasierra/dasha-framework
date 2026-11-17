# Colours

Every colour Dasha Framework uses can be changed, even while it is running.
Dasha Framework can also run without any colours, for terminals that do not
support colour escape codes.

## Themes

A theme sets the colours of every part of the screen. To choose one, open
the system menu (`≡`) and choose **Themes**. The whole screen changes at
once, including the windows of every application, with nothing to restart.
Dasha Framework remembers your choice and starts with it next time.

- **Built-in themes:** Default (blue windows and grey dialogs), Dark (light
  text on black windows, with dark grey dialogs) and Monochrome (no
  colours; see below). These are always available.
- **Theme files:** each file in `~/.dasha/themes/` is a theme, named
  after the file, so `ocean.json` is the theme `ocean`. The menu reads the
  folder each time it opens, so a file added or changed while Dasha Framework is
  running can be chosen straight away. A file with the same name as a
  built-in theme (such as `dark.json`) is ignored, so give yours a name of
  its own. To create one with every colour written out, ready to edit, run:

  ```bash
  dasha --init-theme ocean
  ```

  A theme file has the same format as the colours file (see
  [below](#the-colours-file)), so it can start from any built-in theme,
  including `"base": "dark"`, and change only the colours it needs to.
- **The colours file:** if you have one (`~/.dasha/colours.json`), the
  menu offers it too, as **Colours file**.

Dasha Framework records the theme you chose last as a line such as
`theme = "ocean"` in `~/.dasha/settings.toml`. Only that line is
changed, so anything else in the file stays as you wrote it. Choosing
**Colours file** removes the line, so the colours file is used from then on.

When Dasha Framework starts, it picks its colours from the first of these that
applies:

1. the `--monochrome` option;
2. a colours file named with `--colours FILE`;
3. the theme you chose last;
4. the colours file, `~/.dasha/colours.json`;
5. the Monochrome theme, if `NO_COLOR` is set, or otherwise the Default
   theme.

An application can also change the theme, by name or by the path of a theme
file, with `self.set_theme("dark")`, just as the menu does. This is useful
for an application running on its own, which has no system menu. On the
desktop, only the application the user is working in can change the theme.

## Changing colours in Settings...

To change colours without editing a file, open the system menu and choose
**Settings...**. Its **Appearance** page shows the theme you are using, and
a list of every part of the screen (the roles described below). Choose a
role to see what it colours, then change its foreground and background, and
whether it is bold, underlined or in reverse video. Shadows can also be
turned off, and the button shadow's shape chosen. Every change shows on the
screen at once.

The last colour in the foreground and background boxes, **Custom...**, asks
for an RGB colour: type it as `#rrggbb`, or set its red, green and blue
from 0 to 255, and the sample shows it. The **Desktop** page chooses how
colours are drawn (see [RGB colours](#rgb-colours)).

- **OK** or **Apply** keeps the colours. A theme chosen unchanged is
  remembered by name, as the Themes menu does. Changed colours are saved to
  the colours file (`~/.dasha/colours.json`, or the file named with
  `--colours`), which the desktop then starts with.
- **Cancel** puts back the colours you had before.
- **Save as...** saves the colours as a theme file. Saved in
  `~/.dasha/themes/`, it becomes a theme of its own, offered by the
  Themes menu.
- **Load...** reads a theme file, from anywhere, for you to use or change.

## Monochrome mode

The Monochrome theme uses no colours at all, only bold, underline and
reverse video, which every VT100-compatible terminal supports. The active
window, menu selections, focused buttons and mnemonic letters all remain
easy to tell apart. Dasha Framework uses this theme when any of the following is
true:

- it is run with `--monochrome`;
- the colours file says `"base": "monochrome"`;
- the `NO_COLOR` environment variable is set to any value
  ([no-color.org](https://no-color.org)), and the colours file does not
  name a base theme of its own;
- the terminal has no colours (`TERM` is `dumb`, or a VT terminal such as
  `vt100`, and `COLORTERM` is not set).

`--monochrome` always takes priority, and gives the Monochrome theme
exactly as the Themes menu does: the colours file's changes are left out,
since they may add colours. A base theme named in the colours file takes
priority over `NO_COLOR`, as that convention requires.

An application running on its own, without the desktop, chooses its theme in
the same way, from the same settings, so choosing Monochrome from the Themes
menu covers it too. One that the desktop started has the desktop's theme.

**No colours reach the screen under a theme that has none**, whatever an
application asks for. Dasha Framework leaves them out as it draws, so this holds
for every application, for colours that a program in a terminal window sends,
and for styles written with colours in the code. Bold, underline and reverse
remain, and anything with a background is drawn reversed, so that a highlight
still shows. A theme that the user has added colours to has them, as asked.
On a terminal with no colours, none are drawn under any theme.

## The colours file

When it starts, Dasha Framework reads `~/.dasha/colours.json` if the file
exists. `~` is your home folder, which is `C:\Users\<you>` on Windows. To
use a different file, run Dasha Framework with `--colours FILE`. To create a file
with every colour written out, ready to edit, run:

```bash
dasha --init-colours
```

The file chooses a base theme (`"default"`, `"dark"` or `"monochrome"`) and
changes whichever roles you want:

```json
{
    "base": "default",
    "colours": {
        "desktop": {"foreground": "yellow"},
        "window.body": {"foreground": "bright white", "background": "black"},
        "window.shadow": null
    }
}
```

- **Partial changes.** The settings for a role change only the parts they
  name, and everything else comes from the base theme. For example,
  `{"foreground": "yellow"}` changes the foreground and keeps the background.
- **Settings.** `foreground` and `background`, as well as `bold`,
  `underline` and `reverse` (each `true` or `false`).
- **Colours.**
  - Names: `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`,
    `white`, and `bright black` through to `bright white`. `grey` is the
    same as `bright black`.
  - A number from 0 to 255. Numbers 0 to 15 are the named colours above,
    and 16 to 255 use the 256-colour palette.
  - An RGB colour, `"#rrggbb"` (such as `"#ff8800"`), or `"#rgb"` for
    short (`"#f80"`). See [RGB colours](#rgb-colours).
  - `"default"`, for the terminal's own colour.
- **Shadows.** `null` turns a shadow off (`window.shadow`, `menu.shadow`).

### RGB colours

How colours are drawn depends on what the terminal can show:

| Colour depth | Settings... | RGB colours | Colours 16 to 255 |
| --- | --- | --- | --- |
| `24bit` | 24-bit colour | As they are | As they are |
| `256` | 256 colours | The nearest of the 256-colour palette | As they are |
| `16` | 16 colours (CGA) | The nearest of the 16 standard colours | The nearest of the 16 standard colours |

Colours 0 to 15 are drawn as they are at every depth. The nearest of the 16
is measured against the colours the CGA showed (`#aa0000` for red, `#aa5500`
for yellow, which the CGA showed as brown, `#555555` for bright black, and
so on), as most terminals still show them.

Dasha Framework chooses the depth by itself (`auto`): 24-bit colour when the
`COLORTERM` environment variable is `truecolor` or `24bit`, or on Windows,
whose console always shows it; 16 colours when `TERM` is `linux` (the Linux
console), `cons25` or `ansi`; otherwise 256 colours. To choose for
yourself, run Dasha Framework with `-d 24bit`, `-d 256` or `-d 16` (the long
form is `--colour-depth`; `auto` is the default), or choose on the
**Desktop** page of Settings.... Either way, the choice is kept in
`~/.dasha/settings.toml` as `colour_depth`, so Dasha Framework starts with it
from then on, until you choose again; `-d auto` goes back to letting
Dasha Framework decide.

If colours look wrong, or show as the wrong colour, the terminal cannot
show that many: choose 256 colours, or 16 for a terminal with no more than
the standard colours. `COLORTERM` is often not passed on over SSH, so a
terminal that can show 24-bit colour may get the 256-colour palette until
you choose 24-bit.

### Button shadows

The top-level `"button_shadow"` setting chooses how push button shadows
are drawn:

| Value | Looks like | Used by |
| --- | --- | --- |
| `"solid"` | `▄` beside the button and `▀▀▀▀` below it | The default theme |
| `"outline"` | `┐` beside the button and `└──┘` below it: a single-line outline of where the shadow falls | The monochrome theme |

Without colour, solid blocks look like part of the button, so the
Monochrome theme uses the outline instead. All of these characters are in
code page 437. A file can choose either style with any base theme:

```json
{"base": "monochrome", "button_shadow": "solid"}
```

As with the shortcuts file, Dasha Framework checks the colours file before it
takes over the screen. If anything is wrong, it lists every problem and does
not start. Fix the file, or move it aside to use the default colours. The
file can be UTF-8 (with or without a byte order mark) or UTF-16.

## Roles

This table lists every role and its colours in the Default, Dark and
Monochrome themes. It is generated from `dasha.theme` when the
documentation is built, so it always matches the code. "The window's" means
the colours of the window or dialog that the widget is in.

The `help.*` roles are the colours of help windows, whose cyan marks them as
windows to read rather than to fill in. The Dark theme keeps them cyan too.

```{colour-roles}
```

## For developers

The roles are defined in `dasha.theme`. Each one is a class attribute,
such as `Window.frame_style`, so the classes themselves still define the
default colours, and a subclass that restyles a widget keeps its own colours
under any theme that has colours. Under one that has none, Dasha Framework leaves
them out as it draws (see [Monochrome mode](#monochrome-mode)).

So never tell things apart by colour alone: green for "passed" and red for
"failed" look the same with no colours. Add a mark or a word as well. A widget
with colours of its own can also choose how it looks without them, by looking
at `theme.has_colours()` as it draws.

To give one kind of window colours of its own, set them in a subclass. This
works whether the application runs on its own or the desktop started it. A
window that holds a `TerminalView` also needs the view's `default_style`,
because the view covers the window's body:

```python
class BlackWindow(Window):
    frame_style = Style(foreground=BRIGHT_WHITE, background=BLACK, bold=True)
    inactive_frame_style = Style(foreground=WHITE, background=BLACK)
    body_style = Style(foreground=WHITE, background=BLACK)
    button_style = Style(foreground=BRIGHT_GREEN, background=BLACK, bold=True)

window.view.default_style = Style(foreground=WHITE, background=BLACK)
```

- A colour in a `Style` is a number from 0 to 255 or a
  `dasha.style.Rgb`, such as `Rgb(255, 136, 0)` or
  `Rgb.parse("#ff8800")`. `style.set_colour_depth(depth)`, or
  `PresentationManager.set_colour_depth(depth)` while Dasha Framework is running,
  chooses how colours are drawn. `Rgb.nearest_256()`, `Rgb.nearest_16()`
  and `Rgb.of_palette(number)` convert between them.
- `apply_theme(theme)` installs a theme, and `current_theme()` returns the
  styles in use.
- `load_theme(path)` and `build_theme(settings)` build a theme from a
  colours file or its contents.
- `load_named_theme(name)` loads a built-in theme, a theme from the themes
  folder, or a theme file at a given path, and `theme_names()` lists the
  themes available.

While Dasha Framework is running, `PresentationManager.set_theme(name)`, or an
application's `set_theme`, changes the theme. It installs the theme, tells
every window about it (through `Window.theme_changed`, for windows that
keep a copy of a style of their own), redraws the whole screen, and sends
the theme to each application running in its own process, which then
redraws its windows. Widgets need do nothing, because they read their
colours from their class's attributes each time they are drawn.
`use_theme(theme, name)` does the same for a theme built in some other way.
