import asyncio
import sys
from typing import Optional
import click
import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from app.config import settings
from app.storage.database import init_db
from app.storage.projects import create_default_projects
from app.tools import registry
from app.agent.executor import AgentExecutor
from app.storage.conversations import create_conversation, get_conversation
from app.llm.client import close_provider

console = Console()


@click.group()
def cli():
    """Molly - Autonomous DevOps Assistant CLI"""
    pass


@cli.command()
@click.option("--host", default=None, help="Host to bind to")
@click.option("--port", default=None, type=int, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(host: Optional[str], port: Optional[int], reload: bool):
    """Start the Molly backend server."""
    import uvicorn

    host = host or settings.host
    port = port or settings.port

    console.print(f"[green]Starting Molly backend on {host}:{port}[/green]")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload or settings.debug,
    )


@cli.command()
@click.argument("message")
@click.option("--conversation-id", "-c", help="Conversation ID (creates new if not provided)")
@click.option("--image", "-i", multiple=True, help="Image ID to attach")
@click.option(
    "--mode", type=click.Choice(["general", "bug_bounty"]), default="general",
    help="Agent mode for a newly-created conversation (ignored if --conversation-id points at an existing one).",
)
def run(message: str, conversation_id: Optional[str], image: tuple, mode: str):
    """Run a single message through Molly (CLI mode)."""
    asyncio.run(_run_cli(message, conversation_id, list(image), mode))


async def _run_cli(message: str, conversation_id: Optional[str], image_ids: list, mode: str = "general"):
    """Run agent in CLI mode."""
    # Initialize
    init_db()
    create_default_projects()

    # Get or create conversation
    if conversation_id:
        conv = get_conversation(conversation_id)
        if not conv:
            console.print(f"[red]Conversation not found: {conversation_id}[/red]")
            return
    else:
        conv = create_conversation("CLI Session", metadata={"mode": mode})
        console.print(f"[dim]Created conversation: {conv.id} (mode={mode})[/dim]")

    console.print(Panel(f"[bold]Molly CLI[/bold] - Conversation: {conv.id}", style="blue"))

    # Create executor
    executor = AgentExecutor(conv.id)

    try:
        async for event in executor.run(message, image_ids):
            _print_event(event)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
    finally:
        await close_provider()


def _print_event(event: dict):
    """Pretty print an event."""
    ev_type = event.get("type")

    if ev_type == "agent_started":
        console.print("[dim]Agent started...[/dim]")
    elif ev_type == "tool_started":
        console.print(f"[cyan]🔧 Tool:[/cyan] {event['tool']} {event['arguments']}")
    elif ev_type == "tool_completed":
        result = event.get("result", "")
        if isinstance(result, dict):
            result = str(result)
        truncated = event.get("truncated", False)
        console.print(f"[green]✓ Result:[/green] {result[:500]}{'... (truncated)' if truncated else ''}")
    elif ev_type == "tool_failed":
        console.print(f"[red]✗ Error:[/red] {event['error']}")
    elif ev_type == "tool_error":
        console.print(f"[red]✗ Error:[/red] {event['error']}")
    elif ev_type == "approval_required":
        console.print(Panel(
            f"[bold]APPROVAL REQUIRED[/bold]\n"
            f"Tool: {event['tool']}\n"
            f"Risk: {event['risk_level']}\n"
            f"Reason: {event['reason']}\n"
            f"Arguments: {event['arguments']}",
            style="yellow",
            title="⚠️ Approval",
        ))
        # In CLI, we can't easily wait for approval
        console.print("[yellow]CLI mode: approval not supported. Use web UI.[/yellow]")
    elif ev_type == "agent_completed":
        console.print(Panel(Markdown(event["response"]), title="✅ Complete", style="green"))
    elif ev_type == "agent_error":
        console.print(f"[red]Error: {event['error']}[/red]")
    elif ev_type == "agent_cancelled":
        console.print("[yellow]Cancelled[/yellow]")
    else:
        console.print(f"[dim]{event}[/dim]")


@cli.command()
def connect():
    """Pair a new device (the Molly mobile app) with this server.

    Requires this worker to be enrolled with a fleet gateway first (see
    `molly worker enroll`) - asks the gateway for a short pairing code and
    prints it. Type it into the app, no browser or admin approval
    involved.
    """
    asyncio.run(_connect())


async def _connect():
    from app.tunnel.enrollment import load_credential

    cred = load_credential()
    if not cred:
        console.print(
            "[red]This worker isn't enrolled with a gateway yet.[/red]\n"
            "Run [bold]molly worker enroll --gateway <url> --token <token>[/bold] first."
        )
        return

    gateway_http_url = cred.get("gateway_http_url", "")
    if not gateway_http_url:
        console.print("[red]No gateway URL on file. Re-run `molly worker enroll` with --gateway.[/red]")
        return

    try:
        async with httpx.AsyncClient(base_url=gateway_http_url, timeout=10.0) as client:
            resp = await client.post(
                "/worker/pairing-codes",
                headers={"X-Worker-Id": cred["worker_id"], "X-Worker-Token": cred["worker_token"]},
            )
            resp.raise_for_status()
            data = resp.json()
            console.print(Panel(
                f"Enter this code in the Molly app:\n\n[bold cyan]{data['code']}[/bold cyan]\n\n"
                f"Expires in {data['expires_in_minutes']} minutes.",
                title="🔗 Connect a device",
                style="blue",
            ))
    except httpx.ConnectError:
        console.print(f"[red]Could not reach the gateway at {gateway_http_url}.[/red]")
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Could not get a pairing code: {e.response.text}[/red]")


@cli.group()
def worker():
    """Manage this worker's enrollment with a fleet gateway - required
    for the Molly app to reach this worker at all (see `molly connect`)."""
    pass


@worker.command("enroll")
@click.option(
    "--gateway", "gateway_http_url", default=None,
    help=f"Gateway base URL. Defaults to settings.gateway_http_url ({settings.gateway_http_url}) - "
         "only pass this if enrolling against a different gateway than the built-in default.",
)
@click.option("--token", "enrollment_token", required=True, help="One-time enrollment token from the gateway admin console/API")
@click.option("--label", default=None, help="Human-readable name for this worker (defaults to this machine's hostname)")
def worker_enroll(gateway_http_url: Optional[str], enrollment_token: str, label: Optional[str]):
    """Join the fleet gateway - required before this worker can accept any
    authenticated request (see app/auth/dependencies.py). Run this ON THE
    server - pasting the enrollment token into a shell here is the proof
    that you control this box."""
    gateway_http_url = gateway_http_url or settings.gateway_http_url
    asyncio.run(_worker_enroll(gateway_http_url, enrollment_token, label))


async def _worker_enroll(gateway_http_url: str, enrollment_token: str, label: Optional[str]):
    import socket
    from app.tunnel.enrollment import EnrollmentError, enroll

    try:
        cred = await enroll(gateway_http_url, enrollment_token, label or socket.gethostname())
        console.print(Panel(
            f"[bold]worker_id:[/bold] {cred['worker_id']}\n"
            f"Saved to data/gateway_credential.json (0600).\n\n"
            f"Set GATEWAY_WS_URL in .env if the gateway didn't return one, "
            f"then restart `molly serve` - it will dial out to the gateway "
            f"automatically on startup.",
            title="✓ Enrolled",
            style="green",
        ))
    except EnrollmentError as e:
        console.print(f"[red]Enrollment failed: {e}[/red]")
    except httpx.ConnectError:
        console.print(f"[red]Could not reach the gateway at {gateway_http_url}[/red]")


@worker.command("status")
def worker_status():
    """Show this worker's fleet enrollment, if any."""
    from app.tunnel.enrollment import load_credential

    cred = load_credential()
    if not cred:
        console.print("[dim]Not enrolled with any gateway - this worker won't accept authenticated requests until it is.[/dim]")
        return
    console.print(Panel(
        f"[bold]worker_id:[/bold] {cred['worker_id']}\n"
        f"[bold]gateway:[/bold] {cred.get('gateway_ws_url') or settings.gateway_ws_url or '(set GATEWAY_WS_URL)'}",
        title="Fleet enrollment",
    ))


@worker.command("unenroll")
def worker_unenroll():
    """Remove this worker's saved gateway credential. The worker will stop
    accepting any authenticated request until it's enrolled again."""
    from app.tunnel.enrollment import clear_credential

    clear_credential()
    console.print("[yellow]Credential removed. Restart the server to disconnect the tunnel.[/yellow]")


@cli.command()
def tools():
    """List available tools."""
    console.print("[bold]Available Tools:[/bold]")
    for name in registry.list_tools():
        tool = registry.get(name)
        schema = registry.get_schema(name)
        console.print(f"  [cyan]{name}[/cyan] ({schema.risk_level}): {schema.description}")


@cli.command()
@click.argument("project_id", required=False)
def projects(project_id: Optional[str]):
    """List or show projects."""
    from app.storage.projects import load_project, load_all_projects

    if project_id:
        project = load_project(project_id)
        if not project:
            console.print(f"[red]Project not found: {project_id}[/red]")
            return
        console.print(Panel(
            f"[bold]{project.name}[/bold] ({project.id})\n"
            f"Path: {project.path}\n"
            f"Description: {project.description}\n"
            f"Stack: {', '.join(project.stack)}\n"
            f"Environment: {project.environment}\n"
            f"Services: {', '.join(project.services)}\n"
            f"Commands: {project.commands}",
            title="Project Details",
        ))
    else:
        projects = load_all_projects()
        console.print("[bold]Registered Projects:[/bold]")
        for p in projects:
            console.print(f"  [cyan]{p.id}[/cyan]: {p.name} ({p.path})")


if __name__ == "__main__":
    cli()