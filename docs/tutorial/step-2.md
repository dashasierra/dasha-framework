# Step 2: Creating a window

Next, Notepad needs a window. A {py:class}`~dasha.window.Window` is a
framed rectangle with a title. `self.open` puts it on the desktop, in
front of the others. Add two imports, `Rect` from `dasha.canvas` and
`Window` from `dasha.window`, and open a window at the end of `start`. The
highlighted lines are the ones that are new:

```{literalinclude} notepad2.py
:language: python
:emphasize-lines: 4,6,27-35
```

{download}`Download step 2 <notepad2.py>`

Run it, and the window opens on the desktop:

```{image} screens/window.png
:alt: An empty blue window titled Untitled on the desktop.
:class: screen
```

**How it works.**

- **`title`** is the text shown in the window's title bar.
- **`Rect(row=2, column=4, height=15, width=60)`** is where the window
  goes, measured in screen cells. Row 0 is the top of the screen, where the
  menu bar is, so row 2 leaves a gap below it. The size includes the frame.
- **The flags** give the window its buttons. `closable` puts `[■]` at the
  left of the title bar, `minimisable` and `maximisable` put `[↓]` and
  `[↑]` at its right, and `resizable` gives it a grip in its bottom right
  corner. Without these flags, a window keeps the position and size it was
  opened with.
- **`self.open(window=window)`** is a method of `Application`. It shows
  the window and records that it belongs to Notepad.
- **The active window** has a double frame, and other windows have a
  single one.

**Try this.**

- Drag the window by its title bar, or resize it by its corner.
- Press F5 to maximise it, and press it again to restore it.
- Press Alt+F7 to move it from the keyboard, or Alt+F8 to resize it. The
  arrow keys move or resize the window, Enter keeps the change, and Escape
  puts the window back as it was.
- Close it with `[■]` or Alt+F4. Notepad keeps running without any
  windows, because an application runs until it ends, not until its
  windows are closed. Quit with File > Exit.

Users can change every one of these keys (see
[Keyboard shortcuts](../shortcuts.md)).
