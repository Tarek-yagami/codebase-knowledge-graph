FROM python:3.11-slim

WORKDIR /app

# Only networkx and the tree-sitter grammars are needed for the parser/graph/
# visualizer pipeline - the semantic layer (sentence-transformers/torch) is for
# the MCP server, which needs the host's `claude` CLI and isn't what this image is for.
RUN pip install --no-cache-dir "networkx>=3.2" "tree-sitter-language-pack>=1.20" "json5>=0.9"
# Bake in the grammars with dedicated extractors; any other language's grammar
# downloads the first time a repo containing it is parsed.
RUN python -c "import tree_sitter_language_pack as t; t.download(['typescript', 'tsx', 'javascript', 'vue', 'go', 'php', 'java', 'kotlin', 'csharp', 'rust', 'c', 'cpp'])"

COPY src/ src/
COPY scripts/ scripts/

ENTRYPOINT ["python", "scripts/visualize.py"]
