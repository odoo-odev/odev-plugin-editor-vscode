import json
from pathlib import Path
from typing import cast

from odev.common import progress, string
from odev.common.console import console
from odev.common.databases import LocalDatabase
from odev.common.logging import logging
from odev.common.python import PythonEnv

from odev.plugins.ps_tech_odev_editor_base.common.editor import Editor


logger = logging.getLogger(__name__)


class VSCodeEditor(Editor):
    """Class meant for interacting with VSCode."""

    _name = "code"
    _display_name = "VSCode"

    @property
    def command(self) -> str:
        if isinstance(self.database, LocalDatabase):
            return f"{self._name} {self.workspace_path}"
        else:
            return super().command

    @property
    def workspace_directory(self) -> Path:
        """The path to the workspace directory."""
        return self.path / ".vscode"

    @property
    def workspace_path(self) -> Path:
        """The path to the workspace file."""
        return self.workspace_directory / f"{self.database.name}.code-workspace"

    @property
    def launch_path(self) -> Path:
        """The path to the launch file."""
        return self.workspace_directory / "launch.json"

    @property
    def tasks_path(self) -> Path:
        """The path to the tasks file."""
        return self.workspace_directory / "tasks.json"

    def configure(self):
        """Configure VSCode to work with the database."""
        if not isinstance(self.database, LocalDatabase):
            return logger.warning(
                f"No local database associated with repository {self.git.name!r}, skipping VSCode configuration"
            )

        with progress.spinner(f"Configuring {self._display_name} for project {self.git.name!r}"):
            self.workspace_directory.mkdir(parents=True, exist_ok=True)

            missing_files = filter(
                lambda path: not path.is_file(),
                [self.workspace_path, self.launch_path, self.tasks_path],
            )

            if not list(missing_files):
                return logger.debug("VSCode config files already exist")

            self._create_workspace()
            self._create_launch()
            self._create_tasks()

            created_files = string.join_bullet(
                [
                    f"Workspace: {self.workspace_path}",
                    f"Debugging: {self.launch_path}",
                    f"Tasks: {self.tasks_path}",
                ],
            )
            logger.info(f"Created VSCode config for project {self.git.name!r}\n{created_files}")

    def _create_workspace(self):
        """Create a workspace file for the project."""
        assert isinstance(self.database, LocalDatabase)

        if self.workspace_path.is_file():
            return logger.debug("Workspace file already exists")

        workspace_config = {
            "folders": [{"path": ".."}],
            "settings": {
                "terminal.integrated.cwd": self.path.as_posix(),
                "python.defaultInterpreterPath": self.database.venv.python.as_posix(),
            },
        }

        for worktree in self.database.worktrees:
            cast(list, workspace_config["folders"]).append({"path": worktree.path.as_posix()})

        console.print(json.dumps(workspace_config, indent=4), file=self.workspace_path)

    def _create_launch(self):
        """Create a launch file for the project."""
        if self.launch_path.is_file():
            return logger.debug("Launch file already exists")

        def run_config(shell: bool = False):
            title = "Shell" if shell else "Run"
            return {
                "name": title,
                "type": "debugpy",
                "request": "launch",
                "subProcess": True,
                "justMyCode": True,
                "console": "integratedTerminal",
                "consoleName": f"Odev {title} ({self.database.name})",
                "cwd": self.path.as_posix(),
                "program": self.database.odev.executable.readlink().as_posix(),
                "python": PythonEnv().python.as_posix(),
                "args": [
                    title.lower(),
                    self.database.name,
                    "--log-handler=odoo.addons.base.models.ir_attachment:WARNING",
                    "--limit-time-cpu=0",
                    "--limit-time-real=0",
                ],
            }

        launch_config = {
            "version": "0.2.0",
            "configurations": [
                run_config(),
                run_config(True),
                {
                    "name": "Attach Debugger",
                    "type": "debugpy",
                    "request": "attach",
                    "processId": "${command:pickProcess}",
                },
            ],
        }

        console.print(json.dumps(launch_config, indent=4), file=self.launch_path)

    def _create_tasks(self):
        """Create a tasks file for the project."""
        if self.tasks_path.is_file():
            return logger.debug("Tasks file already exists")

        tasks_config = {
            "version": "2.0.0",
            "tasks": [],
        }

        console.print(json.dumps(tasks_config, indent=4), file=self.tasks_path)
