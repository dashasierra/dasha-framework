# Contributing to Dasha Framework

Thank you for helping. Bug reports, ideas and pull requests are all welcome.

## Reporting a bug

Open an issue using the bug report form. Terminals vary more than you might
expect, so the form asks for your operating system, terminal, Python version
and Dasha Framework version. If a key or the mouse is not working, the output of
`dasha --key-test` is the most useful thing to include.

To report a security problem, please follow [SECURITY.md](SECURITY.md)
instead.

## Making a change

The [development guide](docs/development.md) explains how to set up a
development environment, run the tests and checks, and follow the project's
conventions. In short:

- **Standard library only.** Dasha Framework has no runtime dependencies, and
  it will stay that way. Development tools belong in the `dev` extra.
- **Code page 437 glyphs** for anything drawn on screen, written in the
  source as escapes such as `"\N{FULL BLOCK}"`.
- **British spelling**, such as "colour" and "centre", everywhere. Text
  shown on screen uses "-ise" (Maximise), while code and documentation use
  "-ize" (`maximise`).
- **Tests** go in `tests/` for Dasha Framework itself and in `apps/tests/` for
  the example applications. Every change should come with tests that would
  have caught the problem it fixes.
- **Before opening a pull request**, run black, pylint, mypy and the tests
  (see the development guide). Each pull request runs them all on Linux,
  Windows and macOS and builds the documentation and the package, and can
  be merged once they pass.

If users would notice your change, add a line about it to the "Unreleased"
section of [CHANGELOG.md](CHANGELOG.md).
