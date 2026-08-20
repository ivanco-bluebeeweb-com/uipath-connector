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


async def _get_token_and_conn(ctx, connection_id: str, folder_id_override: str = ""):
    """Resolve the connection, mint an access token, and return
    (conn, access_token, folder_id) or an ActionResult.error to return
    directly from the calling handler."""
    conn = await _resolve_connection(ctx, connection_id)
    if not conn:
        connections = await _load_connections(ctx)
        if not connections:
            return ActionResult.error("No UiPath organization connected yet. Use connect_uipath first.", code="UIPATH_NOT_CONNECTED")
        return ActionResult.error("Multiple organizations connected -- please specify connection_id.", code="UIPATH_AMBIGUOUS_CONNECTION")
    tok = await uc.get_access_token(ctx, conn["client_id"], conn["client_secret"])
    if not tok.get("ok"):
        return ActionResult.error(tok.get("error", "Could not authenticate with UiPath."), code=tok.get("error_code", "UIPATH_AUTH_FAILED"))
    folder_id = folder_id_override or conn.get("default_folder_id", "")
    return conn, tok["access_token"], folder_id


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
