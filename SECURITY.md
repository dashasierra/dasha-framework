# Security policy

## Reporting a vulnerability

Please report security problems privately rather than in a public issue.
Use the **Report a vulnerability** button on the repository's
[Security tab](https://github.com/dashasierra/dasha-framework/security), and
include what you found, how to reproduce it, and the versions of Dasha Framework,
Python and the operating system you used.

You should receive a reply within a week. Once a fix has been released, the
report can be made public, with credit to you if you would like it.

## Supported versions

Only the latest release receives security fixes.

## What counts as a vulnerability

Dasha Framework handles data that may come from untrusted sources. A flaw in how
it handles any of the following is treated as a security problem:

- **Terminal input**: escape sequences, pasted text and mouse reports.
- **Text it displays**: file names, file contents and window titles. None
  of these should ever be able to send a command to the terminal.
- **Messages from applications** running in their own processes. No
  application should be able to crash or freeze the desktop, impersonate
  another application or Dasha Framework itself, capture keystrokes meant for
  another application, or read or change the clipboard without the user's
  knowledge.
- **Planted modules**: Python modules placed in the folder that Dasha Framework
  is run from.
- **Settings files** in `~/.dasha/`, and application manifests.

Running an application or script that you chose to run, whether with
Run..., `dasha install-app` or the command line, runs that program's
code, just as running any other program does. That is not a vulnerability
in itself.
