"""UiPath Orchestrator HTTP client -- OAuth2 client-credentials auth against
a user's own External Application, thin wrappers around the Orchestrator
OData REST API (processes/jobs/queues/robots/assets).

WHY CLIENT CREDENTIALS (External Application), NOT DELEGATED USER OAUTH --
see app.py module docstring for the full architectural reasoning. Token is
requested against UiPath's own Identity Server
(`https://cloud.uipath.com/identity_/connect/token`) with
`grant_type=client_credentials` and the External Application's scopes
(e.g. `OR.Jobs OR.Queues OR.Robots OR.Assets`).

WHY ORCHESTRATOR OData API AS THE PRIMARY SURFACE.

Orchestrator exposes its own resources (Releases, Jobs, QueueDefinitions,
QueueItems, Robots, Assets) as an OData v4 API under
`/{organization}/{tenant}/orchestrator_/odata/*`
(docs.uipath.com/orchestrator -- Orchestrator HTTP API Access, confirmed
2026-08-20). Nearly every call also requires an
`X-UIPATH-OrganizationUnitId` header carrying the Folder id -- Orchestrator
resources are folder-scoped by design (the modern replacement for
"organization unit"), so this is required per-request routing, not an
optional filter, same principle as MuleSoft's X-ANYPNT-ORG-ID/ENV-ID pair.

WHY 401 vs 403 ARE HANDLED DIFFERENTLY, SAME PRINCIPLE AS MuleSoft/n8n/
Make.com/Power Automate CONNECTOR's clients.

A 401 means the External Application's credentials are not accepted at
all (wrong client_id/client_secret, or the token request itself failed).
A 403 means the token was issued fine, but the caller lacks the
Orchestrator permission/scope (e.g. "Jobs.Create") or Folder access for
this specific operation -- a materially different, more specific and
more fixable cause (the fix is granting a permission/Folder assignment in
Orchestrator, not re-entering credentials) that must not be reported as
"wrong credentials".
"""
from __future__ import annotations

IDENTITY_TOKEN_URL = "https://cloud.uipath.com/identity_/connect/token"

ACCOUNT_MISSING = "UIPATH_ACCOUNT_MISSING"
TOKEN_REJECTED = "UIPATH_TOKEN_REJECTED"
PERMISSION_DENIED = "UIPATH_PERMISSION_DENIED"
NOT_FOUND = "UIPATH_NOT_FOUND"
VALIDATION_FAILED = "UIPATH_VALIDATION_FAILED"
RESPONSE_UNEXPECTED = "UIPATH_RESPONSE_UNEXPECTED"
UNREACHABLE = "UIPATH_UNREACHABLE"
RATE_LIMITED = "UIPATH_RATE_LIMITED"
BACKEND_5XX = "UIPATH_BACKEND_5XX"
BACKEND_TIMEOUT = "UIPATH_BACKEND_TIMEOUT"

_MESSAGES = {
    ACCOUNT_MISSING: "No UiPath organization is connected yet.",
    TOKEN_REJECTED: "UiPath rejected these credentials. Check the client ID and client secret, then reconnect.",
    PERMISSION_DENIED: "UiPath accepted the credentials, but this External Application lacks the scope or Folder access for this operation. Grant it the required scope (e.g. \"OR.Jobs\") and Folder assignment in Orchestrator.",
    NOT_FOUND: "Orchestrator has no such process/job/queue/robot/asset, or this Folder cannot access it.",
    VALIDATION_FAILED: "Orchestrator rejected the request as invalid.",
    RESPONSE_UNEXPECTED: "Orchestrator returned a response the connector could not safely interpret.",
    UNREACHABLE: "Could not reach UiPath Orchestrator.",
    RATE_LIMITED: "UiPath is rate-limiting requests; try again shortly.",
    BACKEND_5XX: "UiPath returned a server error; try again shortly.",
    BACKEND_TIMEOUT: "UiPath took too long to respond; try again shortly.",
}
_RETRYABLE = {RATE_LIMITED, BACKEND_5XX, BACKEND_TIMEOUT}


def fail(code: str, detail: str = "") -> dict:
    message = _MESSAGES.get(code, code)
    if detail:
        message = f"{message} ({detail})"
    return {"ok": False, "error_code": code, "error": message, "retryable": code in _RETRYABLE}


class ClientFail(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("error", "UiPath request failed"))
        self.payload = payload


def _orch_base(organization_name: str, tenant_name: str) -> str:
    return f"https://cloud.uipath.com/{organization_name}/{tenant_name}/orchestrator_/odata"


async def get_access_token(ctx, client_id: str, client_secret: str) -> dict:
    """Client-credentials token request against UiPath's own Identity
    Server. Returns {"ok": True, "access_token": ...} or a fail() dict."""
    resp = await ctx.http.post(
        IDENTITY_TOKEN_URL,
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code in (400, 401):
        return fail(TOKEN_REJECTED)
    if resp.status_code >= 500:
        return fail(BACKEND_5XX)
    if resp.status_code != 200:
        return fail(RESPONSE_UNEXPECTED, f"token endpoint returned {resp.status_code}")
    body = resp.body if isinstance(resp.body, dict) else {}
    token = body.get("access_token")
    if not token:
        return fail(RESPONSE_UNEXPECTED, "token response had no access_token")
    return {"ok": True, "access_token": token, "expires_in": body.get("expires_in", 3600)}


def _headers(access_token: str, folder_id: str) -> dict:
    h = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if folder_id:
        h["X-UIPATH-OrganizationUnitId"] = str(folder_id)
    return h


def _check_status(resp, action: str) -> dict | list:
    if resp.status_code in (200, 201, 202, 204):
        if resp.status_code == 204:
            return {}
        return resp.body if isinstance(resp.body, (dict, list)) else {}
    if resp.status_code == 401:
        raise ClientFail(fail(TOKEN_REJECTED, action))
    if resp.status_code == 403:
        raise ClientFail(fail(PERMISSION_DENIED, action))
    if resp.status_code == 404:
        raise ClientFail(fail(NOT_FOUND, action))
    if resp.status_code == 429:
        raise ClientFail(fail(RATE_LIMITED, action))
    if resp.status_code >= 500:
        raise ClientFail(fail(BACKEND_5XX, action))
    if resp.status_code == 400:
        raise ClientFail(fail(VALIDATION_FAILED, action))
    raise ClientFail(fail(RESPONSE_UNEXPECTED, f"{action}: HTTP {resp.status_code}"))


async def check_connection(
    ctx, client_id: str, client_secret: str, organization_name: str, tenant_name: str, folder_id: str,
) -> dict:
    """Get a token, then a cheap GET Releases to prove the External
    Application actually has a working scope/Folder access -- a valid
    token alone does not guarantee Orchestrator access (see
    PERMISSION_DENIED docstring above)."""
    tok = await get_access_token(ctx, client_id, client_secret)
    if not tok.get("ok"):
        return tok
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Releases",
        headers=_headers(tok["access_token"], folder_id),
        params={"$top": 1},
    )
    try:
        _check_status(resp, "verify connection")
    except ClientFail as e:
        return e.payload
    return {"ok": True}


# ──────────────────────────────────────────────────────────────────────────
# Processes (Releases)
# ──────────────────────────────────────────────────────────────────────────


async def list_processes(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Releases",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list processes")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def get_process(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, process_id: str) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Releases({process_id})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "get process")


# ──────────────────────────────────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────────────────────────────────


async def list_jobs(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, *, top: int = 50) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Jobs",
        headers=_headers(access_token, folder_id),
        params={"$top": top, "$orderby": "CreationTime desc"},
    )
    body = _check_status(resp, "list jobs")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def get_job(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, job_id: str) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Jobs({job_id})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "get job")


async def start_job(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, *,
    release_key: str, robot_ids: list[int] | None = None, job_count: int = 1, input_arguments: dict | None = None,
) -> dict:
    """Orchestrator's own StartJobs action -- POST Jobs/UiPath.Server.
    Configuration.OData.StartJobs. Runs a release either on explicit
    robot ids or lets Orchestrator pick (job_count) via a dynamically
    allocated robot."""
    strategy = "Specific" if robot_ids else "JobsCount"
    payload = {
        "startInfo": {
            "ReleaseKey": release_key,
            "Strategy": strategy,
            "JobsCount": job_count if not robot_ids else 0,
            "RobotIds": robot_ids or [],
            "InputArguments": __import__("json").dumps(input_arguments) if input_arguments else None,
        }
    }
    resp = await ctx.http.post(
        f"{_orch_base(organization_name, tenant_name)}/Jobs/UiPath.Server.Configuration.OData.StartJobs",
        headers=_headers(access_token, folder_id),
        json=payload,
    )
    return _check_status(resp, "start job")


async def stop_job(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, job_id: str, strategy: str = "Kill") -> dict:
    """strategy: 'Kill' (immediate) or 'SoftStop' (finish current transaction first)."""
    resp = await ctx.http.post(
        f"{_orch_base(organization_name, tenant_name)}/Jobs({job_id})/UiPath.Server.Configuration.OData.StopJob",
        headers=_headers(access_token, folder_id),
        json={"strategy": strategy},
    )
    return _check_status(resp, "stop job")


# ──────────────────────────────────────────────────────────────────────────
# Queues
# ──────────────────────────────────────────────────────────────────────────


async def list_queue_definitions(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/QueueDefinitions",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list queue definitions")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def list_queue_items(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, *,
    queue_name: str | None = None, top: int = 50,
) -> list[dict]:
    params = {"$top": top, "$orderby": "CreationTime desc"}
    if queue_name:
        params["$filter"] = f"QueueDefinition/Name eq '{queue_name}'"
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/QueueItems",
        headers=_headers(access_token, folder_id),
        params=params,
    )
    body = _check_status(resp, "list queue items")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def add_queue_item(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, *,
    queue_name: str, specific_content: dict, priority: str = "Normal", reference: str = "",
) -> dict:
    payload = {
        "itemData": {
            "Name": queue_name,
            "Priority": priority,
            "SpecificContent": specific_content,
            "Reference": reference or None,
        }
    }
    resp = await ctx.http.post(
        f"{_orch_base(organization_name, tenant_name)}/Queues/UiPathODataSvc.AddQueueItem",
        headers=_headers(access_token, folder_id),
        json=payload,
    )
    return _check_status(resp, "add queue item")


async def set_queue_item_status(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, item_id: str, status: str,
) -> dict:
    """status: 'Successful', 'Failed', 'Abandoned' -- Orchestrator's own
    SetTransactionResult / manual status override for a queue item."""
    resp = await ctx.http.post(
        f"{_orch_base(organization_name, tenant_name)}/QueueItems({item_id})/UiPathODataSvc.SetTransactionResult",
        headers=_headers(access_token, folder_id),
        json={"transactionResult": {"IsSuccessful": status == "Successful", "ProcessingException": None}},
    )
    return _check_status(resp, "set queue item status")


# ──────────────────────────────────────────────────────────────────────────
# Robots
# ──────────────────────────────────────────────────────────────────────────


async def list_robots(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Robots",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list robots")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


# ──────────────────────────────────────────────────────────────────────────
# Assets
# ──────────────────────────────────────────────────────────────────────────


async def list_assets(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Assets",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list assets")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def set_asset_value(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, asset_id: str, value: str,
) -> dict:
    resp = await ctx.http.put(
        f"{_orch_base(organization_name, tenant_name)}/Assets({asset_id})",
        headers=_headers(access_token, folder_id),
        json={"Value": value},
    )
    return _check_status(resp, "update asset")


# ──────────────────────────────────────────────────────────────────────────
# Bulk operations + folder audit (Ярус 3 value-add -- NOT native to the
# Orchestrator API; this connector's own convenience layer, looping the
# single-item calls above with per-item error isolation so one bad job
# doesn't abort the rest, same principle as MuleSoft Connector's
# bulk_set_application_status/bulk_delete_applications).
# ──────────────────────────────────────────────────────────────────────────


async def bulk_stop_jobs(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, job_ids: list[str], strategy: str = "Kill",
) -> list[dict]:
    results = []
    for job_id in job_ids:
        try:
            await stop_job(ctx, access_token, organization_name, tenant_name, folder_id, job_id, strategy)
            results.append({"job_id": job_id, "ok": True})
        except ClientFail as e:
            results.append({"job_id": job_id, "ok": False, "error": e.payload.get("error")})
    return results


# ──────────────────────────────────────────────────────────────────────────
# Folders (Orchestrator's multi-tenant organizational units -- the modern
# replacement for "organization units"; every resource above is scoped to
# one, so listing/reading them is what lets a caller discover valid
# folder_id values instead of having to already know one)
# ──────────────────────────────────────────────────────────────────────────


async def list_folders(ctx, access_token: str, organization_name: str, tenant_name: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Folders",
        headers=_headers(access_token, ""),
    )
    body = _check_status(resp, "list folders")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def get_folder(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Folders({folder_id})",
        headers=_headers(access_token, ""),
    )
    return _check_status(resp, "get folder")


# ──────────────────────────────────────────────────────────────────────────
# Machines (the machine templates/runtimes robots run on)
# ──────────────────────────────────────────────────────────────────────────


async def list_machines(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Machines",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list machines")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def get_machine(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, machine_id: str) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Machines({machine_id})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "get machine")


# ──────────────────────────────────────────────────────────────────────────
# Environments (classic robot groupings within a Folder)
# ──────────────────────────────────────────────────────────────────────────


async def list_environments(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Environments",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list environments")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


# ──────────────────────────────────────────────────────────────────────────
# Libraries (published reusable automation packages, distinct from
# Processes/Releases which are the runnable, versioned deployments of them)
# ──────────────────────────────────────────────────────────────────────────


async def list_libraries(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Libraries",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list libraries")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def get_library(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, library_id: str) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Libraries({library_id})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "get library")


# ──────────────────────────────────────────────────────────────────────────
# Schedules (ProcessSchedules -- time-based triggers for a process)
# ──────────────────────────────────────────────────────────────────────────


async def list_schedules(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/ProcessSchedules",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list schedules")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def get_schedule(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, schedule_id: str) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/ProcessSchedules({schedule_id})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "get schedule")


async def set_schedule_enabled(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, schedule_id: str, enabled: bool,
) -> dict:
    resp = await ctx.http.patch(
        f"{_orch_base(organization_name, tenant_name)}/ProcessSchedules({schedule_id})",
        headers=_headers(access_token, folder_id),
        json={"Enabled": enabled},
    )
    return _check_status(resp, "set schedule enabled")


async def run_schedule_now(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, schedule_id: str) -> dict:
    resp = await ctx.http.post(
        f"{_orch_base(organization_name, tenant_name)}/ProcessSchedules({schedule_id})/UiPath.Server.Configuration.OData.RunNow",
        headers=_headers(access_token, folder_id),
        json={},
    )
    return _check_status(resp, "run schedule now")


# ──────────────────────────────────────────────────────────────────────────
# Buckets (Orchestrator's own file storage a process can read/write files
# from -- distinct from Assets, which hold small config values/credentials)
# ──────────────────────────────────────────────────────────────────────────


async def list_buckets(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Buckets",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list buckets")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def list_bucket_files(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, bucket_id: str, directory_path: str = "/",
) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Buckets({bucket_id})/UiPath.Server.Configuration.OData.GetFiles(directoryPath='{directory_path}')",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list bucket files")
    return body.get("value", []) if isinstance(body, dict) else (body if isinstance(body, list) else [])


async def get_bucket_file_read_uri(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, bucket_id: str, path: str, expiry_minutes: int = 30,
) -> dict:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Buckets({bucket_id})/UiPath.Server.Configuration.OData.GetReadUri(path='{path}',expiryInMinutes={expiry_minutes})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "get bucket file read uri")


# ──────────────────────────────────────────────────────────────────────────
# Webhooks (Orchestrator's own event push subscriptions)
# ──────────────────────────────────────────────────────────────────────────


async def list_webhooks(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Webhooks",
        headers=_headers(access_token, folder_id),
    )
    body = _check_status(resp, "list webhooks")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


async def create_webhook(
    ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, *, url: str, events: list[str], secret: str = "",
) -> dict:
    resp = await ctx.http.post(
        f"{_orch_base(organization_name, tenant_name)}/Webhooks",
        headers=_headers(access_token, folder_id),
        json={"Url": url, "Enabled": True, "Events": [{"Type": e} for e in events], "Secret": secret or None, "SubscribeAllEvents": not events},
    )
    return _check_status(resp, "create webhook")


async def delete_webhook(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, webhook_id: str) -> dict:
    resp = await ctx.http.delete(
        f"{_orch_base(organization_name, tenant_name)}/Webhooks({webhook_id})",
        headers=_headers(access_token, folder_id),
    )
    return _check_status(resp, "delete webhook")


# ──────────────────────────────────────────────────────────────────────────
# Users
# ──────────────────────────────────────────────────────────────────────────


async def list_users(ctx, access_token: str, organization_name: str, tenant_name: str) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/Users",
        headers=_headers(access_token, ""),
    )
    body = _check_status(resp, "list users")
    return body.get("value", []) if isinstance(body, dict) else (body or [])


# ──────────────────────────────────────────────────────────────────────────
# Audit Logs
# ──────────────────────────────────────────────────────────────────────────


async def list_audit_logs(ctx, access_token: str, organization_name: str, tenant_name: str, folder_id: str, *, top: int = 50) -> list[dict]:
    resp = await ctx.http.get(
        f"{_orch_base(organization_name, tenant_name)}/AuditLogs",
        headers=_headers(access_token, folder_id),
        params={"$top": top, "$orderby": "ExecutionTime desc"},
    )
    body = _check_status(resp, "list audit logs")
    return body.get("value", []) if isinstance(body, dict) else (body or [])
