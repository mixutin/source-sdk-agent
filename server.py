#!/usr/bin/env python3
"""On-demand stdio MCP interface; stdout is reserved for MCP messages."""
from mcp.server.fastmcp import FastMCP
from agent import TOOLS
mcp = FastMCP("source-sdk-agent", instructions="Manage only Source SDK projects through typed tools. Inspect doctor before building. Poll get_job until completion. Never describe queued jobs as successes. Write operations require user intent; overwrites require the current sha256. Do not promise successful gameplay without a test. No root or public network service is required.")
for name, function in TOOLS.items():
    mcp.add_tool(function, name=name)
if __name__ == "__main__":
    mcp.run(transport="stdio")
