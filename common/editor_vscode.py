import json
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from odev.common import bash, progress, string
from odev.common.databases import LocalDatabase
from odev.common.logging import logging
from odev.common.odoobin import OdoobinProcess
from odev.common.python import PythonEnv

from odev.plugins.odev_plugin_editor_base.common.editor import Editor


logger = logging.getLogger(__name__)


class VSCodeEditor(Editor):
    """Class meant for interacting with VSCode."""

    _name = "code"
    _display_name = "VSCode"

    @property
    def display_name(self) -> str:
        """Also handle other editors derivated from VSCodium (e.g. Antigravity)."""
        result = bash.execute(f"{self._name} --help", raise_on_error=False)

        if result and result.stdout:
            first_line = result.stdout.decode().splitlines()[0]
            name = re.sub(r"\s+v?[\d.]+.*$", "", first_line).strip()

            if name:
                return name

        return self._display_name

    @property
    def process(self) -> OdoobinProcess:
        """Odoo process backing the configuration.

        Falls back to a version-based process when no local database exists, so that
        repositories opened without a database (version-only) can still be configured.
        """
        if isinstance(self.database, LocalDatabase) and self.database.process:
            return self.database.process
        return OdoobinProcess(self.database, version=self.version).with_edition("enterprise")

    @property
    def command(self) -> str:
        return f"{self._name} {self.workspace_path}"

    @property
    def templates(self) -> Environment:
        return Environment(  # noqa: S701
            loader=FileSystemLoader(self.database.odev.plugins_path / "odev_plugin_editor_vscode/templates")
        )

    @property
    def odoo_path(self) -> Path:
        """The path to the worktree holding the Odoo sources (odoo, enterprise, ...)."""
        return self.database.odev.worktrees_path / self.process.worktree

    @property
    def workspace_directory(self) -> Path:
        """The path to the workspace directory."""
        return self.path / ".vscode" if isinstance(self.database, LocalDatabase) else self.path

    @property
    def workspace_name(self) -> str:
        """The base name used for the workspace file."""
        return self.database.name if isinstance(self.database, LocalDatabase) else str(self.version)

    @property
    def workspace_path(self) -> Path:
        """The path to the workspace file."""
        return self.workspace_directory / f"{self.workspace_name}.code-workspace"

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

        config_files = [self.workspace_path, self.launch_path, self.tasks_path, self.path / "jsconfig.json"]

        if all(path.is_file() for path in config_files):
            logger.debug(f"{self.display_name} config files already exist, skipping configuration")
            return None

        with progress.spinner(f"Configuring {self.display_name} for project {self.git.name!r}"):
            self.workspace_directory.mkdir(parents=True, exist_ok=True)

            self._create_workspace()
            self._create_launch()
            self._create_tasks()
            self._create_jsconfig()

            created_files = string.join_bullet(
                [
                    f"Workspace: {self.workspace_path}",
                    f"Launch: {self.launch_path}",
                    f"Tasks: {self.tasks_path}",
                ],
            )
            logger.info(f"Created {self.display_name} config for project {self.git.name!r}\n{created_files}")
        return None

    def _get_rendered_template(self, template_name, **kwargs):
        template = self.templates.get_template(template_name)
        return template.render(kwargs)

    @property
    def workspace_folders(self) -> list[dict]:
        """The multi-root workspace folders, depending on the configured layout.

        - 'flat' (default): one top-level root per odoo worktree alongside the project.
        - 'nested': a single 'odoo' root holding all worktrees as subfolders.
        """
        project_folder = {"path": "..", "name": "project"}
        layout = self.database.odev.config.vscode.workspace_layout

        if layout == "flat":
            return [
                project_folder,
                *(
                    {"path": worktree.path.as_posix(), "name": worktree.path.name}
                    for worktree in self.process.odoo_worktrees
                ),
            ]

        return [project_folder, {"path": self.odoo_path.as_posix(), "name": "odoo"}]

    def _create_workspace(self):
        """Create a workspace file for the project."""
        rendered_template = self._get_rendered_template(
            "code-workspace.jinja",
            DB_NAME=self.workspace_name,
            ODOO_PATH=self.odoo_path,
            FOLDERS=json.dumps(self.workspace_folders, indent=4),
            VENV_PATH=self.process.venv.python.as_posix(),
            RUFF_PATH=(self.process.venv.path / "bin" / "ruff").as_posix(),
            PYTHON_PATH=PythonEnv().python.as_posix(),
            ODEV_EXE_PATH=self.database.odev.executable.with_name("main.py").as_posix(),
        )
        with open(self.workspace_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)

    def _create_launch(self):
        """Create a launch file for the project."""
        rendered_template = self._get_rendered_template("launch.jinja")
        with open(self.launch_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)

    def _create_tasks(self):
        """Create a tasks file for the project."""
        rendered_template = self._get_rendered_template(
            "tasks.jinja",
            DB_VERSION=self.version,
        )
        with open(self.tasks_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)

    def _create_jsconfig(self):
        """Create JS config file to provide intellisense JavaScript."""
        root = self.odoo_path.resolve()

        addon_dirs = [
            root / "addons",
            root / "odoo" / "addons",
            root / "enterprise",
            self.path,
        ]

        paths_map = {
            "@odoo/owl": ["odoo/addons/web/static/src/@types/owl.d.ts"],
            "@odoo/hoot": ["odoo/addons/web/static/src/@types/hoot.d.ts"],
            "@odoo/hoot-dom": ["odoo/addons/web/static/src/@types/hoot.d.ts"],
        }

        for addon_dir in addon_dirs:
            if not addon_dir.exists():
                continue
            for module in addon_dir.iterdir():
                if module.is_dir():
                    static_src_path = module / "static" / "src"
                    if static_src_path.exists():
                        rel_path = os.path.relpath(static_src_path, root)
                        paths_map[f"@{module.name}/*"] = [f"{rel_path}/*"]

        modules_mapping = dict(sorted(paths_map.items()))

        rendered_template = self._get_rendered_template(
            "jsconfig.jinja",
            ODOO_PATH=self.odoo_path,
            JS_MODULES_PATHS=json.dumps(modules_mapping, indent=4),
        )
        with open(self.path / "jsconfig.json", "w", encoding="utf-8") as f:
            f.write(rendered_template)
