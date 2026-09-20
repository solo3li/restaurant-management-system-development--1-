import sys
import uvicorn
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run unified ASGI Server (Django Web Application + FastMCP Call Center SSE 24/7)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default="127.0.0.1",
            help="Host address to bind the ASGI server (default: 127.0.0.1)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8001,
            help="Port to bind the ASGI server (default: 8001)",
        )
        parser.add_argument(
            "--reload",
            action="store_true",
            default=False,
            help="Enable auto-reload on code changes (development mode)",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]
        reload = options["reload"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Unified ASGI Server on http://{host}:{port} "
                f"(Django App + FastMCP SSE at http://{host}:{port}/sse)..."
            )
        )
        uvicorn.run(
            "restaurant_system.asgi:application",
            host=host,
            port=port,
            reload=reload,
            lifespan="on",
        )
