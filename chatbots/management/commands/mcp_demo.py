import asyncio
import json
import os

import httpx2
from django.core.management.base import BaseCommand, CommandError
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def show(result):
    """The tool result as pretty JSON (tools return their data as JSON text)."""
    if result.structured_content:
        return json.dumps(result.structured_content, indent=2)
    text = "".join(getattr(part, "text", "") for part in result.content)
    try:
        return json.dumps(json.loads(text), indent=2)
    except ValueError:
        return text


class Command(BaseCommand):
    help = (
        "Connect to a Parlo MCP server as a client, list its tools and call them. "
        "Shows exactly what an assistant such as Alexa+ would do."
    )

    def add_arguments(self, parser):
        parser.add_argument("--url", default=os.environ.get("MCP_URL", "http://localhost:8002/mcp"))
        parser.add_argument("--key", required=True, help="the bot's public key (pk_...)")
        parser.add_argument("--question", default="Can I get my money back?")
        parser.add_argument("--ask", action="store_true", help="also call the slower ask_business_assistant tool")

    def handle(self, *args, **options):
        try:
            asyncio.run(self._run(options))
        except Exception as exc:  # show a short message instead of a long traceback
            raise CommandError(f"{type(exc).__name__}: {exc}")

    async def _run(self, options):
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {options['key']}"})
        transport = streamable_http_client(options["url"], http_client=http)
        async with Client(transport) as client:
            tools = await client.list_tools()
            self.stdout.write("Tools:")
            for tool in tools.tools:
                self.stdout.write(f"  - {tool.name}")

            info = await client.call_tool("get_business_info", {})
            self.stdout.write("\nget_business_info:\n" + show(info))

            found = await client.call_tool("search_knowledge", {"query": options["question"]})
            self.stdout.write("\nsearch_knowledge:\n" + show(found))

            if options["ask"]:
                answer = await client.call_tool(
                    "ask_business_assistant", {"question": options["question"]}
                )
                self.stdout.write("\nask_business_assistant:\n" + show(answer))