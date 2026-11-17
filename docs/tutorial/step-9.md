# Step 9: Adding an Insert menu

This step adds a submenu of things to insert at the cursor, which in turn
has a submenu of its own. An item with a `submenu` instead of an `action`
is marked with `►`, and opens that menu beside it.

{download}`Download step 9 <notepad9.py>`

```{literalinclude} notepad9.py
:language: python
:pyobject: Notepad._insert_menu
```

`_insert` types text into the front window's text area. The boxes are
drawn with code page 437's line-drawing characters, the same ones that
Dasha Framework uses for its frames. The source writes them by name
(`"\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}"`), so that the file stays
readable in any editor:

```{literalinclude} notepad9.py
:language: python
:start-at: "SINGLE_BOX = ("
:end-before: "def line_ending"
```

Insert is added at the end of the Edit menu:

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
