import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from odev.common import bash, progress, string
from odev.common.databases import LocalDatabase
from odev.common.errors import OdevError
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
        """Also handle other editors derived from VSCode/VSCodium (e.g. Antigravity)."""
        name = bash.execute(f"{self._name} --help | head -n 1 | awk '{{print $1}}'")

        if name and name.stdout.strip():
            return name.stdout.strip().capitalize().decode()

        return self._display_name

    @property
    def command(self) -> str:
        if isinstance(self.database, LocalDatabase) or self.version:
            return f"{self._name} {self.workspace_path}"
        raise OdevError("Database doesn't exist")

    @property
    def templates(self) -> Environment:
        return Environment(  # noqa: S701
            loader=FileSystemLoader(self.database.odev.plugins_path / "odev_plugin_editor_vscode/templates")
        )

    @property
    def workspace_directory(self) -> Path:
        """The path to the workspace directory."""
        if isinstance(self.database, LocalDatabase):
            return self.path / ".vscode"
        return self.path

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
        """Configure VSCode to work with the database, or to browse a bare Odoo version."""
        if isinstance(self.database, LocalDatabase):
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

        if self.version:
            with progress.spinner(f"Configuring {self.display_name} workspace for Odoo {self.version}"):
                self.workspace_directory.mkdir(parents=True, exist_ok=True)
                self._create_version_workspace()
                logger.info(f"Created {self.display_name} workspace for Odoo {self.version}\n  Workspace: {self.workspace_path}")
            return None

        return logger.warning(
            f"No local database associated with repository {self.git.name!r}, "
            f"skipping {self.display_name} configuration"
        )

    def _get_rendered_template(self, template_name, **kwargs):
        template = self.templates.get_template(template_name)
        return template.render(kwargs)

    def _create_workspace(self):
        """Create a workspace file for the project."""
        rendered_template = self._get_rendered_template(
            "code-workspace.jinja",
            DB_NAME=self.database.name,
            ODOO_PATH=self.database.odev.worktrees_path / self.database.worktree,
            VENV_PATH=self.database.venv.python.as_posix(),
            PYTHON_PATH=PythonEnv().python.as_posix(),
            ODEV_EXE_PATH="odev",
        )
        with open(self.workspace_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)

    def _create_version_workspace(self):
        """Create a workspace listing the Odoo worktrees (odoo, enterprise, design-themes) for the version."""
        process = OdoobinProcess(self.database, version=self.version).with_edition("enterprise")

        worktrees = list(process.odoo_worktrees)
        if len(worktrees) < len(list(process.odoo_repositories)):
            process.update_worktrees()
            worktrees = list(process.odoo_worktrees)

        folders = [{"path": worktree.path.as_posix(), "name": worktree.path.name} for worktree in worktrees]
        self.workspace_path.write_text(json.dumps({"folders": folders}, indent=4))

    def _create_launch(self):
        """Create a launch file for the project."""
        rendered_template = self._get_rendered_template("launch.jinja")
        with open(self.launch_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)

    def _create_tasks(self):
        """Create a tasks file for the project."""
        rendered_template = self._get_rendered_template(
            "tasks.jinja",
            DB_VERSION=self.database.version,
        )
        with open(self.tasks_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)

    def _create_jsconfig(self):
        """Create JS config file to provide intellisense JavaScript."""
        odoo_path = self.database.odev.worktrees_path / self.database.worktree
        root = Path(odoo_path).resolve()

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
            ODOO_PATH=odoo_path,
            JS_MODULES_PATHS=json.dumps(modules_mapping, indent=4),
        )
        with open(self.path / "jsconfig.json", "w", encoding="utf-8") as f:
            f.write(rendered_template)
