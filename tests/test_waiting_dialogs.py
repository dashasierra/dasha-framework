"""Tests for dialogs that wait their turn: one application's dialog does not
take the keyboard from another's that is waiting for an answer."""

import unittest
from multiprocessing.connection import Connection

from dasha.dialog import Dialog
from dasha.hosting import AppHost, AppServer
from dasha.remote import RemoteWindow
from dasha.manager import PresentationManager
from dasha.protocol import Message
from dasha.shortcuts import Shortcuts
from dasha.statusbar import StatusBar
from tests.test_hosting import drain
from tests.support import pipe

DIVIDER = StatusBar.divider


def state(**changes: object) -> Message:
    """A window message from an application."""
    message: Message = {
        "type": "window", "id": 1, "title": "W", "rect": [2, 2, 8, 40],
        "maximised": False, "flags": [True, True, True, True], "look": "window",
        "modal": False, "outside": False, "status": "", "hints": [], "footer": [],
        "content": [0, 0], "scroll": [0, 0],
    }  # fmt: skip
    message.update(changes)
    return message


class WaitingTests(unittest.TestCase):
    """Notepad's Save as dialog is up when the Worker's Done dialog arrives."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(columns=80, lines=24)
        self.server = AppServer(manager=self.manager)
        self.addCleanup(self.server.stop_all, 0)
        self.manager.server = self.server
        self.notepad, self.notepad_end = self.host(name="Notepad")
        self.notepad.handle(message=state(title="Untitled"))
        self.worker, self.worker_end = self.host(name="Worker")
        self.worker.handle(message=state(title="Crunching", rect=[5, 30, 6, 30]))
        self.manager.bring_to_front(window=self.notepad.windows[1])
        self.save = self.dialog(host=self.notepad, title="Save as")

    def host(self, name: str) -> tuple[AppHost, Connection]:
        """An application at the end of a pipe."""
        host = AppHost(server=self.server, target="x:Y", name=name)
        app_end, desktop_end = pipe()
        host.connected(connection=desktop_end)
        self.server.hosts.append(host)
        self.manager.add_application(application=host.application)
        return host, app_end

    def dialog(self, host: AppHost, title: str) -> RemoteWindow:
        """A dialog of an application's, waiting for its answer."""
        host.handle(message=state(id=2, title=title, look="dialog", modal=True))
        return host.windows[2]

    def front(self) -> str:
        """The title of the window in front."""
        return self.manager.windows[-1].title

    def test_waits_behind(self) -> None:
        """The Worker's dialog goes just behind Notepad's, without the
        keyboard; asking to come forward does not get it there either."""
        done = self.dialog(host=self.worker, title="Done")
        self.assertEqual(self.front(), "Save as")
        self.assertIs(self.manager.windows[-2], done)
        self.worker.handle(message={"type": "request", "id": 2, "op": "front"})
        self.assertEqual(self.front(), "Save as")
        self.manager.windows[-1].handle_key(key="enter", shortcuts=Shortcuts())
        self.assertEqual(drain(self.worker_end), [])
        self.assertIn({"type": "key", "id": 2, "key": "enter"}, drain(self.notepad_end))

    def test_the_status_bar_says_so(self) -> None:
        """The status bar names the application whose dialog waits."""
        self.dialog(host=self.worker, title="Done")
        self.assertEqual(self.manager.status_owner, f"Notepad {DIVIDER} Worker waiting")

    def test_its_turn_comes(self) -> None:
        """Once Notepad's dialog is answered, the Worker's comes forward, with
        the keyboard, and the Worker is the active application."""
        self.dialog(host=self.worker, title="Done")
        self.notepad.handle(message={"type": "close", "id": 2})
        self.assertEqual(self.front(), "Done")
        self.assertIs(self.manager.active_application, self.worker.application)
        self.assertEqual(self.manager.status_owner, "Worker")
        self.assertEqual(self.manager.waiting, [])

    def test_behind_the_active_applications_work(self) -> None:
        """Nothing waiting for an answer in front, but Notepad is still the
        active application: the Worker's dialog waits behind Notepad's
        window, not taking what the user types, and the status bar says so.
        Switching to the Worker brings it forward."""
        self.notepad.handle(message={"type": "close", "id": 2})
        self.dialog(host=self.worker, title="Done")
        self.assertEqual(self.front(), "Untitled")
        self.assertEqual(self.manager.status_owner, f"Notepad {DIVIDER} Worker waiting")
        self.manager.switch_to(application=self.worker.application)
        self.assertEqual(self.front(), "Done")
        self.assertEqual(self.manager.status_owner, "Worker")
        titles = [menu.title for menu in self.manager.bar_menus()]
        self.assertEqual(self.manager.inert_menus(), list(range(1, len(titles))))

    def test_the_same_applications_dialog_comes_forward(self) -> None:
        """Notepad's own next dialog (Replace it?) opens on top of its first."""
        self.notepad.handle(
            message=state(id=3, title="Replace?", look="dialog", modal=True)
        )
        self.assertEqual(self.front(), "Replace?")

    def test_waits_behind_the_desktops_own(self) -> None:
        """The desktop's own dialog (Shutdown, say) is not interrupted."""
        self.notepad.handle(message={"type": "close", "id": 2})
        shutdown = Dialog(title="Exit", width=30, height=6)
        shutdown.modal = True  # as execute() marks it
        self.manager.add(window=shutdown)
        self.dialog(host=self.worker, title="Done")
        self.assertIs(self.manager.windows[-1], shutdown)
        self.assertEqual(self.manager.status_owner, f"Notepad {DIVIDER} Worker waiting")

    def test_chosen_by_the_user(self) -> None:
        """Clicking the waiting dialog brings it forward: the user's choice."""
        done = self.dialog(host=self.worker, title="Done")
        self.manager.bring_to_front(window=done)
        self.assertEqual(self.front(), "Done")
        self.assertEqual(self.manager.status_owner, f"Worker {DIVIDER} Notepad waiting")


if __name__ == "__main__":
    unittest.main()
