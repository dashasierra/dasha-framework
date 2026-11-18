# Step 4: Creating a window class, adding more windows

An editor has a window for each file. Before adding files, give Notepad's
window a class of its own, so that each window can keep track of what
belongs to it, and let the File menu open and close windows. From here on,
the program is too long to repeat in full at each step, so each step shows
only what is new, and its download contains the whole program.

{download}`Download step 4 <notepad4.py>`

**New imports.** This step adds three names to the imports:

- `separator` from `dasha.menu`, alongside `Menu` and `MenuItem`, for a
  dividing line in the File menu;
- `Callable` from `collections.abc`, and `Protocol` from `typing`. Both
  come from Python's standard library rather than from Dasha Framework, and
  describe functions to the type checker, as shown below.

The top of the program is now:

```{literalinclude} notepad4.py
:language: python
:start-at: "from collections.abc import"
:end-before: "class NotepadWindow"
```

**The window class.** `NotepadWindow` is a `Window` that sets itself up:
`super().__init__` is given the same title and flags that `Window` was
given in [step 3](step-3.md), and a rectangle that is now passed in, so
that each window can go somewhere different. The window
keeps its text area as `self.area` (`add` returns the widget it adds) for
the code that works on it. It also keeps a reference to the application it
belongs to, as `self.notepad`, which later steps need. The type of
`notepad` is written in quotes, `"Notepad"`, because the `Notepad` class
comes further down the file:

```{literalinclude} notepad4.py
:language: python
:pyobject: NotepadWindow
```

**More windows.** `new` opens a window, and `_place` works out where to put
it: each new window goes a little below and to the right of the one before,
so that none hides another completely, and after six it starts again at
the top. `self.windows` is the application's list of its open
windows, in the order they were opened: `open` adds a window to it, and the
window is taken off it again when it closes. `start` now builds the menus
with `_menus` and opens the first window with `new`:

```{literalinclude} notepad4.py
:language: python
:start-at: "    def start(self)"
:end-before: "    def _front(self)"
```

**Acting on the front window.** Menu items such as Close act on the window
in front. `self.active_window` is the application's window nearest the
front, or `None` if it has none. It is a plain `Window` as far as the type
checker knows, so `_front` checks that it is a `NotepadWindow` before
returning it. `_on_front` turns "something to do with a window" into a menu
action that finds the front window when the item is chosen, rather than
when the menu was created:

```{literalinclude} notepad4.py
:language: python
:start-at: "    def _front(self)"
:end-before: "    # Menus"
```

The "something to do" is described for the type checker by `WindowAction`,
which goes between the two classes. A class based on `Protocol` describes
what an object can do rather than what it is: here, it can be called with a
`NotepadWindow` as its `window=` argument. Any function that can be called
that way fits, such as the `lambda` that the Close item below passes to
`_on_front`. `_on_front` returns a `Callable[[], None]`, a function that
takes no arguments and returns nothing, which is what a menu item's
`action` is.

```{literalinclude} notepad4.py
:language: python
:pyobject: WindowAction
```

**The File menu** now has New, Close and Exit, with a
{py:func}`~dasha.menu.separator` line before Close:

```{literalinclude} notepad4.py
:language: python
:start-at: "    def _menus(self)"
:end-before: "if __name__"
```

- **`self.manager`** is the presentation manager: the part of Dasha
  Framework that runs the desktop, and that every application runs on. It
  is `None` until the application has been launched, but `start`, which
  calls `_menus`, only runs after that, so `_file_items` can `assert` that
  it is there. This also tells the type checker that it is not `None`.
- **`shortcut`** shows a key on the right of the item, and pressing that
  key chooses the item, whether or not the menu is open. The key comes from
  the user's keyboard shortcuts, `self.manager.shortcuts`, whose `hint`
  method gives the key for an action (`hint(action="close_window")`). It is
  not written out as `"Alt+F4"`, so if the user changes the key, the menu
  shows and uses their key instead.
- **`self.close(window=window)`** closes one of the application's windows,
  just as the user would by closing it.
- **`enabled=self.has_window`** greys out Close while Notepad has no
  window. `has_window` is a method of `Application`, given without calling
  it, and the menu calls it each time it is shown.

Run it, and choose File > New a couple of times:

```{image} screens/windows.png
:alt: Three Untitled windows, each a little down and to the right of the one before.
:class: screen
```

F6 brings the next window to the front, and the Window menu lists them
all. Close them all with File > Close, and you will see Close greyed out.
