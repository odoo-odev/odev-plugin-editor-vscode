from odev.common.config import Section


class VscodeSection(Section):
    _name = "vscode"

    @property
    def workspace_layout(self) -> str:
        """Layout of the multi-root VSCode workspace, one of:
        - 'flat': One top-level root per odoo worktree alongside the project (legacy default).
        - 'nested': A single 'odoo' root holding all worktrees as subfolders.
        Defaults to 'flat'.
        """
        return self.get("workspace_layout", "flat")

    @workspace_layout.setter
    def workspace_layout(self, value: str):
        if value not in ("flat", "nested"):
            raise ValueError(f"'vscode.workspace_layout' must be one of 'flat', 'nested', got {value!r}")
        self.set("workspace_layout", value)
