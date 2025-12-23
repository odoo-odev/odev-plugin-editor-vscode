import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from odev.common import progress, string
from odev.common.databases import LocalDatabase
from odev.common.errors import OdevError
from odev.common.logging import logging
from odev.common.python import PythonEnv

from odev.plugins.odev_plugin_editor_base.common.editor import Editor


logger = logging.getLogger(__name__)


class VSCodeEditor(Editor):
    """Class meant for interacting with VSCode."""

    _name = "code"
    _display_name = "VSCode"

    @property
    def command(self) -> str:
        if isinstance(self.database, LocalDatabase):
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
            logger.info(f"Created VSCode config for project {self.git.name!r}\n{created_files}")
        return None

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
