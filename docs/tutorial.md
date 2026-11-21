# Tutorial: building Notepad

In this tutorial you build Notepad, the text editor in the repository's
`apps/` folder, one step at a time. Each step adds one feature and leaves
you with a working program, so you can see what each piece of code does
before you move on. Each step has a page of its own, and the links at the
foot of each page lead on to the next. By the end, you will have the
complete application:

- a desktop with a menu bar and a way to quit;
- windows that can be moved, resized, maximised and closed;
- a text area to type in, with undo, the clipboard and selection built in;
- files opened from the command line or a file dialog, and saved;
- a prompt before unsaved work is lost;
- Edit and Insert menus;
- a Format menu that turns word wrap and line numbers on and off, and the
  cursor position shown at the foot of each window.

The tutorial explains each part of Dasha Framework as it uses it. The
[architecture guide](architecture.md) goes into more detail, and the
[API reference](api.rst) lists every class and function, with a short
description of each and of its arguments.

## Before you start

You need Python 3.12 or newer, with Dasha Framework installed. From a copy of the
repository, run:

```bash
python -m pip install -e .
```

Create a folder to work in, and keep your program in it as `notepad.py`.
Each step shows the code to add, and you can also download each step's
complete program if you would rather start from that. Run your program
after each step:

```bash
python notepad.py
```

Notepad takes over the terminal while it runs. The pictures show it in an
80 by 24 terminal using Dasha Framework's own colours, which your terminal may
show slightly differently. To quit Notepad at any point, press Ctrl+Q and
then Enter.

Like the example applications, the code passes arguments by name
(`Rect(row=2, column=4, height=15, width=60)` rather than
`Rect(2, 4, 15, 60)`), so that you can see what each one is.

## The steps

```{toctree}
:maxdepth: 1

tutorial/step-1
tutorial/step-2
tutorial/step-3
tutorial/step-4
tutorial/step-5
tutorial/step-6
tutorial/step-7
tutorial/step-8
tutorial/step-9
tutorial/step-10
tutorial/on-the-desktop
```
