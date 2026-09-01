FROM python:3.11-slim

WORKDIR /app

# Only networkx is needed for the parser/graph/visualizer pipeline - the
# semantic layer (sentence-transformers/torch) is for the MCP server, which
# needs the host's `claude` CLI and isn't what this image is for.
RUN pip install --no-cache-dir networkx>=3.2

COPY src/ src/
COPY scripts/ scripts/

ENTRYPOINT ["python", "scripts/visualize.py"]
