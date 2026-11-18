# Step 9: Adding an Insert menu

This step adds a submenu of things to insert at the cursor, which in turn
has a submenu of its own. An item with a `submenu` instead of an `action`
is marked with `►`, and opens that menu beside it.

{download}`Download step 9 <notepad9.py>`

**New imports.** This step adds `time`, from Python's standard library,
for the date and time that Insert > Date and time types
(`time.strftime`). The top of the program is now:

```{literalinclude} notepad9.py
:language: python
:start-at: "import os"
:end-before: "FILTERS = ["
```

**The menus.** `_insert_menu` builds the Insert menu, with its Box submenu,
`boxes`. Each `Menu` here is given to a `MenuItem` as its `submenu`, rather
than going on the menu bar. The method goes after `_edit_items`:

```{literalinclude} notepad9.py
:language: python
:pyobject: Notepad._insert_menu
```

**Inserting.** `_insert` types text into the front window's text area,
using the text area's `insert` method, which puts the text in place of the
selection, or at the cursor, just as typing and pasting do. It goes in
`Notepad`, after `_on_front`:

```{literalinclude} notepad9.py
:language: python
:pyobject: Notepad._insert
```

**Boxes.** `box` is given one of the strings below, and takes it apart
into its six characters, `tuple(lines)`, to draw a box with room for ten
characters inside.
The boxes are drawn with code page 437's line-drawing characters, the same
ones that Dasha Framework uses for its frames. The source writes them by
name (`"\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}"`), so that the file stays
readable in any editor. They go below `FILTERS`:

```{literalinclude} notepad9.py
:language: python
:start-at: "SINGLE_BOX = ("
:end-before: "def line_ending"
```

Insert is added at the end of the Edit menu, after the items that
`_edit_items` builds from its table in [step 8](step-8.md), and before it
returns them:

```{literalinclude} notepad9.py
:language: python
:start-at: "        items += ["
:end-at: "        return items"
```

Open Edit > Insert > Box:

```{image} screens/insert-menu.png
:alt: The Edit menu open with its Insert submenu, and Insert's Box submenu beside that.
:class: screen
```

The mnemonic letters in Insert's menus deliberately overlap the Edit
menu's: D is Delete line in Edit, Date and time in Insert, and Double line
in Box. When several open menus share a letter, the innermost one wins.
Choose Edit > Insert > Box > Double line:

```{image} screens/box.png
:alt: A double-lined box drawn at the top of the window's text.
:class: screen
```
