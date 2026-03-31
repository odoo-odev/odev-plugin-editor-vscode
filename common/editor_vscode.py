import json
from pathlib import Path

from odev.common import bash, progress, string
from odev.common.databases import LocalDatabase
from odev.common.logging import logging
from odev.common.odoobin import OdoobinProcess
from odev.plugins.odev_plugin_editor_base.common.editor import Editor

logger = logging.getLogger(__name__)


class VSCodeEditor(Editor):
    """Class meant for interacting with VSCode."""

    _name = "code"
    _display_name = "VSCode"

    @property
    def display_name(self) -> str:
        """Also handle other editors derivated from VSCodium (e.g. Antigravity)."""
        name = bash.execute(f"{self._name} --help | head -n 1 | awk '{{print $1}}'")

        if name and name.stdout.strip():
            return name.stdout.strip().capitalize().decode()

        return self._display_name

    @property
    def command(self) -> str:
        return f"{self._name} {self.workspace_path}"

    @property
    def workspace_directory(self) -> Path:
        """The path to the workspace directory."""
        return (
            self.path / ".vscode"
            if isinstance(self.database, LocalDatabase)
            else self.path
        )

    @property
    def workspace_path(self) -> Path:
        """The path to the workspace file."""
        name = self.database.name if isinstance(self.database, LocalDatabase) else str(self.version)
        return self.workspace_directory / f"{name}.code-workspace"

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
        if not isinstance(self.database, LocalDatabase) and not self.version:
            return logger.warning(
                f"No local database associated with repository {self.git.name!r}, "
                f"skipping {self.display_name} configuration"
            )

        # We always want to update the configuration to ensure the Python environment is correct
        # even if the workspace file already exists.

        with progress.spinner(f"Configuring {self.display_name} for project {self.git.name!r}"):
            self.workspace_directory.mkdir(parents=True, exist_ok=True)

            created_files_list = []

            if self._create_workspace():
                created_files_list.append(f"Workspace: {self.workspace_path}")

            self._create_launch()
            self._create_tasks()
            created_files_list.extend([
                f"Debugging: {self.launch_path}",
                f"Tasks: {self.tasks_path}",
            ])

            created_files = string.join_bullet(created_files_list)
            logger.info(f"Created {self.display_name} config for project {self.git.name!r}\n{created_files}")

    def _create_workspace(self) -> bool:
        """Create a workspace file for the project."""
        workspace_config = {}
        if self.workspace_path.is_file():
            try:
                workspace_config = json.loads(self.workspace_path.read_text())
            except Exception:
                logger.warning(f"Could not load existing workspace file {self.workspace_path}")

        if not workspace_config:
            workspace_config = {
                "folders": [],
                "settings": {},
            }

        workspace_config["settings"]["terminal.integrated.cwd"] = self.path.as_posix()

        process = (
            self.database.process
            if isinstance(self.database, LocalDatabase) and self.database.process
            else OdoobinProcess(self.database, version=self.version).with_edition("enterprise")
        )

        if isinstance(self.database, LocalDatabase):
            if {"path": ".."} not in workspace_config["folders"]:
                workspace_config["folders"].append({"path": ".."})

            python_path = process.venv.python.as_posix()
            workspace_config["settings"]["python.defaultInterpreterPath"] = python_path
            # Set interpreterPath as well for better compatibility with different editor versions
            workspace_config["settings"]["python.interpreterPath"] = python_path

            # Add extra paths for better autocompletion
            extra_paths = [p.as_posix() for p in process.addons_paths if p.exists()]
            workspace_config["settings"]["python.analysis.extraPaths"] = extra_paths
            workspace_config["settings"]["python.autoComplete.extraPaths"] = extra_paths

            # Force Ruff extension to use the binary from the venv
            ruff_bin = (process.venv.path / "bin" / "ruff").as_posix()
            workspace_config["settings"]["ruff.path"] = [ruff_bin]
            workspace_config["settings"]["ruff.importStrategy"] = "fromEnvironment"

        for worktree in process.odoo_worktrees:
            worktree_path = {"path": worktree.path.as_posix()}
            if worktree_path not in workspace_config["folders"]:
                workspace_config["folders"].append(worktree_path)

        self.workspace_path.write_text(json.dumps(workspace_config, indent=4))
        return True

    def _create_launch(self):
        """Create a launch file for the project."""
        process = (
            self.database.process
            if isinstance(self.database, LocalDatabase) and self.database.process
            else OdoobinProcess(self.database, version=self.version).with_edition("enterprise")
        )

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
                "program": self.database.odev.executable.as_posix(),
                "python": process.venv.python.as_posix(),
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

        self.launch_path.write_text(json.dumps(launch_config, indent=4))

    def _create_tasks(self):
        """Create a tasks file for the project."""

        tasks_config = {
            "version": "2.0.0",
            "tasks": [],
        }

        self.tasks_path.write_text(json.dumps(tasks_config, indent=4))
