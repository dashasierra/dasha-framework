# Step 1: A desktop, with an escape hatch

Every Dasha Framework program is an **application**: a subclass of
{py:class}`~dasha.application.Application`. Its `start` method runs
once the application is on the desktop, and sets up its menus and windows.
The smallest useful application has a menu bar with a way to quit:

```{literalinclude} notepad1.py
:language: python
```

{download}`Download step 1 <notepad1.py>`

Run it, and you will see the desktop: a patterned background, the menu bar
along the top, and the status bar along the bottom. The status bar shows
the application's name on the left and, on the right, the key that opens
the menu bar.

```{image} screens/desktop.png
:alt: The empty desktop: File and Window menus along the top, and the status bar along the bottom showing Notepad and F10 Menu.
:class: screen
```

**How it works.**

- **`name`** is the name Dasha Framework uses for the application: on the status
  bar, in messages, and later on in the desktop's Applications menu.
- **`menus`** is the application's menu bar: a list of
  {py:class}`~dasha.menu.Menu` objects, each with a title and a list of
  {py:class}`~dasha.menu.MenuItem` objects. The `&` in `"&File"` makes
  F its mnemonic letter, so Alt+F opens the menu (F10 also opens the menu
  bar). In `"E&xit"`, pressing X chooses the item while the menu is open.
- **`action`** is what an item does when it is chosen. `self.exit` is the
  application's own way to end: it checks `can_close` first (there is more
  about this in [step 7](step-7.md)), and then ends.
- **`status`** is help text shown on the status bar while the item is
  highlighted.
- **`Notepad().run()`** runs the application on its own, on a desktop of
  its own in the terminal, until the application ends. `run` returns an
  exit code, which `SystemExit` passes back to the shell.

Open the File menu with Alt+F (or click it):

```{image} screens/file-menu.png
:alt: The File menu open, with its one item, Exit.
:class: screen
```

The Window menu beside it is not in your code: Dasha Framework adds it to every
application's menu bar, to list, arrange and close the application's
windows. Choose Exit to quit. Ctrl+Q also quits, but asks first, because it
is the desktop's key rather than your application's:

```{image} screens/close-question.png
:alt: A dialog asking Close Notepad?, with Close and Cancel buttons.
:class: screen
```
