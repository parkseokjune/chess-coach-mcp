"""Boot the server as a real MCP stdio process and exercise it as a client.

Run:  uv run python examples/mcp_smoke.py

Verifies the full MCP protocol path: spawn the server, initialise a session,
list tools, and call a couple of them. No network required.
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "chess_coach_mcp.server"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("TOOLS:", names)

            status = await session.call_tool("engine_status", {})
            print("engine_status ->", status.content[0].text)

            pos = await session.call_tool(
                "analyze_position",
                {"fen": "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "depth": 10, "multipv": 1},
            )
            print("analyze_position ->", pos.content[0].text[:240])

    print("OK: MCP server booted, listed tools, and answered tool calls.")


if __name__ == "__main__":
    asyncio.run(main())
