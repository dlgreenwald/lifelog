FROM python:3.11-slim

WORKDIR /app

# Copy package files needed for editable install
COPY pyproject.toml README.md src/ ./

# Install dependencies (editable mode)
RUN pip install --no-cache-dir -e .

# Run the MCP server
CMD ["python", "-m", "lifelog_mcp.server"]
