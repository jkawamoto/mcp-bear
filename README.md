# Bear MCP Server
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python Application](https://github.com/jkawamoto/mcp-bear/actions/workflows/python-app.yaml/badge.svg)](https://github.com/jkawamoto/mcp-bear/actions/workflows/python-app.yaml)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![GitHub License](https://img.shields.io/github/license/jkawamoto/mcp-bear)](https://github.com/jkawamoto/mcp-bear/blob/main/LICENSE)

A MCP server for interacting with [Bear](https://bear.app/) note-taking software.

<img src="icon.png" width="256" height="256" alt="Bear MCP Server Icon">

## Installation
> [!NOTE]
> You'll need [`uv`](https://docs.astral.sh/uv) installed on your system to use `uvx` command.

### [goose](https://block.github.io/goose/)
Open this link
```
goose://extension?cmd=uvx&arg=--from&arg=git%2Bhttps%3A%2F%2Fgithub.com%2Fjkawamoto%2Fmcp-bear&arg=mcp-bear&id=bear&name=Bear&description=Interacting%20with%20Bear%20note-taking%20software&env=BEAR_API_TOKEN
```
to launch the installer, then click "Yes" to confirm the installation.
Set `BEAR_API_TOKEN` environment variable to your api token.

<details>
<summary>Manually configuration</summary>

You can also directly edit the config file (`~/.config/goose/config.yaml`) to include the following entry:

```yaml
extensions:
  bear:
    name: Bear
    cmd: uvx
    args: [--from, git+https://github.com/jkawamoto/mcp-bear, mcp-bear]
    envs: { "BEAR_API_TOKEN": "<YOUR_TOKEN>" }
    enabled: true
    type: stdio
```

</details>

For more details on configuring MCP servers in Goose, refer to the documentation:
[Using Extensions | goose](https://block.github.io/goose/docs/getting-started/using-extensions#mcp-servers).

### [Claude](https://claude.com/download)
Download the latest MCP bundle `mcp-bear.mcpb` from
the [Releases](https://github.com/jkawamoto/mcp-bear/releases) page,
then open the downloaded `.mcpb `file or drag it into the Claude Desktop's Settings window.

<details>
<summary>Manually configuration</summary>

You can also manually configure this server for Claude Desktop.
Edit the `claude_desktop_config.json` file by adding the following entry under `mcpServers`:

```json
{
  "mcpServers": {
    "bear": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/jkawamoto/mcp-bear",
        "mcp-bear",
        "--token",
        "<YOUR_TOKEN>"
      ]
    }
  }
}
```
After editing, restart the application.

</details>

For more information,
see: [Connect to local MCP servers - Model Context Protocol](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

### [LM Studio](https://lmstudio.ai/)
To configure this server for LM Studio, click the button below.

[![Add MCP Server bear to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=bear&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL2prYXdhbW90by9tY3AtYmVhciIsIm1jcC1iZWFyIiwiLS10b2tlbiIsIjxZT1VSX1RPS0VOPiJdfQ%3D%3D)

## Actions Implemented

The server supports the following actions.
Refer to Bear's [X-callback-url Scheme documentation](https://bear.app/faq/x-callback-url-scheme-documentation/) for details on each action.

- [x] /open-note
- [x] /create
- [x] /add-text (partially, via the replace_note and add_title method)
- [x] /add-file
- [x] /tags
- [x] /open-tag
- [x] /rename-tag
- [x] /delete-tag
- [x] /trash
- [x] /archive
- [x] /untagged
- [x] /todo
- [x] /today
- [x] /locked
- [x] /search
- [x] /grab-url

## License
This application is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.
