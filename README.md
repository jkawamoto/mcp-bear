# Bear MCP Server
[![Python Application](https://github.com/jkawamoto/mcp-bear/actions/workflows/python-app.yaml/badge.svg)](https://github.com/jkawamoto/mcp-bear/actions/workflows/python-app.yaml)
[![GitHub License](https://img.shields.io/github/license/jkawamoto/mcp-bear)](https://github.com/jkawamoto/mcp-bear/blob/main/LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A MCP server for interacting with [Bear](https://bear.app/) note-taking software.

<a href="https://glama.ai/mcp/servers/2gg54jdwwv"><img width="380" height="200" src="https://glama.ai/mcp/servers/2gg54jdwwv/badge" alt="Bear Server MCP server" /></a>

## Installation
> [!NOTE]
> You'll need [`uv`](https://docs.astral.sh/uv) installed on your system to use `uvx` command.

### For Goose CLI
To enable the Bear extension in Goose CLI,
edit the configuration file `~/.config/goose/config.yaml` to include the following entry:

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

### For Goose Desktop
Add a new extension with the following settings:

- **Type**: Standard IO
- **ID**: bear
- **Name**: Bear
- **Description**: Interacting with Bear note-taking software
- **Command**: `uvx --from git+https://github.com/jkawamoto/mcp-bear mcp-bear`
- **Environment Variables**: Add `BEAR_API_TOKEN` with your api token

For more details on configuring MCP servers in Goose Desktop,
refer to the documentation:
[Using Extensions - MCP Servers](https://block.github.io/goose/docs/getting-started/using-extensions#mcp-servers).

### For Claude Desktop
Download the latest MCP bundle `mcp-bear.mcpb` from
the [Releases](https://github.com/jkawamoto/mcp-bear/releases) page,
then open the downloaded `.mcpb `file or drag it into the Claude Desktop's Settings window.

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
For more information,
see: [For Claude Desktop Users - Model Context Protocol](https://modelcontextprotocol.io/quickstart/user).

### For LM Studio
To configure this server for LM Studio, click the button below.

[![Add MCP Server bear to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=bear&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL2prYXdhbW90by9tY3AtYmVhciIsIm1jcC1iZWFyIiwiLS10b2tlbiIsIjxZT1VSX1RPS0VOPiJdfQ%3D%3D)

## Actions Implemented

The server supports the following actions.
Refer to Bear's [X-callback-url Scheme documentation](https://bear.app/faq/x-callback-url-scheme-documentation/) for details on each action.

- [x] /open-note
- [x] /create
- [x] /add-text (partially, via the replace_note method)
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
