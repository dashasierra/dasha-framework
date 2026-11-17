# Applications

Each application runs in its own process, so one that goes wrong does not take the others with it.

## Starting an application

Choose one from **Applications** in the [system menu](menus.md#the-system-menu), or use [Run...](running.md) for a script that is not installed.

## Switching between applications

The running applications are listed at the top of the system menu, with the active one marked. Choosing another switches to it. The menu bar always shows the active application's menus.

## Installing an application

From a command prompt:

```
dasha install-app path/to/app.py
```

It then appears in the Applications menu, and can be started with `dasha` and its id or its name, in any case: on its own (`dasha notepad`, or `dasha Notepad`), or on the desktop (`dasha-desktop notepad`, or `dasha desktop notepad`). No application can have the id `desktop`. `dasha list-apps` lists what is installed. The [Applications page of Settings](settings.md#applications) manages them too.

## When an application stops responding

Its window's title says **(Not responding)**. Closing the window then offers to end the application.
