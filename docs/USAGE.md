# Usage guide

This is the practical how-to. For the research story (what this project actually found, and why), see the [README](../README.md).

## Quickstart

```bash
git clone https://github.com/Tarek-yagami/codebase-knowledge-graph.git
cd codebase-knowledge-graph
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install .
codegraph-viz /path/to/your/project
```

That opens `data/graph3d.html` in your browser: a live, click-to-explore 3D graph of whatever codebase you pointed it at. Click a module or class to step inside it, click the surrounding shell (or empty space) to step back out.

## Install options

**As a package** (recommended, gives you the `codegraph-viz` and `codegraph-mcp` commands directly):

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

## Troubleshooting

- **"Pending approval" forever in `claude mcp list`**: that approval is granted at session startup, not by listing servers. Start a fresh `claude` session in the directory and approve it when asked.
- **Windows: `claude` has no `.exe`, only `.cmd`/`.ps1`**: if you're scripting against it directly (like `experiments/_common.py` does), resolve the path with `shutil.which("claude")` rather than assuming a plain string works with `subprocess.run`.
- **First MCP server launch against a large codebase is slow**: structural parsing isn't cached (by design, since it's fast, a few seconds even for a large repo) but embeddings are, so only the very first launch against a given repo pays the full cost, a couple of minutes for something Django-sized.
- **Docker image can't see your repo**: make sure both `-v` mounts are absolute paths, and on Git Bash, use `MSYS_NO_PATHCONV=1` (see above).

## Reproducing the research

This needs `requests` and Django cloned locally, since the findings in the README are tied to those exact repos.

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
