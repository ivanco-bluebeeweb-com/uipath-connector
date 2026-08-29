"""Chat functions for UiPath Connector: connection management, Orchestrator
processes (Releases), jobs, queues/queue items, robots, assets, and bulk
operations + folder audit (Ярус 3 value-add). Built on uipath_client.py /
schemas.py, following the same shape as MuleSoft Connector's handlers.py.
"""
from __future__ import annotations

import uuid

from imperal_sdk import ActionResult

import uipath_client as uc
from app import ext, chat
from schemas import (
    NoParams,
    ConnectUipathParams, ProviderConnection, ProviderConnectionList,
    DisconnectUipathParams, DeleteResult,
    ListProcessesParams, OrchestratorProcess, OrchestratorProcessList,
    GetProcessParams,
    ListJobsParams, OrchestratorJob, OrchestratorJobList,
    GetJobParams,
    StartJobParams, StopJobParams, JobActionResult,
    ListQueuesParams, OrchestratorQueue, OrchestratorQueueList,
    ListQueueItemsParams, QueueItem, QueueItemList,
    AddQueueItemParams, SetQueueItemStatusParams,
    ListRobotsParams, OrchestratorRobot, OrchestratorRobotList,
    ListAssetsParams, OrchestratorAsset, OrchestratorAssetList,
    GetAssetParams, SetAssetValueParams,
    BulkJobResultItem, BulkJobResult, BulkJobIdsParams,
    AuditFolderParams, FolderAuditRow, FolderAuditReport,
    ListFoldersParams, OrchestratorFolder, OrchestratorFolderList, GetFolderParams,
    ListMachinesParams, OrchestratorMachine, OrchestratorMachineList, GetMachineParams,
    ListEnvironmentsParams, OrchestratorEnvironment, OrchestratorEnvironmentList,
    ListLibrariesParams, OrchestratorLibrary, OrchestratorLibraryList, GetLibraryParams,
    ListSchedulesParams, OrchestratorSchedule, OrchestratorScheduleList,
    SetScheduleEnabledParams, GetScheduleParams, RunScheduleParams,
    ListBucketsParams, OrchestratorBucket, OrchestratorBucketList,
    ListBucketFilesParams, BucketFile, BucketFileList,
    GetBucketFileReadUriParams, BucketFileReadUri,
    ListWebhooksParams, OrchestratorWebhook, OrchestratorWebhookList,
    CreateWebhookParams, DeleteWebhookParams,
    ListUsersParams, OrchestratorUser, OrchestratorUserList,
    ListAuditLogsParams, OrchestratorAuditLogEntry, OrchestratorAuditLogList,
)

_SECRET_NAME = "uipath_connections"


# ──────────────────────────────────────────────────────────────────────────
# Connection management
# ──────────────────────────────────────────────────────────────────────────


async def _load_connections(ctx) -> list[dict]:
    import json
    raw = await ctx.secrets.get(_SECRET_NAME)
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


async def _save_connections(ctx, connections: list[dict]) -> None:
    import json
    await ctx.secrets.set(_SECRET_NAME, json.dumps(connections))


def _to_provider_connection(c: dict) -> ProviderConnection:
    detail = f"{c.get('organization_name', '')}/{c.get('tenant_name', '')}"
    return ProviderConnection(
        id=c.get("id", ""),
        title=c.get("label") or detail,
        connected=True,
        detail=detail,
        organization_name=c.get("organization_name", ""),
        tenant_name=c.get("tenant_name", ""),
        default_folder_id=c.get("default_folder_id", ""),
    )


async def _resolve_connection(ctx, connection_id: str) -> dict | None:
    connections = await _load_connections(ctx)
    if not connections:
        return None
    if connection_id:
        return next((c for c in connections if c.get("id") == connection_id), None)
    if len(connections) == 1:
        return connections[0]
    return None


_TOKEN_CACHE = "uipath_token_cache"


async def _cached_token(ctx, conn_id: str) -> str:
    import time as _time
    page = await ctx.store.query(_TOKEN_CACHE, where={"connection_id": conn_id}, limit=1)
    if not page.data:
        return ""
    doc = page.data[0].data
    if int(doc.get("expires_at", 0)) <= int(_time.time()):
        return ""
    return doc.get("access_token", "")


async def _store_token(ctx, conn_id: str, access_token: str, expires_in: int) -> None:
    import time as _time
    page = await ctx.store.query(_TOKEN_CACHE, where={"connection_id": conn_id}, limit=1)
    doc = {
        "connection_id": conn_id,
        "access_token": access_token,
        "expires_at": int(_time.time()) + max(int(expires_in or 3600) - 60, 60),
    }
    if page.data:
        await ctx.store.update(_TOKEN_CACHE, page.data[0].id, doc)
    else:
        await ctx.store.create(_TOKEN_CACHE, doc)


async def _get_token_and_conn(ctx, connection_id: str, folder_id_override: str = ""):
    """Resolve the connection, reuse a cached access token when still fresh
    (see AUTH_AND_CREDENTIALS_STANDARD.md Part B3 -- UiPath Identity Server's
    client-credentials token endpoint returns a real expires_in, so re-minting
    a token on every single tool call is unnecessary and risks the token
    endpoint's own rate limit during bulk operations), and return
    (conn, access_token, folder_id) or an ActionResult.error to return
    directly from the calling handler."""
    conn = await _resolve_connection(ctx, connection_id)
    if not conn:
        connections = await _load_connections(ctx)
        if not connections:
            return ActionResult.error("No UiPath organization connected yet. Use connect_uipath first.", code="UIPATH_NOT_CONNECTED")
        return ActionResult.error("Multiple organizations connected -- please specify connection_id.", code="UIPATH_AMBIGUOUS_CONNECTION")
    conn_id = conn.get("id", "")
    access_token = await _cached_token(ctx, conn_id) if conn_id else ""
    if not access_token:
        tok = await uc.get_access_token(ctx, conn["client_id"], conn["client_secret"])
        if not tok.get("ok"):
            return ActionResult.error(tok.get("error", "Could not authenticate with UiPath."), code=tok.get("error_code", "UIPATH_AUTH_FAILED"))
        access_token = tok["access_token"]
        if conn_id:
            await _store_token(ctx, conn_id, access_token, tok.get("expires_in", 3600))
    folder_id = folder_id_override or conn.get("default_folder_id", "")
    return conn, access_token, folder_id


@chat.function(
    "connect_uipath",
    "Connect a UiPath Automation Cloud organization/tenant by saving your own "
    "External Application's client_id/client_secret plus the organization name, "
    "tenant name, and a default Orchestrator Folder id, after checking the "
    "credentials actually work. You'll need: an External Application (Automation "
    "Cloud > Admin > External Applications > create a Confidential Application) "
    "granted the OR.* scopes you want to use (e.g. OR.Jobs, OR.Queues, OR.Robots, "
    "OR.Assets).",
    action_type="write",
    chain_callable=True,
    data_model=ProviderConnection,
    event="uipath-connector.connect_uipath",
    effects=["uipath.provider.connected"],
)
async def connect_uipath(ctx, params: ConnectUipathParams) -> ActionResult:
    """Connect a UiPath Automation Cloud organization/tenant by saving your
    own External Application's client_id/client_secret plus the
    organization name, tenant name, and a default Orchestrator Folder id,
    after checking the credentials actually work."""
    client_id = params.client_id.strip()
    client_secret = params.client_secret.strip()
    organization_name = params.organization_name.strip()
    tenant_name = params.tenant_name.strip()
    default_folder_id = params.default_folder_id.strip()
    missing = [
        n for n, v in [
            ("client_id", client_id), ("client_secret", client_secret),
            ("organization_name", organization_name), ("tenant_name", tenant_name),
            ("default_folder_id", default_folder_id),
        ] if not v
    ]
    if missing:
        return ActionResult.error(f"Please provide: {', '.join(missing)}.", code="UIPATH_MISSING_FIELD")

    check = await uc.check_connection(ctx, client_id, client_secret, organization_name, tenant_name, default_folder_id)
    if not check.get("ok"):
        return ActionResult.error(check.get("error", "Could not verify these credentials."), code=check.get("error_code", "UIPATH_CONNECT_FAILED"))

    connections = await _load_connections(ctx)
    existing = next((c for c in connections if c.get("organization_name") == organization_name and c.get("tenant_name") == tenant_name), None)
    if existing:
        existing.update({
            "client_id": client_id, "client_secret": client_secret,
            "default_folder_id": default_folder_id,
            "label": params.label.strip() or existing.get("label", ""),
        })
        record = existing
    else:
        record = {
            "id": str(uuid.uuid4()),
            "client_id": client_id, "client_secret": client_secret,
            "organization_name": organization_name, "tenant_name": tenant_name,
            "default_folder_id": default_folder_id, "label": params.label.strip(),
        }
        connections.append(record)
    await _save_connections(ctx, connections)
    return ActionResult.ok(_to_provider_connection(record), message=f"Connected UiPath organization '{organization_name}/{tenant_name}'.")


@chat.function(
    "list_connections",
    "List the connected UiPath Automation Cloud organizations/tenants.",
    action_type="read",
    chain_callable=True,
    data_model=ProviderConnectionList,
    event="uipath-connector.list_connections",
)
async def list_connections(ctx, params: NoParams) -> ActionResult:
    """List the connected UiPath Automation Cloud organizations/tenants."""
    connections = await _load_connections(ctx)
    items = [_to_provider_connection(c) for c in connections]
    return ActionResult.ok(ProviderConnectionList(title="UiPath connections", items=items))


@chat.function(
    "disconnect_uipath",
    "Disconnect one UiPath organization/tenant. Nothing in Automation Cloud is "
    "changed; the saved External Application credentials are deleted here.",
    action_type="write",
    chain_callable=True,
    data_model=DeleteResult,
    event="uipath-connector.disconnect_uipath",
    effects=["uipath.provider.disconnected"],
)
async def disconnect_uipath(ctx, params: DisconnectUipathParams) -> ActionResult:
    """Disconnect a UiPath organization/tenant: deletes the saved External
    Application credentials. Existing Orchestrator resources are untouched."""
    connections = await _load_connections(ctx)
    remaining = [c for c in connections if c.get("id") != params.connection_id]
    if len(remaining) == len(connections):
        return ActionResult.error("Connection not found.", code="UIPATH_NOT_FOUND")
    await _save_connections(ctx, remaining)
    return ActionResult.ok(DeleteResult(id=params.connection_id, title="Disconnected", ok=True), message="UiPath organization disconnected.")


# ──────────────────────────────────────────────────────────────────────────
# Processes (Releases)
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_processes",
    "List processes (Orchestrator Releases) available in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorProcessList,
    event="uipath-connector.list_processes",
)
async def list_processes(ctx, params: ListProcessesParams) -> ActionResult:
    """List processes (Orchestrator Releases) available in a Folder."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_processes(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list processes."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [
        OrchestratorProcess(
            id=str(p.get("Id", "")), title=p.get("Name", ""),
            key=p.get("Key", ""), version=p.get("ProcessVersion", ""),
            process_key=p.get("ProcessKey", ""), description=p.get("Description", "") or "",
        )
        for p in raw
        if not params.search or params.search.lower() in p.get("Name", "").lower()
    ]
    return ActionResult.ok(OrchestratorProcessList(title="Processes", items=items))


@chat.function(
    "get_process",
    "Read one process (Release) in full.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorProcess,
    event="uipath-connector.get_process",
)
async def get_process(ctx, params: GetProcessParams) -> ActionResult:
    """Read one process (Release) in full."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        p = await uc.get_process(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.process_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get process."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorProcess(
        id=str(p.get("Id", "")), title=p.get("Name", ""),
        key=p.get("Key", ""), version=p.get("ProcessVersion", ""),
        process_key=p.get("ProcessKey", ""), description=p.get("Description", "") or "",
    ))


# ──────────────────────────────────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_jobs",
    "List recent jobs (process runs) in a Folder, most recent first.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorJobList,
    event="uipath-connector.list_jobs",
)
async def list_jobs(ctx, params: ListJobsParams) -> ActionResult:
    """List recent jobs (process runs) in a Folder, most recent first."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_jobs(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list jobs."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [
        OrchestratorJob(
            id=str(j.get("Id", "")), title=j.get("Key", "") or str(j.get("Id", "")),
            state=j.get("State", ""), process_key=(j.get("ReleaseName") or ""),
            robot_name=(j.get("Robot", {}) or {}).get("Name", "") if isinstance(j.get("Robot"), dict) else "",
            start_time=j.get("StartTime", "") or "", end_time=j.get("EndTime", "") or "",
            info=j.get("Info", "") or "",
        )
        for j in raw
    ]
    return ActionResult.ok(OrchestratorJobList(title="Jobs", items=items))


@chat.function(
    "get_job",
    "Read one job in full -- state, robot, timing, and any error info.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorJob,
    event="uipath-connector.get_job",
)
async def get_job(ctx, params: GetJobParams) -> ActionResult:
    """Read one job in full -- state, robot, timing, and any error info."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        j = await uc.get_job(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.job_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get job."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorJob(
        id=str(j.get("Id", "")), title=j.get("Key", "") or str(j.get("Id", "")),
        state=j.get("State", ""), process_key=(j.get("ReleaseName") or ""),
        robot_name=(j.get("Robot", {}) or {}).get("Name", "") if isinstance(j.get("Robot"), dict) else "",
        start_time=j.get("StartTime", "") or "", end_time=j.get("EndTime", "") or "",
        info=j.get("Info", "") or "",
    ))


@chat.function(
    "start_job",
    "Start a job: run a process (by its Release key) now, either on explicit "
    "robots or letting Orchestrator pick any available robot.",
    action_type="write",
    chain_callable=True,
    data_model=JobActionResult,
    event="uipath-connector.start_job",
    effects=["uipath.job.started"],
)
async def start_job(ctx, params: StartJobParams) -> ActionResult:
    """Start a job: run a process (by its Release key) now, either on
    explicit robots or letting Orchestrator pick any available robot."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    robot_ids = [int(r) for r in params.robot_ids] if params.robot_ids else None
    try:
        result = await uc.start_job(
            ctx, token, conn["organization_name"], conn["tenant_name"], folder_id,
            release_key=params.process_key, robot_ids=robot_ids,
            job_count=params.jobs_count, input_arguments=params.input_arguments,
        )
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to start job."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    started = result.get("value", []) if isinstance(result, dict) else []
    return ActionResult.ok(
        JobActionResult(id=params.process_key, title="Job started", ok=True, detail=f"{len(started)} job(s) started."),
        message=f"Started {len(started)} job(s) for process '{params.process_key}'.",
    )


@chat.function(
    "stop_job",
    "Stop a running job: 'Kill' for immediate termination, or 'SoftStop' to let "
    "the current transaction finish first.",
    action_type="write",
    chain_callable=True,
    data_model=JobActionResult,
    event="uipath-connector.stop_job",
    effects=["uipath.job.stopped"],
)
async def stop_job(ctx, params: StopJobParams) -> ActionResult:
    """Stop a running job: 'Kill' for immediate termination, or 'SoftStop'
    to let the current transaction finish first."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        await uc.stop_job(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.job_id, params.strategy)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to stop job."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(JobActionResult(id=params.job_id, title="Job stop requested", ok=True, detail=params.strategy), message=f"Requested {params.strategy} for job {params.job_id}.")


# ──────────────────────────────────────────────────────────────────────────
# Queues + queue items
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_queues",
    "List queue definitions configured in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorQueueList,
    event="uipath-connector.list_queues",
)
async def list_queues(ctx, params: ListQueuesParams) -> ActionResult:
    """List queue definitions configured in a Folder."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_queue_definitions(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list queues."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [
        OrchestratorQueue(
            id=str(q.get("Id", "")), title=q.get("Name", ""),
            max_retries=q.get("MaxNumberOfRetries", 0) or 0,
            accept_automatically_retry=bool(q.get("AcceptAutomaticallyRetry", False)),
            description=q.get("Description", "") or "",
        )
        for q in raw
    ]
    return ActionResult.ok(OrchestratorQueueList(title="Queues", items=items))


@chat.function(
    "list_queue_items",
    "List transaction items in a queue, optionally filtered by status (New, "
    "InProgress, Successful, Failed, Abandoned, Retried).",
    action_type="read",
    chain_callable=True,
    data_model=QueueItemList,
    event="uipath-connector.list_queue_items",
)
async def list_queue_items(ctx, params: ListQueueItemsParams) -> ActionResult:
    """List transaction items in a queue, optionally filtered by status
    ('New', 'InProgress', 'Successful', 'Failed', 'Abandoned', 'Retried')."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_queue_items(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, queue_name=params.queue_name)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list queue items."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [
        QueueItem(
            id=str(i.get("Id", "")), title=i.get("Reference", "") or str(i.get("Id", "")),
            queue_name=params.queue_name, status=i.get("Status", ""),
            priority=i.get("Priority", ""), reference=i.get("Reference", "") or "",
            retry_number=i.get("RetryNumber", 0) or 0,
        )
        for i in raw
        if not params.status or i.get("Status", "") == params.status
    ]
    return ActionResult.ok(QueueItemList(title=f"Queue items -- {params.queue_name}", items=items))


@chat.function(
    "add_queue_item",
    "Add a new transaction item to a queue -- the payload a process will pick "
    "up and process.",
    action_type="write",
    chain_callable=True,
    data_model=QueueItem,
    event="uipath-connector.add_queue_item",
    effects=["uipath.queue_item.added"],
)
async def add_queue_item(ctx, params: AddQueueItemParams) -> ActionResult:
    """Add a new transaction item to a queue -- the payload a process will
    pick up and process."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        result = await uc.add_queue_item(
            ctx, token, conn["organization_name"], conn["tenant_name"], folder_id,
            queue_name=params.queue_name, specific_content=params.specific_content,
            priority=params.priority, reference=params.reference,
        )
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to add queue item."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(
        QueueItem(id=str(result.get("Id", "")), title=params.reference or str(result.get("Id", "")), queue_name=params.queue_name, status=result.get("Status", "New"), priority=params.priority, reference=params.reference),
        message=f"Added item to queue '{params.queue_name}'.",
    )


@chat.function(
    "set_queue_item_status",
    "Manually set a queue item's outcome to 'Successful' or 'Failed'.",
    action_type="write",
    chain_callable=True,
    data_model=JobActionResult,
    event="uipath-connector.set_queue_item_status",
    effects=["uipath.queue_item.updated"],
)
async def set_queue_item_status(ctx, params: SetQueueItemStatusParams) -> ActionResult:
    """Manually set a queue item's outcome to 'Successful' or 'Failed'."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        await uc.set_queue_item_status(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.queue_item_id, params.status)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to update queue item."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(JobActionResult(id=params.queue_item_id, title="Queue item updated", ok=True, detail=params.status), message=f"Queue item {params.queue_item_id} marked {params.status}.")


# ──────────────────────────────────────────────────────────────────────────
# Robots
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_robots",
    "List robots registered in a Folder -- their machine, status, and type.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorRobotList,
    event="uipath-connector.list_robots",
)
async def list_robots(ctx, params: ListRobotsParams) -> ActionResult:
    """List robots registered in a Folder -- their machine, status, and type."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_robots(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list robots."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [
        OrchestratorRobot(
            id=str(r.get("Id", "")), title=r.get("Name", ""),
            machine_name=r.get("MachineName", "") or "", status=r.get("Status", "") or "",
            type=r.get("Type", "") or "", hostname=r.get("Hostname", "") or "",
        )
        for r in raw
    ]
    return ActionResult.ok(OrchestratorRobotList(title="Robots", items=items))


# ──────────────────────────────────────────────────────────────────────────
# Assets
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_assets",
    "List assets (named configuration values/credentials/text) defined in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorAssetList,
    event="uipath-connector.list_assets",
)
async def list_assets(ctx, params: ListAssetsParams) -> ActionResult:
    """List assets (named configuration values/credentials/text) defined in a Folder."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_assets(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list assets."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [
        OrchestratorAsset(
            id=str(a.get("Id", "")), title=a.get("Name", ""),
            value_type=a.get("ValueType", "") or "",
            value=(a.get("StringValue") or a.get("Value") or "") if a.get("ValueType") != "Credential" else "***",
            description=a.get("Description", "") or "",
        )
        for a in raw
    ]
    return ActionResult.ok(OrchestratorAssetList(title="Assets", items=items))


@chat.function(
    "get_asset",
    "Read one asset's value by name (credential assets never expose their secret).",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorAsset,
    event="uipath-connector.get_asset",
)
async def get_asset(ctx, params: GetAssetParams) -> ActionResult:
    """Read one asset's value by name (credential assets never expose their secret)."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_assets(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get asset."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    match = next((a for a in raw if a.get("Name") == params.asset_name), None)
    if not match:
        return ActionResult.error(f"Asset '{params.asset_name}' not found.", code="UIPATH_NOT_FOUND")
    return ActionResult.ok(OrchestratorAsset(
        id=str(match.get("Id", "")), title=match.get("Name", ""),
        value_type=match.get("ValueType", "") or "",
        value=(match.get("StringValue") or match.get("Value") or "") if match.get("ValueType") != "Credential" else "***",
        description=match.get("Description", "") or "",
    ))


@chat.function(
    "set_asset_value",
    "Update an existing asset's value.",
    action_type="write",
    chain_callable=True,
    data_model=JobActionResult,
    event="uipath-connector.set_asset_value",
    effects=["uipath.asset.updated"],
)
async def set_asset_value(ctx, params: SetAssetValueParams) -> ActionResult:
    """Update an existing asset's value."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_assets(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to update asset."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    match = next((a for a in raw if a.get("Name") == params.asset_name), None)
    if not match:
        return ActionResult.error(f"Asset '{params.asset_name}' not found.", code="UIPATH_NOT_FOUND")
    try:
        await uc.set_asset_value(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, str(match.get("Id")), params.value)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to update asset."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(JobActionResult(id=params.asset_name, title="Asset updated", ok=True, detail=""), message=f"Asset '{params.asset_name}' updated.")


# ──────────────────────────────────────────────────────────────────────────
# Bulk operations + folder audit (Ярус 3 value-add -- not native to the
# Orchestrator API; loops single-item calls with per-item error isolation,
# same principle as MuleSoft Connector's bulk_* handlers)
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "bulk_stop_jobs",
    "Stop several jobs in one call, by explicit job ids. Continues past "
    "per-item failures and reports which ones succeeded/failed.",
    action_type="write",
    chain_callable=True,
    data_model=BulkJobResult,
    event="uipath-connector.bulk_stop_jobs",
    effects=["uipath.job.stopped"],
)
async def bulk_stop_jobs(ctx, params: BulkJobIdsParams) -> ActionResult:
    """Stop several jobs in one call, by explicit job ids. Continues past
    per-item failures and reports which ones succeeded/failed."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    raw_results = await uc.bulk_stop_jobs(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.job_ids, params.strategy)
    items = [BulkJobResultItem(id=r["job_id"], title=r["job_id"], job_id=r["job_id"], ok=r["ok"], error=r.get("error", "")) for r in raw_results]
    succeeded = sum(1 for r in items if r.ok)
    return ActionResult.ok(
        BulkJobResult(title="Bulk stop jobs", items=items, succeeded=succeeded, failed=len(items) - succeeded),
        message=f"Stopped {succeeded}/{len(items)} job(s).",
    )


@chat.function(
    "audit_folder",
    "Build one aggregated health report for a Folder: every process with its "
    "currently running job count and last-24h success/failure counts.",
    action_type="read",
    chain_callable=True,
    data_model=FolderAuditReport,
    event="uipath-connector.audit_folder",
)
async def audit_folder(ctx, params: AuditFolderParams) -> ActionResult:
    """Build one aggregated health report for a Folder: every process with
    its currently running job count and last-24h success/failure counts --
    the Orchestrator API has no single endpoint for this, so it loops
    list_processes + list_jobs and aggregates client-side, same principle
    as MuleSoft Connector's audit_cloudhub_environment."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        processes = await uc.list_processes(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
        jobs = await uc.list_jobs(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, top=200)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to audit folder."), code=e.payload.get("error_code", "UIPATH_ERROR"))

    import datetime
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    def _parse(ts: str):
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        except Exception:
            return None

    rows: list[FolderAuditRow] = []
    total_running = 0
    total_faulted = 0
    for p in processes:
        key = p.get("ProcessKey") or p.get("Name", "")
        related = [j for j in jobs if (j.get("ReleaseName") or "") == p.get("Name", "")]
        running = sum(1 for j in related if j.get("State") in ("Running", "Pending"))
        recent = [j for j in related if (_parse(j.get("StartTime", "")) or cutoff) >= cutoff]
        faulted = sum(1 for j in recent if j.get("State") == "Faulted")
        successful = sum(1 for j in recent if j.get("State") == "Successful")
        total_running += running
        total_faulted += faulted
        rows.append(FolderAuditRow(id=str(p.get("Id", "")), title=p.get("Name", ""), process_key=key, running_jobs=running, faulted_jobs_24h=faulted, successful_jobs_24h=successful))

    return ActionResult.ok(FolderAuditReport(
        title="Folder audit", items=rows,
        total_processes=len(rows), total_running_jobs=total_running, total_faulted_24h=total_faulted,
    ))


@chat.function(
    "list_folders",
    "List Orchestrator Folders (organization units) in the connected tenant.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorFolderList,
    event="uipath-connector.list_folders",
)
async def list_folders(ctx, params: ListFoldersParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, _ = resolved
    try:
        raw = await uc.list_folders(ctx, token, conn["organization_name"], conn["tenant_name"])
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list folders."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorFolder(id=str(f.get("Id", "")), title=f.get("DisplayName", ""), fully_qualified_name=f.get("FullyQualifiedName", ""), description=f.get("Description", "") or "", folder_type=f.get("FolderType", "")) for f in raw]
    return ActionResult.ok(OrchestratorFolderList(title="Orchestrator folders", items=items))


@chat.function(
    "get_folder",
    "Read one Orchestrator Folder in full.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorFolder,
    event="uipath-connector.get_folder",
)
async def get_folder(ctx, params: GetFolderParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, _ = resolved
    try:
        f = await uc.get_folder(ctx, token, conn["organization_name"], conn["tenant_name"], params.folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get folder."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorFolder(id=str(f.get("Id", "")), title=f.get("DisplayName", ""), fully_qualified_name=f.get("FullyQualifiedName", ""), description=f.get("Description", "") or "", folder_type=f.get("FolderType", "")))


@chat.function(
    "list_machines",
    "List Machines (runtime hosts robots run on) registered in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorMachineList,
    event="uipath-connector.list_machines",
)
async def list_machines(ctx, params: ListMachinesParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_machines(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list machines."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorMachine(id=str(m.get("Id", "")), title=m.get("Name", ""), machine_type=m.get("Type", ""), non_production_slots=m.get("NonProductionSlots", 0) or 0, unattended_slots=m.get("UnattendedSlots", 0) or 0) for m in raw]
    return ActionResult.ok(OrchestratorMachineList(title="Orchestrator machines", items=items))


@chat.function(
    "get_machine",
    "Read one Machine in full.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorMachine,
    event="uipath-connector.get_machine",
)
async def get_machine(ctx, params: GetMachineParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        m = await uc.get_machine(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.machine_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get machine."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorMachine(id=str(m.get("Id", "")), title=m.get("Name", ""), machine_type=m.get("Type", ""), non_production_slots=m.get("NonProductionSlots", 0) or 0, unattended_slots=m.get("UnattendedSlots", 0) or 0))


@chat.function(
    "list_environments",
    "List Environments (legacy robot groupings) configured in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorEnvironmentList,
    event="uipath-connector.list_environments",
)
async def list_environments(ctx, params: ListEnvironmentsParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_environments(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list environments."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorEnvironment(id=str(e_.get("Id", "")), title=e_.get("Name", ""), description=e_.get("Description", "") or "") for e_ in raw]
    return ActionResult.ok(OrchestratorEnvironmentList(title="Orchestrator environments", items=items))


@chat.function(
    "list_libraries",
    "List Libraries (shared reusable automation components) published in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorLibraryList,
    event="uipath-connector.list_libraries",
)
async def list_libraries(ctx, params: ListLibrariesParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_libraries(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list libraries."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorLibrary(id=str(l.get("Id", "")), title=l.get("Title", "") or l.get("Name", ""), version=l.get("Version", ""), description=l.get("Description", "") or "") for l in raw]
    return ActionResult.ok(OrchestratorLibraryList(title="Orchestrator libraries", items=items))


@chat.function(
    "get_library",
    "Read one Library in full.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorLibrary,
    event="uipath-connector.get_library",
)
async def get_library(ctx, params: GetLibraryParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_libraries(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get library."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    match = next((l for l in raw if str(l.get("Id", "")) == params.library_id), None)
    if not match:
        return ActionResult.error("Library not found.", code="UIPATH_NOT_FOUND")
    return ActionResult.ok(OrchestratorLibrary(id=str(match.get("Id", "")), title=match.get("Title", "") or match.get("Name", ""), version=match.get("Version", ""), description=match.get("Description", "") or ""))


@chat.function(
    "list_schedules",
    "List Process Schedules (Triggers) -- Orchestrator's own recurring job scheduler -- configured in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorScheduleList,
    event="uipath-connector.list_schedules",
)
async def list_schedules(ctx, params: ListSchedulesParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_schedules(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list schedules."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorSchedule(id=str(s.get("Id", "")), title=s.get("Name", ""), enabled=bool(s.get("Enabled", False)), cron_expression=(s.get("StartProcessCron", "") or ""), process_key=((s.get("StartProcess") or {}).get("ProcessKey", "") if isinstance(s.get("StartProcess"), dict) else "")) for s in raw]
    return ActionResult.ok(OrchestratorScheduleList(title="Orchestrator schedules", items=items))


@chat.function(
    "get_schedule",
    "Read one Process Schedule (Trigger) in full.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorSchedule,
    event="uipath-connector.get_schedule",
)
async def get_schedule(ctx, params: GetScheduleParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        s = await uc.get_schedule(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.schedule_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get schedule."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorSchedule(id=str(s.get("Id", "")), title=s.get("Name", ""), enabled=bool(s.get("Enabled", False)), cron_expression=(s.get("StartProcessCron", "") or ""), process_key=((s.get("StartProcess") or {}).get("ProcessKey", "") if isinstance(s.get("StartProcess"), dict) else "")))


@chat.function(
    "set_schedule_enabled",
    "Enable or disable a Process Schedule (Trigger) without deleting it.",
    action_type="write",
    chain_callable=True,
    data_model=OrchestratorSchedule,
    effects=["update:uipath_schedule"],
    event="uipath-connector.set_schedule_enabled",
)
async def set_schedule_enabled(ctx, params: SetScheduleEnabledParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        s = await uc.set_schedule_enabled(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.schedule_id, params.enabled)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to update schedule."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorSchedule(id=params.schedule_id, title=s.get("Name", ""), enabled=params.enabled, cron_expression=(s.get("StartProcessCron", "") or ""), process_key=""), message=f"Schedule {'enabled' if params.enabled else 'disabled'}.")


@chat.function(
    "run_schedule",
    "Run a Process Schedule (Trigger) right now, regardless of its cron timing.",
    action_type="write",
    chain_callable=True,
    data_model=NoParams,
    effects=["create:uipath_job"],
    event="uipath-connector.run_schedule",
)
async def run_schedule(ctx, params: RunScheduleParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        await uc.run_schedule_now(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.schedule_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to run schedule."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(NoParams(), message="Schedule triggered.")


@chat.function(
    "list_buckets",
    "List Storage Buckets (Orchestrator's own file storage a process can read/write files from) configured in a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorBucketList,
    event="uipath-connector.list_buckets",
)
async def list_buckets(ctx, params: ListBucketsParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_buckets(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list buckets."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorBucket(id=str(b.get("Id", "")), title=b.get("Name", ""), description=b.get("Description", "") or "", identifier=b.get("Identifier", "") or "") for b in raw]
    return ActionResult.ok(OrchestratorBucketList(title="Orchestrator buckets", items=items))


@chat.function(
    "list_bucket_files",
    "List files stored inside one Storage Bucket, optionally under a directory path.",
    action_type="read",
    chain_callable=True,
    data_model=BucketFileList,
    event="uipath-connector.list_bucket_files",
)
async def list_bucket_files(ctx, params: ListBucketFilesParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_bucket_files(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.bucket_id, params.prefix or "/")
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list bucket files."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [BucketFile(id=f.get("FullPath", ""), title=f.get("Name", "") or f.get("FullPath", ""), full_path=f.get("FullPath", ""), content_type=f.get("ContentType", "") or "", size=f.get("Size", 0) or 0) for f in raw]
    return ActionResult.ok(BucketFileList(title="Bucket files", items=items))


@chat.function(
    "get_bucket_file_read_uri",
    "Get a signed, time-limited download URL for one file inside a Storage Bucket.",
    action_type="read",
    chain_callable=True,
    data_model=BucketFileReadUri,
    event="uipath-connector.get_bucket_file_read_uri",
)
async def get_bucket_file_read_uri(ctx, params: GetBucketFileReadUriParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        r = await uc.get_bucket_file_read_uri(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.bucket_id, params.path, params.expiry_minutes)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to get file read URI."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(BucketFileReadUri(url=r.get("Uri", "") or r.get("BlobToken", {}).get("Uri", "") if isinstance(r, dict) else "", expires_in_minutes=params.expiry_minutes))


@chat.function(
    "list_webhooks",
    "List Webhooks (Orchestrator's own event push subscriptions) configured on the connected tenant.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorWebhookList,
    event="uipath-connector.list_webhooks",
)
async def list_webhooks(ctx, params: ListWebhooksParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_webhooks(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list webhooks."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorWebhook(id=str(w.get("Id", "")), title=w.get("Name", "") or w.get("Url", ""), url=w.get("Url", ""), enabled=bool(w.get("Enabled", False))) for w in raw]
    return ActionResult.ok(OrchestratorWebhookList(title="Orchestrator webhooks", items=items))


@chat.function(
    "create_webhook",
    "Create a new Webhook subscription: Orchestrator will POST events to your URL as they happen "
    "(e.g. job.completed, job.faulted) instead of you having to poll.",
    action_type="write",
    chain_callable=True,
    data_model=OrchestratorWebhook,
    effects=["create:uipath_webhook"],
    event="uipath-connector.create_webhook",
)
async def create_webhook(ctx, params: CreateWebhookParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        w = await uc.create_webhook(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, url=params.url, events=params.events, secret=params.secret)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to create webhook."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(OrchestratorWebhook(id=str(w.get("Id", "")), title=w.get("Name", "") or w.get("Url", ""), url=w.get("Url", ""), enabled=bool(w.get("Enabled", False))), message="Webhook created.")


@chat.function(
    "delete_webhook",
    "Permanently remove a Webhook subscription. Cannot be undone.",
    action_type="write",
    chain_callable=True,
    data_model=DeleteResult,
    effects=["delete:uipath_webhook"],
    event="uipath-connector.delete_webhook",
)
async def delete_webhook(ctx, params: DeleteWebhookParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        await uc.delete_webhook(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, params.webhook_id)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to delete webhook."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    return ActionResult.ok(DeleteResult(deleted=True), message="Webhook deleted.")


@chat.function(
    "list_users",
    "List Users registered in the connected UiPath Automation Cloud organization.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorUserList,
    event="uipath-connector.list_users",
)
async def list_users(ctx, params: ListUsersParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, _ = resolved
    try:
        raw = await uc.list_users(ctx, token, conn["organization_name"], conn["tenant_name"])
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list users."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorUser(id=str(u.get("Id", "")), title=u.get("Name", "") or u.get("UserName", ""), username=u.get("UserName", ""), email=u.get("Email", "") or "", is_active=not bool(u.get("IsDisabled", False))) for u in raw]
    return ActionResult.ok(OrchestratorUserList(title="Orchestrator users", items=items))


@chat.function(
    "list_audit_logs",
    "List Audit Log entries -- Orchestrator's own record of who did what and when -- for a Folder.",
    action_type="read",
    chain_callable=True,
    data_model=OrchestratorAuditLogList,
    event="uipath-connector.list_audit_logs",
)
async def list_audit_logs(ctx, params: ListAuditLogsParams) -> ActionResult:
    """Execute this UiPath Orchestrator operation."""
    resolved = await _get_token_and_conn(ctx, params.connection_id, params.folder_id)
    if isinstance(resolved, ActionResult):
        return resolved
    conn, token, folder_id = resolved
    try:
        raw = await uc.list_audit_logs(ctx, token, conn["organization_name"], conn["tenant_name"], folder_id, top=params.top)
    except uc.ClientFail as e:
        return ActionResult.error(e.payload.get("error", "Failed to list audit logs."), code=e.payload.get("error_code", "UIPATH_ERROR"))
    items = [OrchestratorAuditLogEntry(id=str(a.get("Id", "")), title=(str(a.get("Component", "") or "") + ": " + str(a.get("Action", "") or "")), component=a.get("Component", "") or "", action=a.get("Action", "") or "", execution_time=a.get("ExecutionTime", "") or "", user_name=a.get("User", "") or "") for a in raw]
    return ActionResult.ok(OrchestratorAuditLogList(title="Orchestrator audit logs", items=items))
