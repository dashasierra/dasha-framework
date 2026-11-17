# On the desktop

So far, Notepad has run on a desktop of its own. Dasha Framework's own desktop can
run any number of applications side by side, each in its own process, and
lists them in its Applications menu. To add Notepad to it, install it:

```bash
dasha install-app notepad.py
```

Then start the desktop, and choose Notepad from Applications in the system
menu (`≡`), or name it to start it there straight away (`dasha-desktop
notepad`):

```bash
dasha desktop
```

The class is exactly the same: `run` detects that the desktop started it,
and joins that desktop instead of creating its own. On the desktop, Ctrl+Q
quits the whole desktop, but it calls each application's `can_close`
first, so Notepad still offers to save your work.

`dasha notepad` runs an installed Notepad on its own, just as
`python notepad.py` does: there is no system menu, and Dasha Framework ends when
Notepad does. To run Notepad once without installing it, use Run... in the
system menu: name the script, and the dialog finds its application class,
and any virtual environment next to it, by itself. See
[Applications](../architecture.md#applications-dashaapplication) in the
architecture guide for more.

## Where next

- **Testing.** `apps/tests/test_notepad.py` tests Notepad without a
  terminal: it runs the presentation manager on scripted keys, and checks
  the windows, the files and the answers to dialogs.
- **More widgets.** `apps/demo.py` shows the other widgets and dialogs,
  including buttons, check boxes, lists, tables, trees and tabs. Each one
  has a page in the [API reference](../api.rst).
- **Colours and keys.** Users can change both without any change to the
  application; see [Colours](../colours.md) and
  [Keyboard shortcuts](../shortcuts.md).
