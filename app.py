"""Extension declaration, secrets, lifecycle hooks.

WHY BYOK (bring-your-own-key), same reasoning as MuleSoft Connector /
Power Automate Connector / Make.com Connector / n8n Connector. UiPath
Orchestrator lives inside the USER'S OWN UiPath Automation Cloud
organization (or their own on-prem/standalone Orchestrator) -- Imperal
cannot and should not broker access to someone else's UiPath tenant
centrally.

WHY EXTERNAL APPLICATION (client_id + client_secret) + ORGANIZATION/
TENANT/FOLDER, NOT A GENERIC PLATFORM OAUTH ENTRY.

UiPath Automation Cloud's own "External Applications" feature
(Admin > External Applications) supports OAuth 2.0 client-credentials
grant for exactly this kind of unattended server-to-server integration
(docs.uipath.com/automation-cloud/automation-cloud/latest/api-guide/
accessing-uipath-resources-using-external-applications, confirmed during
Discovery 2026-08-20, CONNECTOR_DISCOVERY.md). Unlike Zapier (which
requires external marketplace review before any real API access exists
at all), a UiPath External Application can be created immediately by any
org admin -- no chicken-and-egg. The connector therefore asks for the
External Application's own client_id/client_secret plus the
organization's logical name, the tenant's logical name, and a default
Folder id -- Orchestrator scopes almost every call to one Folder (the
modern replacement for "organization unit"), same shape as MuleSoft's
org_id/environment_id pair or Power Automate's environment_url.

WHY `write_mode="both"`, SAME REASONING AS MuleSoft/n8n/Make.com/Power
Automate CONNECTOR.

Declaring `write_mode="user"` would mean only the platform's generic
Secrets screen could write these -- leaving a first-time user with no
in-app screen explaining what an External Application even is or how to
create one. `"both"` keeps the generic Secrets screen as a fallback while
letting `connect_uipath` be the friendly guided path.

WHY SCOPE IS PER-ACCOUNT, NOT APP-LEVEL, SAME AS MuleSoft/n8n/Make.com/
Power Automate CONNECTOR.

Each user connects their OWN UiPath organization -- these are not
developer-owned app credentials, so the connections secret is declared
per-account (default scope), not `scope="app"`.

WHY ONE SECRET HOLDING A JSON ARRAY, NOT FLAT SECRETS FOR "the"
ORGANIZATION (multi-tenant support).

A UiPath Automation Cloud account can host several tenants (e.g.
Default/Staging/Production), each with its own set of Folders -- same
structural problem MuleSoft already solved for multi-environment orgs and
Power Automate solved for Dev/Test/UAT/Prod environments. `ctx.secrets`
only supports a fixed, manifest-declared set of NAMES -- there is no "one
secret per connection_id" primitive. This connector follows the same
precedent: `uipath_connections` holds a JSON array of `{id, label,
client_id, client_secret, organization_name, tenant_name,
default_folder_id}` objects. `schemas.py`'s `connection_id` parameter on
every tool call addresses one specific entry in that array -- see
handlers.py's `_load_connections`/`_save_connections` helpers.

SCOPE OF THIS RELEASE (Ярус 1 + 2, confirmed against Discovery):
processes (release definitions), jobs (start/stop/monitor runs of a
process -- UiPath's closest analogue to "run this scenario now"), queues
(queue definitions + queue items, the transaction-level unit of RPA
work), robots (machine/robot inventory), and assets (shared config
values a process reads at runtime). Studio (the visual designer),
Insights (analytics), and Automation Hub/Action Center (citizen-dev
submission / human-in-the-loop task review) are explicitly out of scope
for this release -- they are either design-time tooling or a materially
different product surface, same boundary discipline as MuleSoft's Design
Center/Access Management exclusion.
"""
from __future__ import annotations

from imperal_sdk import ChatExtension, Extension

ext = Extension(
    "uipath-connector",
    version="0.1.0",
    display_name="UiPath",
    description=(
        "Connect your own UiPath Orchestrator (Automation Cloud or "
        "standalone) to see and manage your processes, jobs, queues, "
        "robots, and assets from Imperal -- list processes and start/stop "
        "jobs against them, manage transaction queues and their items, "
        "browse connected robots, and read/set shared assets. Uses your "
        "own UiPath External Application (OAuth2 client credentials) -- "
        "nothing is hosted or proxied by Imperal beyond the request "
        "itself. Note: this manages processes/jobs/queues/robots/assets "
        "only; Studio (the visual designer), Insights analytics, and "
        "Automation Hub/Action Center human-in-the-loop tasks are out of "
        "scope."
    ),
    icon="icon.svg",
    capabilities=[
        "uipath:read",
        "uipath:write",
    ],
    actions_explicit=True,
    system=False,
)

chat = ChatExtension(
    ext,
    tool_name="uipath",
    description=(
        "UiPath Connector -- connect your own UiPath Orchestrator "
        "organization via an External Application, then list/get "
        "processes, start/stop/monitor jobs, manage queues and queue "
        "items, browse robots, and read/set assets."
    ),
)

ext.secret(
    "uipath_connections",
    (
        "Your connected UiPath Orchestrator organizations -- stored as a "
        "JSON array, one entry per organization/tenant, each with its own "
        "External Application (client_id, client_secret) and "
        "organization_name/tenant_name/default_folder_id. Managed through "
        "connect_uipath / disconnect_uipath -- you should not need to "
        "edit this directly."
    ),
    required=True,
    write_mode="both",
    max_bytes=65536,
    rotation_hint_days=180,
)(lambda: None)


@ext.health_check
async def health_check(ctx) -> dict:
    """Fast configuration health; no third-party call -- just confirms at
    least one organization connection is stored, same shape as MuleSoft
    Connector's health_check."""
    import json as _json
    raw = await ctx.secrets.get("uipath_connections")
    try:
        count = len(_json.loads(raw)) if raw else 0
    except Exception:
        count = 0
    return {
        "healthy": True,
        "detail": (
            f"{count} UiPath organization(s) connected." if count
            else "Not connected yet -- run connect_uipath."
        ),
    }
