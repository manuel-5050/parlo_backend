import uvicorn
from django.core.management.base import BaseCommand

from chatbots.mcp_server import create_app


class Command(BaseCommand):
    help = "Run Parlo's MCP server (Streamable HTTP) at http://HOST:PORT/mcp"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8002)

    def handle(self, *args, **options):
        host, port = options["host"], options["port"]
        self.stdout.write(f"Parlo MCP server on http://{host}:{port}/mcp (health: /health)")
        uvicorn.run(create_app(host), host=host, port=port, log_level="info")