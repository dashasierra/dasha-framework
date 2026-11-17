# Step 4: Creating a window class, adding more windows

An editor has a window for each file. Before adding files, give Notepad's
window a class of its own, so that each window can keep track of what
belongs to it, and let the File menu open and close windows. From here on,
the program is too long to repeat in full at each step, so each step shows
only what is new, and its download contains the whole program.

{download}`Download step 4 <notepad4.py>`

**The window class.** `NotepadWindow` is a `Window` that sets itself up:
its frame and buttons, and its text area, which it keeps as `self.area` for
the code that works on it. It also keeps a reference to the application it
belongs to, which later steps need:

```{literalinclude} notepad4.py
:language: python
:pyobject: NotepadWindow
```

**More windows.** `new` opens a window, and `_place` works out where to put
it: each new window goes a little below and to the right of the one before,
so that none hides another completely. `start` now builds the menus with
`_menus` and opens the first window with `new`:

```{literalinclude} notepad4.py
:language: python
:start-at: "    def start(self)"
:end-before: "    def _front(self)"
```

**Acting on the front window.** Menu items such as Close act on the window
in front, and `active_window` is the application's window nearest the
front. `_on_front` turns "something to do with a window" into a menu action
that finds the front window when the item is chosen, rather than when the
menu was created:

```{literalinclude} notepad4.py
:language: python
:start-at: "    def _front(self)"
:end-before: "    # Menus"
```

`WindowAction` describes this "something to do" for the type checker: a
function that takes the window as its `window=` argument.

**The File menu** now has New, Close and Exit, with a
{py:func}`~dasha.menu.separator` line before Close:

```{literalinclude} notepad4.py
:language: python
:start-at: "    def _menus(self)"
:end-before: "if __name__"
```

- **`enabled=self.has_window`** greys out Close while Notepad has no
  window. The menu checks this each time it is shown.
- **`shortcut`** shows a key on the right of the item, and pressing that
  key chooses the item, whether or not the menu is open. The key comes from
  the user's shortcuts (`hint(action="close_window")`) rather than being
  written out as `"Alt+F4"`, so if the user changes the key, the menu shows
  and uses their key instead.

Run it, and choose File > New a couple of times:

```{image} screens/windows.png
:alt: Three Untitled windows, each a little down and to the right of the one before.
:class: screen
```

F6 brings the next window to the front, and the Window menu lists them
all. Close them all with File > Close, and you will see Close greyed out.
