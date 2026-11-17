# Step 7: Preventing loss of work

So far, closing a window or quitting Notepad throws away anything that has
not been saved. Dasha Framework checks with an application before either of these
happens, and the application can refuse.

{download}`Download step 7 <notepad7.py>`

- **`request_close`** is called on a window before it closes, however the
  user closes it: with `[■]`, Alt+F4, File > Close or the Window menu.
  Return `False` to keep the window open.
- **`can_close`** is called on the application before it ends, whether
  through File > Exit, Ctrl+Q or the whole desktop shutting down. Return
  `False` to keep running.

Both rely on `offer_to_save`, which asks the user with a
{py:func}`~dasha.dialog.question`: a dialog with buttons of your own
choosing, each of which gives its answer as the value that `execute`
returns.

```{literalinclude} notepad7.py
:language: python
:start-at: "    def offer_to_save(self)"
:end-before: "class WindowAction"
```

```{literalinclude} notepad7.py
:language: python
:start-at: "    # Closing"
:end-before: "    # Menus"
```

`all` stops at the first window that refuses, so choosing Cancel for any
file keeps Notepad running, with the remaining windows still open. Open a
file, change it, and close it:

```{image} screens/save-question.png
:alt: A dialog asking Save the changes to todo.txt?, with Save, Don't save and Cancel buttons.
:class: screen
```
