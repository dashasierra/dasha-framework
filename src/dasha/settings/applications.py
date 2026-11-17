"""Settings...' Applications page: the installed applications, to install
more and uninstall them, as ``dasha install-app``, ``uninstall-app``
and ``list-apps`` do.

Installing and uninstalling happen at once, whether the other settings are
kept or not, and the Applications menu changes to match. Making a virtual
environment, and installing packages into it with pip, are left to
``dasha install-app``, which shows what pip does as it does it.
"""

from dataclasses import replace
from typing import TYPE_CHECKING

from dasha import install, registry
from dasha.dialog import confirm, question
from dasha.registry import AppEntry, ManifestError, is_script, slug, venv_python
from dasha.rundialog import RunDialog
from dasha.widgets import Button, CheckBoxes, Column, Label, Table, TextBox, Widget
from dasha.widgets.tabs import TabPage
from dasha.settings.lists import stay_open

if TYPE_CHECKING:
    from dasha.settings import SettingsDialog


class InstallDialog(RunDialog):
    """Ask what to install: Run...'s program, class and virtual
    environment, with the name the Applications menu gives it, the group it
    is listed in, and whether only one may run at a time, among the
    options. OK answers ``"ok"`` with ``entry`` set, once it is complete."""

    OPTIONS_HEIGHT = 8

    def __init__(self) -> None:
        super().__init__()
        self.title = "Install"
        self.status = "Install an application, for the Applications menu"
        self.options.add(Label("Name in the menu", 5, 2))
        self.name_box = self.options.add(
            TextBox(
                5, 24, 24, name="app_name", status="Blank: from the class or script"
            )
        )
        self.options.add(Label("Group (a submenu)", 6, 2))
        self.group_box = self.options.add(
            TextBox(6, 24, 24, name="group", status="Blank: listed on its own")
        )
        self.single = self.options.add(
            CheckBoxes(["Only one at a &time"], 7, 2, name="single_instance")
        )

    def accept(self) -> None:
        super().accept()
        if self.entry is None:
            return
        name = self.name_box.text.strip() or self.entry.name
        self.entry = replace(
            self.entry,
            id=slug(name),
            name=name,
            group=self.group_box.text.strip(),
            single_instance=self.single.checked[0],
        )


class ApplicationsPage:  # pylint: disable=too-few-public-methods
    """A table of the installed applications, with Install... and
    Uninstall."""

    def __init__(self, dialog: "SettingsDialog", page: TabPage) -> None:
        self.dialog = dialog
        self.manager = dialog.desktop_manager
        self.entries: list[AppEntry] = []
        self.table = page.add(
            Table(
                [
                    Column("Id", 14),
                    Column("Name", 18),
                    Column("Group", 12),
                    Column("Runs", 24),
                ],
                0,
                0,
                72,
                10,
                on_choose=stay_open,
                name="applications",
                status="The installed applications",
            )
        )
        page.add(Button("I&nstall...", 11, 1, action=self._install, name="install"))
        page.add(Button("&Uninstall", 11, 18, action=self._uninstall, name="uninstall"))
        page.add(Label("Installing and uninstalling happen at once.", 13, 1))
        self.refresh()

    def refresh(self) -> None:
        """Show the applications installed now."""
        entries, _ = registry.load_manifests(registry.MANIFEST_FOLDER)
        self.entries = sorted(entries, key=lambda entry: entry.id)
        self.table.set_rows(
            [entry.id, entry.name, entry.group, entry.target] for entry in self.entries
        )

    def _install(self, button: Widget) -> None:
        del button
        dialog = InstallDialog()
        if self.dialog.ask(dialog) != "ok" or dialog.entry is None:
            return
        entry = dialog.entry
        if registry.reserved_id_problem(entry.id):
            self.dialog.problem(
                "Install",
                f'Its id would be "{entry.id}", which dasha\n'
                "keeps for the desktop. Give it another name.",
            )
            return
        path = registry.MANIFEST_FOLDER / f"{entry.id}.toml"
        if path.exists():
            replacing = confirm(
                "Install", f'"{entry.id}" is installed already.\nReplace it?'
            )
            if self.dialog.ask(replacing) != "ok":
                return
        module = entry.target.partition(":")[0]
        python = venv_python(entry.venv) if entry.venv else None
        if not is_script(entry.target) and not install.module_found(module, python):
            where = "its virtual environment" if entry.venv else "Dasha Framework"
            self.dialog.problem("Install", f"{module} cannot be imported by {where}.")
            return
        try:
            installed = registry.read_manifest(
                registry.write_manifest(entry, registry.MANIFEST_FOLDER)
            )
        except (OSError, ManifestError) as error:
            self.dialog.problem("Install", f"It could not be installed:\n{error}")
            return
        self.manager.register(installed)
        self._changed()

    def _uninstall(self, button: Widget) -> None:
        del button
        index = self.table.value
        if not isinstance(index, int):
            return
        entry = self.entries[index]
        answers = [("&Uninstall", "uninstall")]
        if install.made_venv(entry) is not None:
            answers.append(("Also &delete its environment", "venv"))
        answers.append(("&Cancel", "cancel"))
        answer = self.dialog.ask(
            question("Uninstall", f"Uninstall {entry.name} ({entry.id})?", answers)
        )
        if answer not in ("uninstall", "venv"):
            return
        try:
            install.remove_application(entry.id, remove_venv=answer == "venv")
        except (OSError, ManifestError) as error:
            self.dialog.problem("Uninstall", f"It could not be uninstalled:\n{error}")
            return
        self.manager.unregister(entry.id)
        self._changed()

    def _changed(self) -> None:
        self.refresh()
        self.dialog.desktop.refresh()
