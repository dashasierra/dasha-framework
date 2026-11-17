# Step 8: Adding an Edit menu

Every editing key already works in the text area. An Edit menu makes these
commands easy to find, and lets them be used with the mouse.

{download}`Download step 8 <notepad8.py>`

The items are all alike, so they are built from a table. Each entry gives a
label, the text area method the item runs, the shortcut action whose key it
shows, and its status text. A `None` entry in the table is a separator.

```{literalinclude} notepad8.py
:language: python
:pyobject: Notepad._edit_items
```

The keys come from `hint`, as Close's key does in [step 4](step-4.md), so
the menu always shows the keys the user actually has. Add the menu to the
bar in `_menus`:

```{literalinclude} notepad8.py
:language: python
:start-at: "        return ["
:end-at: "        ]"
```

Type something, and open the Edit menu with Alt+E:

```{image} screens/edit-menu.png
:alt: The Edit menu open: Undo, Redo, Cut, Copy, Paste, Select all and Delete line, each with its key.
:class: screen
```
