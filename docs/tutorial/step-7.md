# Step 7: Preventing loss of work

So far, closing a window or quitting Notepad throws away anything that has
not been saved. Dasha Framework checks with an application before either of these
happens, and the application can refuse.

{download}`Download step 7 <notepad7.py>`

**New imports.** This step adds {py:func}`~dasha.dialog.question` to the
import from `dasha.dialog`, which now reads:

```{literalinclude} notepad7.py
:language: python
:start-at: "from dasha.dialog import"
:end-at: "from dasha.dialog import"
```

**Asking first.** Dasha Framework calls two methods, which an application
and its windows can override:

- **`request_close`** is called on a window before it closes, however the
  user closes it: with `[■]`, Alt+F4, File > Close or the Window menu.
  Return `False` to keep the window open.
- **`can_close`** is called on the application before it ends, whether
  through File > Exit, Ctrl+Q or the whole desktop shutting down. Return
  `False` to keep running.

Both rely on `offer_to_save`, a new method of `NotepadWindow` (after
`save_as`), which asks the user with a
{py:func}`~dasha.dialog.question`: a dialog with buttons of your own
choosing, each given as a label and the answer it gives. `execute` returns
the answer of the button the user chooses, or `"cancel"` if they press
Escape. Before asking, `offer_to_save` brings the window to the front with
the presentation manager's `bring_to_front`, so that the user can see which
file the question is about. It does this only if the window is on that
manager's desktop: a window's own `manager` is the presentation manager it
is shown on. Choosing Don't save clears `modified`, so that the window is
not asked about again.

```{literalinclude} notepad7.py
:language: python
:start-at: "    def offer_to_save(self)"
:end-before: "class WindowAction"
```

Notepad's `can_close` goes in `Notepad`, before the menus:

```{literalinclude} notepad7.py
:language: python
:start-at: "    # Closing"
:end-before: "    # Menus"
```

`all` stops at the first window that refuses, so choosing Cancel for any
file keeps Notepad running, with the remaining windows still open. The Exit
item's status text changes to `"Exits, offering to save each changed
file"`, to say so. Open a file, change it, and close it:

```{image} screens/save-question.png
:alt: A dialog asking Save the changes to todo.txt?, with Save, Don't save and Cancel buttons.
:class: screen
```
