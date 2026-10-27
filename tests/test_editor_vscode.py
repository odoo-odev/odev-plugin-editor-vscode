"""Tests for the configuration files generated for VSCode."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, PropertyMock, patch

from jinja2 import Environment, FileSystemLoader

import odev
from odev.common.databases import LocalDatabase
from odev.common.python import PythonEnv
from odev.common.version import OdooVersion

from odev.plugins.odev_plugin_editor_vscode.common.editor_vscode import VSCodeEditor


PLUGIN_PATH = Path(__file__).resolve().parents[1]
ODEV_PATH = Path(odev.__file__).resolve().parents[1]


class TestVSCodeEditor(TestCase):
    """Check the workspace and launch configurations rendered for a local database."""

    def setUp(self):
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.project_path = Path(temporary_directory.name) / "project"
        self.project_path.mkdir()

        database = MagicMock(spec=LocalDatabase)
        database.name = "test"
        database.worktree = "20.0"
        database.odev = MagicMock()
        database.odev.path = ODEV_PATH
        self.worktrees_path = Path(temporary_directory.name) / "worktrees"
        database.odev.worktrees_path = self.worktrees_path
        database.venv = MagicMock()
        self.odoo_python = Path(temporary_directory.name) / "virtualenvs/20.0/bin/python"
        database.venv.python = self.odoo_python

        self.database = database
        self.editor = VSCodeEditor(database, repository="test/project")

        for name, value in (
            ("path", self.project_path),
            ("templates", Environment(loader=FileSystemLoader(PLUGIN_PATH / "templates"))),  # noqa: S701
        ):
            patcher = patch.object(VSCodeEditor, name, new_callable=PropertyMock, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.editor.workspace_directory.mkdir()

    def _add_module(self, name: str):
        """Create an empty Odoo module in the project."""
        module_path = self.project_path / name
        module_path.mkdir()
        (module_path / "__manifest__.py").write_text("{}")

    def _workspace_text(self) -> str:
        """Render the workspace file and read it."""
        self.editor._create_workspace()

        return self.editor.workspace_path.read_text()

    def _workspace_setting(self, name: str) -> str:
        """Read the value of a setting in the rendered workspace file."""
        setting = re.search(rf'"{re.escape(name)}": "([^"]*)"', self._workspace_text())

        if setting is None:
            raise AssertionError(f"Setting {name!r} is missing from the workspace")

        return setting.group(1)

    def test_01_odev_path_is_the_entry_point(self):
        """The debugger needs a python file to run, it does not look for programs in the PATH."""
        odev_path = Path(self._workspace_setting("odevPath"))

        self.assertTrue(odev_path.is_absolute())
        self.assertTrue(odev_path.is_file())
        self.assertEqual(odev_path.name, "main.py")

    def test_02_python_path_is_odev_interpreter(self):
        """Odev must run with its own interpreter, not with the one of the Odoo version."""
        self.assertEqual(self._workspace_setting("pythonPath"), PythonEnv().python.as_posix())
        self.assertNotEqual(self._workspace_setting("pythonPath"), self.odoo_python.as_posix())

    def test_03_launch_runs_odev_with_its_interpreter(self):
        """Every configuration going through odev must run its entry point with its interpreter."""
        self.editor._create_launch()
        configurations = self.editor.launch_path.read_text().split('"name": ')[1:]
        through_odev = [configuration for configuration in configurations if "${config:odevPath}" in configuration]

        self.assertEqual(len(through_odev), 3)

        for configuration in through_odev:
            self.assertIn('"python": "${config:pythonPath}"', configuration)

    def test_04_modules_default_to_suite(self):
        """The suite module is expected to depend on the other modules of the project."""
        self._add_module("test_suite")
        self._add_module("test_sale")

        self.assertEqual(self._workspace_setting("odoo.modules"), "test_suite")

    def test_05_modules_default_to_project_modules(self):
        """Without a suite module, all modules of the project are selected."""
        self._add_module("test_sale")
        self._add_module("test_account")
        (self.project_path / "scripts").mkdir()

        self.assertEqual(self._workspace_setting("odoo.modules"), "test_account,test_sale")

    def test_06_modules_default_to_base(self):
        """A project without modules must not select a module that does not exist."""
        self.assertEqual(self._workspace_setting("odoo.modules"), "base")

    def test_07_odoo_path_uses_the_database_worktree(self):
        """The Odoo folder of the workspace is the worktree the database runs on."""
        self.assertEqual(self.editor.odoo_path, self.worktrees_path / "20.0")

    def test_08_odoo_path_defaults_to_the_version(self):
        """A database that was never run has no worktree yet, its version tells which one it will use."""
        self.database.worktree = None
        self.database.version = OdooVersion("19.0")

        self.assertEqual(self.editor.odoo_path, self.worktrees_path / "19.0")
        self.assertIn(f'"path": "{self.worktrees_path}/19.0"', self._workspace_text())
