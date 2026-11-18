# Step 6: Saving files

To save a file, a window needs to know whether it has changes, and where to
save them.

{download}`Download step 6 <notepad6.py>`

**New imports.** This step adds two:

- {py:func}`~dasha.config.write_atomically` from `dasha.config`, which
  writes a file safely, as described under **Saving** below;
- {py:func}`~dasha.dialog.confirm`, added to the import from
  `dasha.dialog`, a dialog that asks the user to confirm something.

The top of the program is now:

```{literalinclude} notepad6.py
:language: python
:start-at: "import os"
:end-before: "FILTERS = ["
```

**Changes.** A text area calls its `on_change` function after every change
the user makes. The window uses this to set `modified`:

```{literalinclude} notepad6.py
:language: python
:start-at: "        self.area = self.add("
:end-at: '        """Whether there are changes since it was opened or saved."""'
```

`on_change` is given the text area that changed, as `area`. A window has
only the one text area, so `_changed` has no use for it, and `del area`
says so:

```{literalinclude} notepad6.py
:language: python
:pyobject: NotepadWindow._changed
```

`load` clears `modified` again when a file is loaded into the window:

```{literalinclude} notepad6.py
:language: python
:pyobject: NotepadWindow.load
```

and `open_path` now opens a file in the front window only if that window
has no changes as well as no text (`not front.modified`), so that text
typed and then deleted still counts as a change.

**Saving.** `save` writes the text to the file, with the file's own line
endings put back. It writes with {py:func}`~dasha.config.write_atomically`
rather than `open(path, "w")`, which would empty the file first: if the
disk is full, or the program is stopped part-way, the file is left as it
was rather than lost. Its `newline=""` writes the line endings exactly as
they are in the text. If the file cannot be written, `save` uses
Notepad's `tell` from [step 5](step-5.md), through the window's
`self.notepad`, to say why.

A window that has no file yet asks for a name instead, using `save_as`.
This shows the file dialog, with a Name box filled in with the name to
suggest (`name=`), and asks for confirmation with
{py:func}`~dasha.dialog.confirm` before overwriting another file. Like the
file dialog, `confirm` is shown with `execute`, which returns `"ok"` if the
user chooses its OK button, here labelled Replace (`ok_label`). If the file
cannot be written, the window keeps the file it had before.

```{literalinclude} notepad6.py
:language: python
:start-at: "    # Saving"
:end-before: "class WindowAction"
```

Both methods return whether the file was saved, which the next step needs.
The File menu gains Save (with the `save_file` key, F2) and Save as...,
after Open...:

```{literalinclude} notepad6.py
:language: python
:start-at: '                label="&Save",'
:end-at: '                status="Saves under a new name",'
```

Type something in a new window and press F2. Because there is no file yet,
Save asks for a name:

```{image} screens/save-as-dialog.png
:alt: The Save as dialog, suggesting the name untitled.txt, over a window holding Plans for the weekend.
:class: screen
```
