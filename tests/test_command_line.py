"""Tests for starting applications by name: ``dasha APP ...``, ``dasha
desktop [APP ...]`` and ``dasha-desktop [APP ...]``, and the Applications menu,
which offer what is installed."""

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest import mock

from dasha import registry
from dasha.__main__ import (
    _desktop,
    _parse_arguments,
    _report_unsaid,
    _startup,
    desktop_main,
    main,
)
from dasha.hosting import AppServer
from dasha.manager import PresentationManager
from dasha.registry import AppEntry, write_manifest
from tests.hosted_apps import Hangs, Hello
from tests.support import isolated_home, started


class CommandLineTests(unittest.TestCase):
    """``dasha APP ...``, ``dasha desktop [APP ...]`` and ``dasha-desktop``."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        # Nothing the user has installed.
        patcher = mock.patch.object(registry, "MANIFEST_FOLDER", Path(folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, *entries: AppEntry) -> None:
        """Install applications, as install-app would."""
        for entry in entries:
            write_manifest(entry, registry.MANIFEST_FOLDER)

    def offered(self, manager: PresentationManager) -> list[str]:
        """What the Applications menu lists."""
        submenu = manager.system_menu.items[1].submenu
        assert submenu is not None
        return [item.label for item in submenu.items]

    def test_nothing_comes_with_dasha(self) -> None:
        """With nothing installed, an empty desktop offering nothing: the
        Applications menu says so, greyed out."""
        manager = _desktop(None, [], processes=False)
        self.assertEqual(manager.windows, ())
        submenu = manager.system_menu.items[1].submenu
        assert submenu is not None
        self.assertEqual(self.offered(manager), ["(None installed)"])
        self.assertFalse(submenu.items[0].is_available)

    def test_installed_apps_offered(self) -> None:
        """Every installed application is in the menu."""
        self.install(AppEntry.of(Hello), AppEntry.of(Hangs))
        manager = _desktop(None, [], processes=False)
        self.assertEqual(self.offered(manager), ["&Hangs", "&Hello"])

    def test_named_apps_start(self) -> None:
        """Names on the command line start those apps (here in this process:
        installed ones each start a process of their own)."""
        entries = {"hello": AppEntry.of(Hello), "hangs": AppEntry.of(Hangs)}
        manager = _desktop(None, ["hello", "hangs"], processes=False, entries=entries)
        self.assertEqual([type(app) for app in manager.applications], [Hello, Hangs])

    def test_named_apps_run_alone(self) -> None:
        """``dasha hello`` is Hello on its own, as its script runs it: no
        system menu, the exit key asks to close Hello, and Dasha Framework ends
        when Hello does."""
        entries = {"hello": AppEntry.of(Hello), "hangs": AppEntry.of(Hangs)}
        manager = _desktop(
            None, ["hello"], processes=False, entries=entries, alone=True
        )
        self.assertFalse(manager.show_system_menu)
        self.assertNotIn(manager.system_menu, manager.bar_menus())
        self.assertEqual(
            (manager.exit_title, manager.exit_message), ("Hello", "Close Hello?")
        )
        manager._running = True  # pylint: disable=protected-access
        manager.applications[0].quit()
        self.assertFalse(manager.is_running)
        several = _desktop(
            None, ["hello", "hangs"], processes=False, entries=entries, alone=True
        )
        self.assertEqual(several.exit_message, "Close Hello and Hangs?")

    def test_the_desktop_has_its_menu(self) -> None:
        """``dasha`` alone is the desktop, with its system menu."""
        manager = _desktop(None, [], processes=False)
        self.assertTrue(manager.show_system_menu)
        self.assertFalse(manager.quit_when_empty)

    def test_by_id_or_by_name(self) -> None:
        """An application can be named by its id, in any case, or by what it
        is called, in any case; an id comes first, and the ids are what
        start."""
        self.install(
            AppEntry.of(Hello),
            replace(AppEntry.of(Hangs), id="dasha-github", name="Git"),
        )
        for given, expected in (
            ("hello", "hello"),
            ("HELLO", "hello"),
            ("dasha-github", "dasha-github"),
            ("git", "dasha-github"),
            ("GIT", "dasha-github"),
        ):
            with self.subTest(given=given):
                found = _startup([given])
                assert found is not None
                self.assertEqual(found[1], [expected])
        self.install(replace(AppEntry.of(Hello), id="git", name="Other"))
        found = _startup(["git"])
        assert found is not None
        self.assertEqual(found[1], ["git"])  # the id, not dasha-github's name
        found = _startup(["Git"], desktop=True)
        assert found is not None
        self.assertEqual(found[1], ["git"])  # the id in another case

    def test_a_name_too_many_have(self) -> None:
        """A name more than one application has is refused, with their ids,
        and nothing starts; an id still picks one."""
        self.install(
            replace(AppEntry.of(Hello), id="git-one", name="Git"),
            replace(AppEntry.of(Hangs), id="git-two", name="git"),
        )
        err = StringIO()
        with redirect_stderr(err):
            self.assertIsNone(_startup(["git"]))
        self.assertIn('more than one application is called "git"', err.getvalue())
        self.assertIn("git-one, git-two", err.getvalue())
        self.assertIn("by its id", err.getvalue())
        found = _startup(["git-two"])
        assert found is not None
        self.assertEqual(found[1], ["git-two"])

    def test_named_and_autostart_once(self) -> None:
        """An application named by name, and also autostart's, starts once."""
        self.install(AppEntry.of(Hello), AppEntry.of(Hangs))
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.toml"
            settings.write_text('autostart = ["hangs"]\n', encoding="utf-8")
            with mock.patch.object(registry, "SETTINGS_PATH", settings):
                found = _startup([AppEntry.of(Hangs).name, "Hello"], desktop=True)
        assert found is not None
        self.assertEqual(found[1], ["hangs", "hello"])

    def test_named_apps_leave_out_autostart(self) -> None:
        """Applications named alone start without autostart's; the desktop
        starts autostart's, then those named that are not among them."""
        self.install(AppEntry.of(Hello), AppEntry.of(Hangs))
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.toml"
            settings.write_text('autostart = ["hangs"]\n', encoding="utf-8")
            with mock.patch.object(registry, "SETTINGS_PATH", settings):
                named = _startup(["hello"])
                desktop = _startup([], desktop=True)
                both = _startup(["hello", "hangs"], desktop=True)
        assert named is not None and desktop is not None and both is not None
        self.assertEqual((named[1], desktop[1]), (["hello"], ["hangs"]))
        self.assertEqual(both[1], ["hangs", "hello"])

    def test_what_it_could_not_say(self) -> None:
        """Ended before it could show it (the only application could not
        start), the desktop's message is said on the terminal."""
        manager = _desktop(None, [], processes=False)
        server = AppServer(manager)
        self.addCleanup(server.stop_all, 0)
        manager.server = server
        server.notices.append(("Cannot start", "Cannot start Hello:\nno such script"))
        err = StringIO()
        with redirect_stderr(err):
            _report_unsaid(manager)
        self.assertIn(
            "Cannot start: Cannot start Hello: no such script", err.getvalue()
        )

    def test_list_apps_with_none(self) -> None:
        """list-apps says when nothing is installed."""
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["list-apps"]), 0)
        self.assertIn("No applications are installed", out.getvalue())

    def test_short_options(self) -> None:
        """Each short option is the same as its long one."""
        short = _parse_arguments(
            ["-s", "keys.json", "-c", "colours.json", "-d", "16", "-m", "-k", "demo"]
        )
        long = _parse_arguments(
            [
                "--shortcuts",
                "keys.json",
                "--colours",
                "colours.json",
                "--colour-depth",
                "16",
                "--show-mouse",
                "--key-test",
                "demo",
            ]
        )
        self.assertEqual(short, long)
        self.assertEqual(short.colour_depth, "16")
        self.assertEqual(short.apps, ["demo"])
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            _parse_arguments(["-v"])
        self.assertIn("Dasha Framework", out.getvalue())

    def test_something_to_run_is_required(self) -> None:
        """With no application, and not desktop, the usage and an error
        are shown, as for any mistake in the arguments (exit code 2)."""
        isolated_home(self)
        for arguments in ([], ["--monochrome"], ["-d", "16", "-m"]):
            err = StringIO()
            with (
                self.subTest(arguments=arguments),
                redirect_stderr(err),
                self.assertRaises(SystemExit) as stopped,
            ):
                main(arguments)
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("usage: dasha", err.getvalue())
            self.assertIn("arguments are required: APP (desktop", err.getvalue())

    def test_desktop_or_alone(self) -> None:
        """desktop, first, is the desktop, with any applications after it
        started on it; applications without it run alone. dasha-desktop is
        dasha desktop, and options may come anywhere."""
        cases: tuple[tuple[list[str], bool, tuple[bool, list[str]]], ...] = (
            (["notepad"], False, (False, ["notepad"])),
            (["notepad", "demo"], False, (False, ["notepad", "demo"])),
            (["desktop"], False, (True, [])),
            (["desktop", "-m", "notepad", "demo"], False, (True, ["notepad", "demo"])),
            ([], True, (True, [])),
            (["notepad", "-m", "demo"], True, (True, ["notepad", "demo"])),
            (["desktop", "notepad"], True, (True, ["notepad"])),
        )
        for arguments, desktop, expected in cases:
            with self.subTest(arguments=arguments, dasha_desktop=desktop):
                args = _parse_arguments(arguments, desktop=desktop)
                self.assertEqual((args.desktop, args.apps), expected)

    def test_what_needs_no_application(self) -> None:
        """The key test, and writing settings files, need none."""
        for arguments in (["-k"], ["--init-shortcuts"], ["--init-colours"]):
            with self.subTest(arguments=arguments):
                self.assertFalse(_parse_arguments(arguments).apps)
        self.assertFalse(_parse_arguments(["--init-theme", "Sea"]).desktop)

    def test_dasha_desktop(self) -> None:
        """dasha-desktop starts the desktop, with the named applications on it
        (not alone), as dasha desktop does; dasha alone runs them alone."""
        isolated_home(self)
        self.install(AppEntry.of(Hello))
        runs = (
            started(desktop_main, ["hello"]),
            started(main, ["desktop", "hello"]),
            started(main, ["hello"]),
        )
        calls = [
            (code, desktop.call_args.args[1], desktop.call_args.kwargs["alone"])
            for code, desktop, _ in runs
        ]
        self.assertEqual(
            calls, [(0, ["hello"], False), (0, ["hello"], False), (0, ["hello"], True)]
        )

    def test_unknown_app(self) -> None:
        """An unknown name is reported before the screen is taken over. (The
        user's own settings and colours are kept out of it, and the theme it
        applies is put back.)"""
        err = StringIO()
        isolated_home(self)
        with redirect_stderr(err):
            self.assertEqual(main(["solitaire"]), 1)
        self.assertIn("no application called solitaire", err.getvalue())
        self.assertIn("none are installed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
