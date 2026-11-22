"""python -m leaseapp stdio | serve [--port N] [--public-host HOST] [--allow-origin URL] | reset"""

import argparse

from mcp.server.transport_security import TransportSecuritySettings

from . import db, landlord_web  # noqa: F401  (importing landlord_web registers the landlord pages)
from .mcp_server import mcp


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m leaseapp")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stdio", help="MCP over stdin/stdout, for Claude Desktop and Claude Code")
    s = sub.add_parser("serve", help="MCP at /mcp plus the landlord page, over HTTP")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--public-host", help="Tunnel hostname to accept, e.g. abc.trycloudflare.com (for ChatGPT)")
    s.add_argument("--allow-origin", action="append", default=[], help="Extra Origin header to accept")
    sub.add_parser("reset", help="Delete the database and reload the demo data")
    a = p.parse_args()

    db.init(reset=a.cmd == "reset")
    if a.cmd == "stdio":
        mcp.run()
    elif a.cmd == "serve":
        security = None  # None = the SDK's default: localhost only
        if a.public_host:
            local = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
            security = TransportSecuritySettings(
                allowed_hosts=local + [a.public_host, f"{a.public_host}:*"],
                allowed_origins=["http://127.0.0.1:*", "http://localhost:*", f"https://{a.public_host}",
                                 *a.allow_origin],
            )
        print(f"MCP endpoint:  http://127.0.0.1:{a.port}/mcp"
              + (f"  and  https://{a.public_host}/mcp" if a.public_host else ""))
        print(f"Landlord page: http://127.0.0.1:{a.port}/landlord   Outbox: http://127.0.0.1:{a.port}/outbox")
        # json_response: one plain JSON body per request instead of an SSE stream.
        # Cloudflare quick tunnels do not support SSE, and no tool here needs streaming.
        mcp.run(transport="streamable-http", host="127.0.0.1", port=a.port, json_response=True,
                transport_security=security)
    else:
        print(f"Reset {db.db_path()}")


if __name__ == "__main__":
    main()
