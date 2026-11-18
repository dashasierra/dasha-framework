# Step 8: Adding an Edit menu

Every editing key already works in the text area. An Edit menu makes these
commands easy to find, and lets them be used with the mouse.

{download}`Download step 8 <notepad8.py>`

**No new imports.** Everything this step uses is already imported:
`Menu`, `MenuItem` and `separator` from `dasha.menu`, and `Callable` from
`collections.abc`, all from [step 4](step-4.md).

The items are all alike, so they are built from a table in a new method,
`_edit_items`, which goes after `_file_items`. Each entry gives a label, the
name of the text area method the item runs, the shortcut action whose key
it shows, and its status text. A `None` entry in the table is a separator.

```{literalinclude} notepad8.py
:language: python
:pyobject: Notepad._edit_items
```

`on_area` makes each item's action. It uses `_on_front` from
[step 4](step-4.md), so the action finds the front window when it is
chosen, and Python's built-in `getattr` to look up the text area's method
by its name: `getattr(window.area, "undo")()` calls `window.area.undo()`.

The keys come from `hint`, as Close's key does in [step 4](step-4.md), so
the menu always shows the keys the user actually has. Add the menu to the
bar in `_menus`:

```{literalinclude} notepad8.py
:language: python
:pyobject: Notepad._menus
```

Type something, and open the Edit menu with Alt+E:

```{image} screens/edit-menu.png
:alt: The Edit menu open: Undo, Redo, Cut, Copy, Paste, Select all and Delete line, each with its key.
:class: screen
```
