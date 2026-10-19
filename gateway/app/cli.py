"""
Minimal operator CLI for the gateway itself - creating the first tenant
account is the one thing that has to happen outside the API (nothing can
call get_tenant_admin before a tenant/API key exists). A real SaaS
replaces `create-tenant` with a signup flow; everything downstream
(workers, devices, pairing) already goes through the regular API once a
tenant exists.
"""
import asyncio
import secrets

import click

from app.db import SessionLocal, init_models
from app.models import Tenant
from app.security import hash_secret


@click.group()
def cli():
    """Molly Gateway - operator CLI"""
    pass


@cli.command("create-tenant")
@click.option("--name", required=True, help="Tenant/account display name")
def create_tenant(name: str):
    """Create a new tenant account and print its API key. Store the key
    somewhere safe - it's only ever shown here, hashed at rest exactly
    like a worker's enrollment token."""
    asyncio.run(_create_tenant(name))


async def _create_tenant(name: str):
    await init_models()
    api_key = f"mk_{secrets.token_urlsafe(32)}"
    async with SessionLocal() as db:
        tenant = Tenant(name=name, api_key_hash=hash_secret(api_key))
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
    click.echo(f"tenant_id: {tenant.id}")
    click.echo(f"api_key:   {api_key}")
    click.echo("(use this as the X-API-Key header on /admin/* calls)")


if __name__ == "__main__":
    cli()
