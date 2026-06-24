"""A control target: a notes formatter that actually only formats notes.
A trustworthy tool must produce ZERO findings, or the whole approach is noise."""
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("honest-notes-formatter")

@app.list_tools()
async def list_tools():
    return [Tool(name="format_note",
                 description="Formats a markdown note. Purely local text formatting.",
                 inputSchema={"type": "object",
                              "properties": {"text": {"type": "string"}},
                              "required": ["text"]})]

@app.call_tool()
async def call_tool(name, arguments):
    return [TextContent(type="text", text=f"# {arguments.get('text','')}\n")]

async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
