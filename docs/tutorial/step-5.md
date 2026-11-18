# Step 5: Opening files

In this step, Notepad learns to open files, both those named on the command
line and those chosen with File > Open....

{download}`Download step 5 <notepad5.py>`

**New imports.** This step adds five:

- `os`, from Python's standard library, for working with paths: a file's
  name (`os.path.basename`), its folder (`os.path.dirname`), its full path
  (`os.path.abspath`), and whether it exists (`os.path.exists`);
- `sys`, also from the standard library, for the command line's arguments
  (`sys.argv`);
- `Sequence`, added to the import from `collections.abc`, for the type of
  the list of paths Notepad is given;
- {py:func}`~dasha.dialog.information` from `dasha.dialog`, a dialog that
  shows a message;
- {py:class}`~dasha.filedialog.FileDialog` from `dasha.filedialog`, the
  dialog for choosing a file.

The top of the program is now:

```{literalinclude} notepad5.py
:language: python
:start-at: "import os"
:end-before: "FILTERS = ["
```

**Files to start with.** Notepad is given the paths to open when it is
created. Its `__init__` calls `Application`'s own with `super().__init__()`
first, and then keeps the paths. `start` opens each one (with `open_path`,
below), or a new, empty window if none of them could be opened:

```{literalinclude} notepad5.py
:language: python
:start-at: "    def __init__(self, paths"
:end-at: "            self.new()"
```

The paths come from the command line: `sys.argv` is the command that ran
the program, so `sys.argv[1:]` is everything after `notepad.py`:

```{literalinclude} notepad5.py
:language: python
:start-at: 'if __name__ == "__main__":'
```

**A window knows its file.** `NotepadWindow` now takes the file's `path`
and `text`, and gives the text to its text area with `text=text`. Its
`file_name` is the last part of the path, which it shows as its title (a
window's `title` can be changed at any time), and `load` puts a file into a
window that is already open. It also remembers the file's line ending, with
`line_ending`, which is described under **Line endings** below:

```{literalinclude} notepad5.py
:language: python
:pyobject: NotepadWindow
```

`new` passes the path and text on to the window:

```{literalinclude} notepad5.py
:language: python
:pyobject: Notepad.new
```

**Reading a file.** `read` returns a file's text, or tells the user why it
cannot be read. `tell` shows a message in an
{py:func}`~dasha.dialog.information` box.

Dialogs are shown by `manager.execute`, where `manager` is the presentation
manager from [step 4](step-4.md). `execute` waits for the user's answer, so
it can only be used while the desktop is running. However, a file named on
the command line is read in `start`, which runs before anything is on the
screen. So `tell` passes the dialog to
{py:meth}`~dasha.manager.PresentationManager.call_when_running`, which
shows it straight away if the desktop is already running (as it is for File
> Open), and otherwise as soon as the desktop starts. A file that cannot be
read is skipped, and its message appears once Notepad's windows are on
screen.

```{literalinclude} notepad5.py
:language: python
:start-at: "    def tell(self"
:end-before: "    def open_path(self"
```

**Line endings.** The file is read with `newline=""`, so its line endings
come through unchanged. A text area always uses `"\n"` internally, so the
window remembers the file's own line ending (`line_ending`) and puts it back
when the file is saved, in [step 6](step-6.md). That way, a Windows file
stays a Windows file. `line_ending` is a function of its own, outside both
classes, just below the imports:

```{literalinclude} notepad5.py
:language: python
:pyobject: line_ending
```

**Opening.** `open_path` puts a file in the right place: if the file is
already open, its window is brought to the front with `show`; if the front
window is new and still empty, the file is opened there; otherwise it opens
in a new window. `show` asks the presentation manager to bring the window
to the front, restoring it first if it is minimised:

```{literalinclude} notepad5.py
:language: python
:start-at: "    def show(self"
:end-before: "    def tell(self"
```

`open_file` asks the user which file to open, with a
{py:class}`~dasha.filedialog.FileDialog`. It does nothing unless the
manager's `is_running` says the desktop is running, as dialogs need it to
be. The dialog starts in the front window's folder (or the current folder,
if that window has no file), and with
`must_exist=True` it only accepts a file that is there. `execute` returns
`"ok"` once a file has been chosen, and the dialog's `path` is the chosen
file.

```{literalinclude} notepad5.py
:language: python
:start-at: "    def open_path(self"
:end-before: "    def _front(self)"
```

`FILTERS` lists the kinds of file that the dialog's Type box offers, each a
name and the patterns of the file names it matches. It goes below the
imports:

```{literalinclude} notepad5.py
:language: python
:start-at: "FILTERS = ["
:end-before: "def line_ending"
```

The new Open... item in the File menu, between New and the separator, uses
the `open_file` key (F3, unless the user changes it):

```{literalinclude} notepad5.py
:language: python
:start-at: '                label="&Open...",'
:end-at: '                status="Opens a file",'
```

Run it with some files, using `python notepad.py shopping.txt todo.txt`:

```{image} screens/opened-files.png
:alt: Two windows, shopping.txt and todo.txt, each showing its file's text.
:class: screen
```

and press F3 for the file dialog:

```{image} screens/open-dialog.png
:alt: The Open dialog: a Name box, the list of files (letters, ideas.md, shopping.txt, todo.txt), the Type and Drive boxes, and OK and Cancel buttons.
:class: screen
```

The picture was taken on Windows; on other systems the dialog has no Drive
box, and folder names end in `/`. Tab moves between the parts of the dialog,
and Enter on a folder opens it. Naming a file that does not exist yet opens
an empty window, ready to be saved under that name once saving works.
