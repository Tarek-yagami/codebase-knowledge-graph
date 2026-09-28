# Usage guide

This is the practical how-to. For what the project found when it was tested, see the [research findings](RESEARCH.md).

## As a Claude Code plugin

The easiest way in. You need [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, then inside Claude Code:

```
/plugin marketplace add Tarek-yagami/codebase-knowledge-graph
/plugin install codegraph@codebase-knowledge-graph
```

After a restart, the `codegraph` MCP server runs against whatever project you open Claude Code in, and three commands are available: `/codegraph:map` opens the 3D graph, `/codegraph:impact` shows what depends on your uncommitted changes (or on files or a git range you name), and `/codegraph:tour` walks you through the codebase in dependency order, optionally focused on one area (`/codegraph:tour authentication`).

The plugin installs the package without semantic search, which needs PyTorch. To turn it on, change the `--from` argument of the `codegraph` server in the plugin's `.claude-plugin/plugin.json` to `codebase-knowledge-graph[semantic] @ git+https://github.com/Tarek-yagami/codebase-knowledge-graph`.

## Quickstart without Claude Code

```bash
git clone https://github.com/Tarek-yagami/codebase-knowledge-graph.git
cd codebase-knowledge-graph
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install .
codegraph-viz /path/to/your/project
```

That opens a live, click-to-explore 3D graph of whatever codebase you pointed it at in your browser. The page is saved in codegraph's cache folder (`~/.cache/codegraph`, or wherever `CODEGRAPH_CACHE` points). Use `--out page.html` to write it somewhere else and `--no-open` to skip the browser. Click a module or class to step inside it, click the surrounding shell (or empty space) to step back out.

## Install options

**As a package** (gives you the `codegraph-viz` and `codegraph-mcp` commands directly). Add `[semantic]` after the package name, like `pip install '.[semantic]'`, to include semantic search:

```bash
pip install .                                                                    # from a local clone
pip install git+https://github.com/Tarek-yagami/codebase-knowledge-graph.git     # straight from GitHub, no clone needed
```

**From a source checkout, no install** (useful if you're modifying the code):

```bash
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python scripts/visualize.py /path/to/your/project
```

**With Docker, no local Python at all** (visualizer only, doesn't need the semantic layer's dependencies):

```bash
docker build -t codegraph-viz .
docker run --rm -v /path/to/your/project:/repo -v "$(pwd)/data:/app/data" codegraph-viz /repo
```

On Windows with Git Bash specifically, prefix that `docker run` with `MSYS_NO_PATHCONV=1`, otherwise Git Bash silently rewrites `/repo` into a Windows path before Docker ever sees it.

## Connecting it to Claude Code

This is the actual point of the project: Claude Code can query the graph directly instead of reading and grepping through files.

1. Install the standalone CLI: `npm install -g @anthropic-ai/claude-code`. This is separate from the Claude Code IDE extension, both can be installed at once with no conflict.
2. Copy `.mcp.json.example` to `.mcp.json` in the project you want Claude Code to explore (or in this repo, if you're pointing it at itself).
3. Fill in the real paths: `command` should point at your Python interpreter (or the installed `codegraph-mcp` executable, see below), and the last argument should be the absolute path to the codebase you want indexed.
4. Run `claude` in that directory. The first time, it'll ask to approve the new `codegraph` MCP server, say yes.
5. Ask it a real question about the codebase. Watch which tool it reaches for.

If you installed the package, `.mcp.json` gets simpler:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "/absolute/path/to/.venv/bin/codegraph-mcp",
      "args": ["/absolute/path/to/the/repo/you/want/to/explore"]
    }
  }
}
```

### Tool reference

| Tool | Use it when |
|---|---|
| `list_modules` | You want an overview of every module in the codebase. |
| `get_node` | You already have a node's exact id and want its full details, docstring, and source. |
| `list_children` | You know a module or class and want what's defined directly inside it. |
| `get_relationships` | The question is "who calls this" or "what does this depend on" - exact, not a guess. |
| `find_by_name` | You know the exact name you're looking for (e.g. every method literally called `save`), and want *all* of them, not a ranked top few. |
| `search_nodes` | You don't know the exact name, but have a keyword or partial name in mind. Results are ranked: exact name match first, then partial, then docstring mention. |
| `semantic_search` | You don't know the name *or* the keyword, only what the code should *do* (e.g. "code that retries a failed request"). |
| `impact_of_changes` | You're about to change (or just changed) a file and want to know what actually depends on it before you commit. |
| `suggested_reading_order` | You're new to the codebase and want a sensible order to read its modules in, dependencies first. |

## Troubleshooting

- **"Pending approval" forever in `claude mcp list`**: that approval is granted at session startup, not by listing servers. Start a fresh `claude` session in the directory and approve it when asked.
- **Windows: `claude` has no `.exe`, only `.cmd`/`.ps1`**: if you're scripting against it directly (like `experiments/_common.py` does), resolve the path with `shutil.which("claude")` rather than assuming a plain string works with `subprocess.run`.
- **The first semantic search on a large codebase is slow**: the server starts right away, but it builds the embedding index on the first `semantic_search` call, a couple of minutes for something Django-sized. The index is then cached, so later sessions load it in under a second.
- **`semantic_search` says it needs an optional extra**: semantic search pulls in PyTorch, so it isn't installed by default. See the install options above.
- **Docker image can't see your repo**: make sure both `-v` mounts are absolute paths, and on Git Bash, use `MSYS_NO_PATHCONV=1` (see above).

## Reproducing the research

This needs `requests` and Django cloned locally, since the [research findings](RESEARCH.md) are tied to those exact repos.

```bash
git clone --depth 1 https://github.com/psf/requests.git data/repos/requests
git clone --depth 1 https://github.com/django/django.git data/repos/django

python experiments/token_economy/run_requests.py    # research question 4
python experiments/token_economy/summarize.py
python experiments/rq1_graphrag_vs_flatrag/run_requests.py   # research question 1
python experiments/rq1_graphrag_vs_flatrag/summarize.py
```

Each one makes real, billed calls through the `claude` CLI (a handful of cents per run on `requests`), and results are saved incrementally so an interrupted run picks up where it left off.

## Running the test suite

```bash
pip install -r requirements-dev.txt
pytest        # tests only, self-contained, no real repo needed
ruff check .
ruff format --check .
mypy
```
