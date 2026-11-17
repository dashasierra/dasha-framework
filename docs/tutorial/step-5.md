# Step 5: Opening files

In this step, Notepad learns to open files, both those named on the command
line and those chosen with File > Open....

{download}`Download step 5 <notepad5.py>`

**Files to start with.** Notepad is given the paths to open when it is
created, and `start` opens each one, or a new, empty window if there are
none:

```{literalinclude} notepad5.py
:language: python
:start-at: "    def __init__(self, paths"
:end-at: "            self.new()"
```

```{literalinclude} notepad5.py
:language: python
:start-at: 'if __name__ == "__main__":'
```

**A window knows its file.** `NotepadWindow` now takes the file's `path`
and `text`. It shows the file's name as its title, and `load` puts a file
into a window that is already open:

```{literalinclude} notepad5.py
:language: python
:start-at: "        self.notepad = notepad"
:end-before: "class WindowAction"
```

**Reading a file.** `read` returns a file's text, or tells the user why it
cannot be read. `tell` shows a message in an
{py:func}`~dasha.dialog.information` box.

Dialogs are shown by `manager.execute`, where the manager is the
presentation manager that runs the desktop. `execute` waits for the user's
answer, so it can only be used while the desktop is running. However, a
file named on the command line is read in `start`, which runs before
anything is on the screen. So `tell` passes the dialog to
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
stays a Windows file.

```{literalinclude} notepad5.py
:language: python
:pyobject: line_ending
```

**Opening.** `open_path` puts a file in the right place: if the file is
already open, its window is brought to the front; if the front window is
new and still empty, the file is opened there; otherwise it opens in a new
window. `open_file` asks the user which file to open, with a
{py:class}`~dasha.filedialog.FileDialog`. `execute` returns `"ok"` once
a file has been chosen, and the dialog's `path` is the chosen file.
`FILTERS` lists the kinds of file that the dialog's Type box offers.

```{literalinclude} notepad5.py
:language: python
:start-at: "    def open_path(self"
:end-before: "    def _front(self)"
```

The new Open... item in the File menu uses the `open_file` key (F3, unless
the user changes it):

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
