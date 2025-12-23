# ODEV - VSCode Editor

Configure VSCode or any other editor derivated from VSCodium (e.g. VSCodium) for a database and open a repository
in the editor.

## Installation

Install [odev](https://github.com/odoo-odev/odev/tree/main?tab=readme-ov-file#installation) if not already done. You'll
need odev version 4.0.0 or above.

Enable this plugin by running:

```bash
odev plugin --enable odoo-odev/odev-plugin-editor-vscode
```

Using other editors with the same base (e.g. VSCodium) should work as well at the cost of setting up a symlink
to the editor executable in your path.

Antigravity example:

```bash
ln -s $(which antigravity) /usr/local/bin/code
```
