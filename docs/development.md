# Development guide

## Setup

```bash
python -m venv .venv
```

Activate the environment, then install the package in editable mode along
with the development tools:

```bash
python -m pip install -e ".[dev]"
```

The `dev` extra (autopep8, black, build, coverage, mypy, pylint and twine)
is for development only. A plain `pip install dasha-framework` installs nothing beyond
the standard library.

## Running tests

The tests use the standard library's `unittest` module, so nothing extra
needs to be installed:

```bash
python -m unittest discover -s tests -v
```

These are Dasha Framework's own tests. The example applications in `apps/` have
their own tests in `apps/tests/`, which are run from that folder (see
`apps/README.md`), so neither set depends on the other.

`tests/support.py` holds helpers that the tests share:

- `isolated_home(self)`: a test that runs the command line calls this
  first, so that it never reads your own `~/.dasha` (such as a theme
  you chose from the menu) and passes on any machine.
- `assert_lines_shown(self, text, output)`: checks that some text reached
  the screen. A message with line breaks is drawn one line at a time, each
  in its own place, so it never appears in the terminal output as a single
  piece; this helper looks for each line in turn, skipping blank ones.
- `without_styles(output)`: removes the colour changes from terminal
  output, so that text split by a change of style can be checked.

## Test coverage

coverage.py measures how much of Dasha Framework the tests exercise, including
branches. Its settings are in `pyproject.toml` (`[tool.coverage.*]`), and it
measures only `dasha`, not the tests or the example
applications. Some tests start real application processes
(`python -m dasha.host`). These are measured too, each writing its own
data file, so combine the files before reporting:

```bash
python -m coverage run -m unittest discover -s tests
```

```bash
python -m coverage combine
```

```bash
python -m coverage report
```

The report lists, for each module, the lines and branches that the tests
never reached. For a page per module with those lines highlighted, write the
HTML report and open `htmlcov/index.html`:

```bash
python -m coverage html
```

Part of the terminal code is specific to each platform:
`terminal/_posix.py` runs only on Linux and macOS, and `terminal/_windows.py`
only on Windows, so a run on one platform leaves the other's code
uncovered. Code that only runs in a real terminal, such as the `--key-test`
screen and reading from the console, is also left uncovered and needs to be
checked by hand. Git ignores the data files (`.coverage*`) and `htmlcov/`.

## Formatting, linting and type checking

All the tools' settings are in `pyproject.toml`, and the line length is 88
throughout.

To format the code, run autopep8 first and black last, because black has
the final say on layout:

```bash
python -m autopep8 --in-place -r src tests frozen apps docs
```

```bash
python -m black src tests frozen apps docs
```

To lint, run pylint from the project's root. It finds its settings in
`.pylintrc` by itself, and those settings also say what to check (`src`,
`tests` and `frozen`), so no arguments are needed; any files you name on the command
line are checked instead. pylint exits with a non-zero status for any
message at all, even one too minor to lower the score below 10.00/10, so
check the exit status rather than the score:

```bash
python -m pylint
```

The example applications are linted and type-checked from `apps/` (see
`apps/README.md`).

To type-check, in strict mode, with the paths taken from `pyproject.toml`:

```bash
python -m mypy
```

Code should pass black, pylint and mypy without warnings before it is
committed.

## Checks on pull requests

A pull request into the default branch runs seven GitHub Actions workflows,
found in `.github/workflows/`. Each is a separate check, so a failure shows
exactly where the problem is:

- **Format** (black), **Lint** (pylint) and **Type check** (mypy). Lint and
  Type check run on Linux, Windows and macOS, because each platform has
  code that only it runs.
- **Tests** (`tests/`) and **App tests** (`apps/tests/`), on all three
  platforms, with both the oldest and the newest Python that Dasha Framework
  supports. The tests measure coverage as they run: the results appear on
  the run's summary page, and coverage below 90% fails the check.
- **Docs**: builds the documentation as Read the Docs does, treating every
  warning as an error.
- **Package**: builds the package as PyPI would receive it, checks it with
  twine, confirms that the wheel contains only `dasha`, then
  installs it in a clean environment and runs it.

A pull request that changes `.github/workflows/`, such as Dependabot's
updates to the actions, also runs **Dry run** (`dry-run.yml`). It builds the
package with `build.yml` exactly as a release does, downloads it again as
the release workflows do, and installs and runs it, but publishes nothing.
No other check runs those steps before a release does. It can also be run
by hand on any branch: Actions > Dry run > Run workflow.

A check fails when its command exits with a non-zero status. The checks run
the same commands as this guide, so running those yourself first saves a
round trip. Commits pushed directly to the default branch run none of them.

## Releasing

Dasha Framework is published by creating a release on GitHub. Two workflows in
`.github/workflows/` watch for one:

- **Pre-release** (`pre-release.yml`) runs when a release marked as a
  pre-release is published, and uploads the package to TestPyPI.
- **Release** (`release.yml`) runs when a full release is published, or
  when a pre-release is changed into a full release, and uploads the
  package to PyPI.

Both call `build.yml`, which checks that the release's tag is `v` followed
by `__version__` and that `CHANGELOG.md` has a dated section for that
version, then builds the package and checks it as the Package check does.
The built files are also attached to the GitHub release. Saving a draft
release runs nothing; publishing the draft does.

Before the first release, create two repository secrets (Settings >
Secrets and variables > Actions):

- `TEST_PYPI_API_TOKEN`: an API token from test.pypi.org.
- `PYPI_API_TOKEN`: an API token from pypi.org.

No username is needed with a token. Once the first upload has created the
`dasha-framework` project on each index, you can replace each token with one
limited to that project. GitHub creates the `testpypi` and `pypi`
environments the first time the workflows run. In the repository's
settings you can give them protection rules, such as a required reviewer.

To release a version:

1. In a pull request, set `__version__` in `src/dasha/__init__.py` and
   add a section for the version to `CHANGELOG.md`
   (`## [0.0.1] - 2026-11-14`), with its link at the bottom
   (`[0.0.1]: https://github.com/dashasierra/dasha-framework/releases/tag/v0.0.1`).
   The Tests check that both are there, and a release's build checks
   again, so a version cannot go out without them. Merge it once its
   checks pass.
2. On GitHub, draft a new release on the default branch with a new tag
   such as `v0.0.1`, using the version's changelog section as its notes.
   Tick "Set as a pre-release" and publish it. The Pre-release workflow
   uploads it to TestPyPI.
3. Install it from TestPyPI in a clean environment and try it out:

```bash
python -m pip install -i https://test.pypi.org/simple/ dasha-framework==0.0.1
```

4. Edit the release, untick "Set as a pre-release" and save it. The
   Release workflow uploads the same version to PyPI.

A release that is not marked as a pre-release goes straight to PyPI.

PyPI and TestPyPI never accept the same version twice, even after it has
been deleted. If a version needs fixing after it has been uploaded, release
a new version.

PyPI's *Trusted Publishing* is a more secure alternative to tokens: nothing
secret is stored in GitHub. To use it, add a trusted publisher on each
index for this repository, naming the workflow (`pre-release.yml` or
`release.yml`) and its environment (`testpypi` or `pypi`). Then give the
publishing job `permissions: id-token: write` and remove its `password`.

## Building dasha with PyInstaller

A PyInstaller build of dasha (`pyinstaller dasha.spec`) is a single program with
no Python interpreter alongside it: its `sys.executable` is dasha itself. The
desktop starts each application as `sys.executable -P -m dasha.host
TARGET`, so the build needs an entry point that understands that command,
and the spec needs four settings in its `Analysis`:

```python
a = Analysis(
    # Runs dasha, and the applications it starts.
    ['frozen/dasha_entry.py'],
    # Where dasha is: the entry script is not beside it.
    pathex=['src'],
    # Imported by name (by Application.run), so the analysis cannot see it.
    hiddenimports=['dasha.client'],
    # Its source files too, so the desktop can lend dasha to an
    # application in a virtual environment of its own.
    module_collection_mode={'dasha': 'pyz+py'},
    ...
)
```

`frozen/dasha_entry.py` treats `-m dasha.host ...` as Python would, and
anything else as the dasha command line. It also accepts `-P`, which
the desktop gives first so that a real Python does not import modules from
the folder it runs in; a build never does that anyway, so the option is
passed over. A copy of the built program named `dasha-desktop`
(`dasha-desktop.exe`) is the `dasha-desktop` command, `dasha desktop`.
`tests/test_frozen.py` checks the entry point against the very command the
desktop builds (`AppHost.start`), so the two cannot drift apart unnoticed.
Nothing in the package changes for the build, and the script is kept out of
`src/`, so installing Dasha Framework does not install it. In a build, an application without a virtual
environment runs on the built program itself, so a script started with
Run... can import only what the build contains: the standard library
modules that Dasha Framework uses, and Dasha Framework. For anything more, give the
application a virtual environment.

A build has no Python of its own to create virtual environments with, so
`install-app --create-venv` uses one found on `PATH` (`python3`, `python`
or the `py` launcher), or the one given with `--python`. It must be Python
3.12 or newer, which the lent copy of Dasha Framework requires. That copy is
named after the contents of its files, so a one-file build, which unpacks
itself afresh each time it starts, can still reuse it.

## Building the documentation

The documentation is built with Sphinx and published on Read the Docs
(`.readthedocs.yaml`). The guides in `docs/` are written in Markdown and read
by MyST. The API reference is generated from the docstrings and type hints,
with a page for each module (`docs/api.rst`; the pages are written into
`docs/api/` at build time). The colour and shortcut tables are generated
from `dasha.theme` and `dasha.shortcuts`
(`docs/_ext/dasha_tables.py`).

So document a class, function or constant in its docstring rather than in
the guides. Docstrings are written in reST (``` ``literal`` ```, and `::`
before an example), and a constant's docstring is a string placed just
after it. The example applications in `apps/` are not part of the API
reference.

The `docs` extra contains what the build needs (Sphinx, MyST and the Furo
theme):

```bash
python -m pip install -e ".[docs]"
```

```bash
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

The tutorial's programs and pictures are generated from code too.
`docs/tutorial/make_steps.py` writes steps 4 to 9 from the finished Notepad
(`apps/notepad.py`, which is the last step). `docs/tutorial/make_screens.py`
draws the screens that the tutorial shows, as colour PNG pictures, by
running the steps. Drawing them needs Pillow (in the `docs` extra) and the
DejaVu Sans Mono font, which it looks for wherever the system keeps fonts
(`--font` and `--bold-font` name others). After changing Notepad or a step,
run both from the repository's root:

```bash
python docs/tutorial/make_steps.py
```

```bash
python docs/tutorial/make_screens.py
```

`tests/test_tutorial.py` fails while either output is out of date. Each
picture also contains what it shows as text, so the test needs neither
Pillow nor the font. If Notepad changes in a way that `make_steps.py` cannot
follow, it stops and names the step that needs updating by hand.

`-W` turns every warning into an error, as Read the Docs does, so a
docstring that is not valid reST is caught. Open
`docs/_build/html/index.html` to read the result.

## Conventions

- **No third-party runtime dependencies.** `dependencies` in
  `pyproject.toml` stays empty. If something seems to need a library, build
  it on `ctypes` or another part of the standard library instead.
- **src layout.** The code lives under `src/dasha/`, and the tests
  import the installed package rather than the working tree.
- **Type hints** everywhere. mypy runs in strict mode, and the package
  ships a `py.typed` marker.
- **The version** is defined in one place only: `__version__` in
  `src/dasha/__init__.py`.
- **The example applications stay out of the package.** They live in
  `apps/` at the repository root rather than under `src/`, so that the wheel
  contains only the framework. Dasha Framework's code and tests never import them.
- **Examples pass arguments by name.** In `apps/`, in the tutorial, and in
  every example in the documentation (the README, these pages and the
  docstrings), every call into Dasha Framework, and to the example's own
  functions and methods, names its arguments
  (`Label(text="Name:", row=2, column=1)`, not `Label("Name:", 2, 1)`),
  because the examples are how newcomers learn what each argument is.
  Calls to built-in and standard library functions (`len`, `os.path.join`)
  are left as they are, since many of them accept nothing else, as are
  arguments that can only be given by position (`CLIPBOARD.get(*types)`).
  Callbacks that an application calls with an argument also take it by a
  fixed name: for example, Notepad's menu actions are `WindowAction`s,
  called as `act(window=...)`, and Terminal's are `ViewAction`s, called as
  `act(view=...)`. Signatures written out in the text, such as
  `confirm(title, message)`, name the parameters and are not examples.
- **Nothing reaches the terminal unfiltered.** The screen is drawn on a
  `Canvas`, whose `render` method shows control characters as pictures. A
  message printed directly on the terminal uses `dasha.printing.say`
  rather than `print`, because it may contain text from outside, such as an
  application's name, a file name or the last line of a log.
  `tests/test_escape_injection.py` checks both.
- **Code page 437 glyphs** for anything drawn on screen (frames, arrows,
  shading), so that every terminal font can show them. The source writes
  them as escapes (`"\N{FULL BLOCK}"`), not as the characters themselves.
- **British spelling**, such as "colour", "centre" and "grey", everywhere,
  with "-ise" rather than "-ize": in text shown on screen (Maximise, "not
  recognised"), in the documentation, and in names in the code (`maximise`,
  `normalise_key`).
- Files are UTF-8 with LF line endings (see `.editorconfig` and
  `.gitattributes`).
