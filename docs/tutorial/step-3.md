# Step 3: Adding somewhere to type

A window holds **widgets**, the controls inside it. A
{py:class}`~dasha.widgets.textarea.TextArea` holds many lines of text
to edit. Import `TextArea` from `dasha.widgets`, which holds all of Dasha
Framework's widgets, and add one to the window before opening it:

```{literalinclude} notepad3.py
:language: python
:emphasize-lines: 6,36
```

{download}`Download step 3 <notepad3.py>`

Run it and start typing:

```{image} screens/typing.png
:alt: The Untitled window holding the typed text: Dear diary, a blank line, then Today I wrote a text editor.
:class: screen
```

**How it works.**

- **`window.add(widget=...)`** puts a widget in a window, positioned
  relative to the inside of the frame, so row 0, column 0 is the first cell
  inside it. `add` also returns the widget, which [step 4](step-4.md) makes
  use of.
- **`name="text"`** names the widget. Every widget can have a name, which
  code can use to find it again; dialogs use names to find their fields.
  Notepad keeps its text area in a variable instead, from the next step on,
  so the name is only a label.
- **A text area fills its window.** It is always at least as big as the
  inside of the window, and grows with its text: type more lines than will
  fit, and the window's own scroll bars appear.
- **Editing is built in.** The arrow keys, Home and End, PgUp and PgDn,
  selecting with Shift or the mouse, Ctrl+X, Ctrl+C and Ctrl+V, Ctrl+Z to
  undo and Alt+Z to redo all work, and so does the Tab key, which types a
  tab.

That is already a working scratch pad. What it cannot do yet is open or
save files, or open a second window.
