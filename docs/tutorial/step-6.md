# Step 6: Saving files

To save a file, a window needs to know whether it has changes, and where to
save them.

{download}`Download step 6 <notepad6.py>`

**Changes.** A text area calls its `on_change` function after every change
the user makes. The window uses this to set `modified`, and clears it again
when a file is loaded or saved:

```{literalinclude} notepad6.py
:language: python
:start-at: "        self.area = self.add("
:end-at: '        """Whether there are changes since it was opened or saved."""'
```

```{literalinclude} notepad6.py
:language: python
:pyobject: NotepadWindow._changed
```

**Saving.** `save` writes the text to the file, with the file's own line
endings put back. It writes with {py:func}`~dasha.config.write_atomically`
rather than `open(path, "w")`, which would empty the file first: if the
disk is full, or the program is stopped part-way, the file is left as it
was rather than lost. A window that has no file yet asks for a name instead,
using `save_as`. This shows the file dialog with a Name box to fill in, and
asks for confirmation with {py:func}`~dasha.dialog.confirm` before
overwriting another file. If the file cannot be written, the window keeps
the file it had before.

```{literalinclude} notepad6.py
:language: python
:start-at: "    # Saving"
:end-before: "class WindowAction"
```

Both methods return whether the file was saved, which the next step needs.
The File menu gains Save (with the `save_file` key, F2) and Save as....
Type something in a new window and press F2. Because there is no file yet,
Save asks for a name:

```{image} screens/save-as-dialog.png
:alt: The Save as dialog, suggesting the name untitled.txt, over a window holding Plans for the weekend.
:class: screen
```
