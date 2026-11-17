# Step 10: Adding a Format menu, and the cursor's place

This last step finishes Notepad. It adds a Format menu that turns word wrap
and line numbers on and off, and shows the cursor position at the foot of
each window. The program for this step is Notepad itself, `apps/notepad.py`.

{download}`Download step 10 <../../apps/notepad.py>`

A text area supports both features, and both are off unless asked for:

- With `word_wrap` on, a line too long for the window continues on the rows
  below, broken after a space, and the window no longer scrolls sideways.
- With `line_numbers` on, each line's number is shown at its left, followed
  by a `│`. A wrapped line is numbered on its first row only, and the column
  of numbers widens once there are a thousand lines.

So each window's text area is created with Notepad's own settings:

```{literalinclude} ../../apps/notepad.py
:language: python
:start-at: "        self.area = self.add("
:end-before: "        self.modified = False"
```

Notepad creates the settings, and the menu items that show them, when it is
created itself:

```{literalinclude} ../../apps/notepad.py
:language: python
:start-at: "        self.word_wrap = False"
:end-before: "    def start(self)"
```

Each item's label is marked with `√` while its setting is on:

```{literalinclude} ../../apps/notepad.py
:language: python
:pyobject: marked
```

Choosing an item switches its setting in every window, and updates the
item's mark. A menu item's `label` can be changed at any time, and the menu
shows the new label the next time it opens.

```{literalinclude} ../../apps/notepad.py
:language: python
:start-at: "    def _areas(self)"
:end-before: "if __name__"
```

The menu goes on the bar after Edit. F is already taken by File, so the
Format menu's letter is O, and Alt+O opens it:

```{literalinclude} ../../apps/notepad.py
:language: python
:start-at: "        return ["
:end-at: "        ]"
```

```{image} screens/format-menu.png
:alt: The Format menu open, with Word wrap and Line numbers.
:class: screen
```

## Where the cursor is, and unsaved changes

A window can show a short piece of text at the left of its frame's bottom
edge, called its `footer`, which is a list of parts. Notepad's windows work
out their footer each time they are drawn, by overriding `footer_parts`.
The footer starts with `☼` while the file has unsaved changes, followed by
the cursor position as COL:ROW: the character position along the line
(where a tab counts as one character), and the line number. With word wrap
on, ROW counts lines rather than the rows they wrap onto, just as the line
numbers do.

```{literalinclude} ../../apps/notepad.py
:language: python
:pyobject: NotepadWindow.footer_parts
```

The frame draws the line between the parts itself (`╚═ ☼ ═ 12:3 ═══`), in
its current border and colours: double while the window is active, single
while it is not, and in the moving frame's style while it is being moved.
The parts are therefore only ever text, never a piece of the frame that
could be drawn in the wrong style.

When a line is too long for the window, the horizontal scroll bar starts
after the footer (`╚═ 71:1 ═◄▒▒▒■►─┘`). If the window is too narrow for
both, the footer is hidden, and the scroll bar takes up the whole edge again.

Choose Word wrap, then Line numbers, and type a long line followed by a
short one:

```{image} screens/word-wrap.png
:alt: Two lines typed, numbered 1 and 2; the long first line goes on in the rows below it, broken between words, with no number beside them.
:class: screen
```
