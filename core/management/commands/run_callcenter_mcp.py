import sys
from django.core.management.base import BaseCommand
from core.mcp_server import run_server


class Command(BaseCommand):
    help = "Run FastMCP Server for Restaurant Call Center AI Supervisor"

    def add_arguments(self, parser):
        parser.add_argument(
            "--transport",
            type=str,
            choices=["stdio", "sse"],
            default="stdio",
            help="Transport protocol: 'stdio' for Claude Desktop / Cursor, or 'sse' for HTTP/SSE service",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="127.0.0.1",
            help="Host address for SSE server (default: 127.0.0.1)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8002,
            help="Port for SSE server (default: 8002)",
        )

    def handle(self, *args, **options):
        transport = options["transport"]
        host = options["host"]
        port = options["port"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting FastMCP Call Center Server (transport={transport}, host={host}, port={port})..."
            )
        )
        run_server(transport=transport, host=host, port=port)

