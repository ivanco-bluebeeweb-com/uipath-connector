"""Pydantic params models + SDL entity contracts for UiPath Connector.

All params models are module-scope (V17 federal invariant, same rule as
MuleSoft Connector / Power Automate Connector / Make.com Connector / n8n
Connector's schemas.py).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk import sdl


class NoParams(BaseModel):
    """Explicit empty params model -- V17 disallows untyped handlers."""
    pass


# ──────────────────────────────────────────────────────────────────────────
# Connection
# ──────────────────────────────────────────────────────────────────────────


class ConnectUipathParams(BaseModel):
    client_id: str = Field(
        "",
        description="Client ID of the UiPath External Application created for this connection.",
    )
    client_secret: str = Field(
        "",
        description="Client secret (or App Secret) of the UiPath External Application.",
    )
    organization_name: str = Field(
        "",
        description="Your UiPath Automation Cloud organization's logical name (from the account URL).",
    )
    tenant_name: str = Field(
        "",
        description="The tenant's logical name within the organization.",
    )
    default_folder_id: str = Field(
        "",
        description="Default Orchestrator Folder ID to operate in (most calls are folder-scoped). Found in Orchestrator > Folder settings.",
    )
    label: str = Field("", description="Optional friendly name for this organization/tenant connection.")


class ProviderConnection(sdl.Entity):
    id: str = ""
    title: str = ""
    connected: bool = False
    detail: str = ""
    organization_name: str = ""
    tenant_name: str = ""
    default_folder_id: str = ""


class ProviderConnectionList(sdl.Entity):
    id: str = "provider_connection_list"
    title: str = ""
    items: list[ProviderConnection] = Field(default_factory=list)


class DisconnectUipathParams(BaseModel):
    connection_id: str = Field(..., description="Connection id to disconnect, from list_connections.")


class DeleteResult(sdl.Entity):
    id: str = ""
    title: str = ""
    ok: bool = True


# ──────────────────────────────────────────────────────────────────────────
# Processes (release definitions)
# ──────────────────────────────────────────────────────────────────────────


class ListProcessesParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID to look in. Omit to use the connection's default folder.")
    search: str | None = Field(None, description="Optional process name substring filter.")


class OrchestratorProcess(sdl.Entity):
    id: str = ""
    title: str = ""
    key: str = ""
    version: str = ""
    process_key: str = ""
    description: str = ""


class OrchestratorProcessList(sdl.Entity):
    id: str = "orchestrator_process_list"
    title: str = ""
    items: list[OrchestratorProcess] = Field(default_factory=list)


class GetProcessParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    process_id: str = Field(..., description="Process (release) id, from list_processes.")


# ──────────────────────────────────────────────────────────────────────────
# Jobs (process runs)
# ──────────────────────────────────────────────────────────────────────────


class ListJobsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    state: str | None = Field(None, description="Optional job state filter, e.g. 'Running', 'Successful', 'Faulted'.")


class OrchestratorJob(sdl.Entity):
    id: str = ""
    title: str = ""
    state: str = ""
    process_key: str = ""
    robot_name: str = ""
    start_time: str = ""
    end_time: str = ""
    info: str = ""


class OrchestratorJobList(sdl.Entity):
    id: str = "orchestrator_job_list"
    title: str = ""
    items: list[OrchestratorJob] = Field(default_factory=list)


class GetJobParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    job_id: str = Field(..., description="Job id, from list_jobs.")


class StartJobParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    process_key: str = Field(..., description="Process (release) key to start a job for, from list_processes.")
    robot_ids: list[str] | None = Field(None, description="Explicit robot ids to run on. Omit to let Orchestrator pick any available robot in the folder (JobsCount strategy).")
    jobs_count: int = Field(1, ge=1, le=50, description="How many job instances to start when robot_ids is omitted.")
    input_arguments: dict | None = Field(None, description="Input arguments to pass to the process, as key/value pairs.")


class StopJobParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    job_id: str = Field(..., description="Job id to stop, from list_jobs.")
    strategy: str = Field("Kill", description="'Kill' (immediate) or 'SoftStop' (finish current transaction first).")


class JobActionResult(sdl.Entity):
    id: str = ""
    title: str = ""
    ok: bool = True
    detail: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Queues + queue items
# ──────────────────────────────────────────────────────────────────────────


class ListQueuesParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorQueue(sdl.Entity):
    id: str = ""
    title: str = ""
    max_retries: int = 0
    accept_automatically_retry: bool = False
    description: str = ""


class OrchestratorQueueList(sdl.Entity):
    id: str = "orchestrator_queue_list"
    title: str = ""
    items: list[OrchestratorQueue] = Field(default_factory=list)


class ListQueueItemsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    queue_name: str = Field(..., description="Queue definition name, from list_queues.")
    status: str | None = Field(None, description="Optional queue item status filter, e.g. 'New', 'InProgress', 'Successful', 'Failed'.")


class QueueItem(sdl.Entity):
    id: str = ""
    title: str = ""
    queue_name: str = ""
    status: str = ""
    priority: str = ""
    reference: str = ""
    retry_number: int = 0


class QueueItemList(sdl.Entity):
    id: str = "queue_item_list"
    title: str = ""
    items: list[QueueItem] = Field(default_factory=list)


class AddQueueItemParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    queue_name: str = Field(..., description="Queue definition name to add the item to.")
    priority: str = Field("Normal", description="'Low', 'Normal', or 'High'.")
    reference: str = Field("", description="Optional human-readable reference/business key for this item.")
    specific_content: dict = Field(default_factory=dict, description="The transaction payload as key/value pairs -- what the process will read.")


class SetQueueItemStatusParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    queue_item_id: str = Field(..., description="Queue item id, from list_queue_items.")
    status: str = Field(..., description="'Successful' or 'Failed'.")
    is_reprocessable: bool = Field(False, description="For 'Failed' only: whether Orchestrator should retry this item automatically.")
    reason: str = Field("", description="Optional note explaining the outcome.")


# ──────────────────────────────────────────────────────────────────────────
# Robots
# ──────────────────────────────────────────────────────────────────────────


class ListRobotsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorRobot(sdl.Entity):
    id: str = ""
    title: str = ""
    machine_name: str = ""
    status: str = ""
    type: str = ""
    hostname: str = ""


class OrchestratorRobotList(sdl.Entity):
    id: str = "orchestrator_robot_list"
    title: str = ""
    items: list[OrchestratorRobot] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Assets
# ──────────────────────────────────────────────────────────────────────────


class ListAssetsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorAsset(sdl.Entity):
    id: str = ""
    title: str = ""
    value_type: str = ""
    value: str = ""
    description: str = ""


class OrchestratorAssetList(sdl.Entity):
    id: str = "orchestrator_asset_list"
    title: str = ""
    items: list[OrchestratorAsset] = Field(default_factory=list)


class GetAssetParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    asset_name: str = Field(..., description="Asset name, from list_assets.")


class SetAssetValueParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    asset_name: str = Field(..., description="Asset name to update, from list_assets.")
    value: str = Field(..., description="New asset value (as text; interpreted per the asset's own value type).")


# ──────────────────────────────────────────────────────────────────────────
# Bulk operations + folder audit (Ярус 3 value-add -- not native to the
# Orchestrator API)
# ──────────────────────────────────────────────────────────────────────────


class BulkJobResultItem(sdl.Entity):
    id: str = ""
    title: str = ""
    job_id: str = ""
    ok: bool = True
    error: str = ""


class BulkJobResult(sdl.Entity):
    id: str = "bulk_job_result"
    title: str = ""
    items: list[BulkJobResultItem] = Field(default_factory=list)
    succeeded: int = 0
    failed: int = 0


class BulkJobIdsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    job_ids: list[str] = Field(
        ..., min_length=1, max_length=100,
        description="Explicit job ids; 1-100, never inferred.",
    )
    strategy: str = Field("Kill", description="'Kill' (immediate) or 'SoftStop' (finish current transaction first). Only used for stop.")


class AuditFolderParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class FolderAuditRow(sdl.Entity):
    id: str = ""
    title: str = ""
    process_key: str = ""
    running_jobs: int = 0
    faulted_jobs_24h: int = 0
    successful_jobs_24h: int = 0


class FolderAuditReport(sdl.Entity):
    id: str = "folder_audit_report"
    title: str = ""
    items: list[FolderAuditRow] = Field(default_factory=list)
    total_processes: int = 0
    total_running_jobs: int = 0
    total_faulted_24h: int = 0


# ──────────────────────────────────────────────────────────────────────────
# Folders
# ──────────────────────────────────────────────────────────────────────────


class ListFoldersParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")


class OrchestratorFolder(sdl.Entity):
    id: str = ""
    title: str = ""
    fully_qualified_name: str = ""
    description: str = ""
    folder_type: str = ""


class OrchestratorFolderList(sdl.Entity):
    id: str = "orchestrator_folder_list"
    title: str = ""
    items: list[OrchestratorFolder] = Field(default_factory=list)


class GetFolderParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field(..., description="Folder id, from list_folders.")


# ──────────────────────────────────────────────────────────────────────────
# Machines
# ──────────────────────────────────────────────────────────────────────────


class ListMachinesParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorMachine(sdl.Entity):
    id: str = ""
    title: str = ""
    machine_type: str = ""
    non_production_slots: int = 0
    unattended_slots: int = 0


class OrchestratorMachineList(sdl.Entity):
    id: str = "orchestrator_machine_list"
    title: str = ""
    items: list[OrchestratorMachine] = Field(default_factory=list)


class GetMachineParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    machine_id: str = Field(..., description="Machine id, from list_machines.")


# ──────────────────────────────────────────────────────────────────────────
# Environments
# ──────────────────────────────────────────────────────────────────────────


class ListEnvironmentsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorEnvironment(sdl.Entity):
    id: str = ""
    title: str = ""
    description: str = ""


class OrchestratorEnvironmentList(sdl.Entity):
    id: str = "orchestrator_environment_list"
    title: str = ""
    items: list[OrchestratorEnvironment] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Libraries
# ──────────────────────────────────────────────────────────────────────────


class ListLibrariesParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorLibrary(sdl.Entity):
    id: str = ""
    title: str = ""
    version: str = ""
    description: str = ""


class OrchestratorLibraryList(sdl.Entity):
    id: str = "orchestrator_library_list"
    title: str = ""
    items: list[OrchestratorLibrary] = Field(default_factory=list)


class GetLibraryParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    library_id: str = Field(..., description="Library id, from list_libraries.")


# ──────────────────────────────────────────────────────────────────────────
# Process Schedules (Triggers)
# ──────────────────────────────────────────────────────────────────────────


class ListSchedulesParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorSchedule(sdl.Entity):
    id: str = ""
    title: str = ""
    enabled: bool = False
    cron_expression: str = ""
    process_key: str = ""


class OrchestratorScheduleList(sdl.Entity):
    id: str = "orchestrator_schedule_list"
    title: str = ""
    items: list[OrchestratorSchedule] = Field(default_factory=list)


class SetScheduleEnabledParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    schedule_id: str = Field(..., description="Schedule (trigger) id, from list_schedules.")
    enabled: bool = Field(..., description="True to enable, False to disable the schedule.")


class GetScheduleParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    schedule_id: str = Field(..., description="Schedule (trigger) id, from list_schedules.")


class RunScheduleParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    schedule_id: str = Field(..., description="Schedule (trigger) id, from list_schedules.")


# ──────────────────────────────────────────────────────────────────────────
# Storage Buckets
# ──────────────────────────────────────────────────────────────────────────


class ListBucketsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorBucket(sdl.Entity):
    id: str = ""
    title: str = ""
    description: str = ""
    identifier: str = ""


class OrchestratorBucketList(sdl.Entity):
    id: str = "orchestrator_bucket_list"
    title: str = ""
    items: list[OrchestratorBucket] = Field(default_factory=list)


class ListBucketFilesParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    bucket_id: str = Field(..., description="Bucket id, from list_buckets.")
    prefix: str = Field("", description="Optional path prefix to filter files under.")


class BucketFile(sdl.Entity):
    id: str = ""
    title: str = ""
    full_path: str = ""
    content_type: str = ""
    size: int = 0


class BucketFileList(sdl.Entity):
    id: str = "bucket_file_list"
    title: str = ""
    items: list[BucketFile] = Field(default_factory=list)


class GetBucketFileReadUriParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    bucket_id: str = Field(..., description="Bucket id, from list_buckets.")
    path: str = Field(..., description="Full path of the file inside the bucket, from list_bucket_files.")
    expiry_minutes: int = Field(30, ge=1, le=1440, description="How many minutes the signed download URL stays valid.")


class BucketFileReadUri(sdl.Entity):
    id: str = ""
    title: str = "Bucket file download URL"
    url: str = ""
    expires_in_minutes: int = 30


# ──────────────────────────────────────────────────────────────────────────
# Webhooks
# ──────────────────────────────────────────────────────────────────────────


class ListWebhooksParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorWebhook(sdl.Entity):
    id: str = ""
    title: str = ""
    url: str = ""
    enabled: bool = False


class OrchestratorWebhookList(sdl.Entity):
    id: str = "orchestrator_webhook_list"
    title: str = ""
    items: list[OrchestratorWebhook] = Field(default_factory=list)


class CreateWebhookParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    url: str = Field(..., description="HTTPS endpoint Orchestrator will POST events to.")
    events: list[str] = Field(default_factory=list, description="Event types to subscribe to (e.g. 'job.completed', 'job.faulted'). Empty means subscribe to all events.")
    secret: str = Field("", description="Optional shared secret Orchestrator will sign payloads with.")


class DeleteWebhookParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")
    webhook_id: str = Field(..., description="Webhook id, from list_webhooks.")


# ──────────────────────────────────────────────────────────────────────────
# Users
# ──────────────────────────────────────────────────────────────────────────


class ListUsersParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")


class OrchestratorUser(sdl.Entity):
    id: str = ""
    title: str = ""
    username: str = ""
    email: str = ""
    is_active: bool = True


class OrchestratorUserList(sdl.Entity):
    id: str = "orchestrator_user_list"
    title: str = ""
    items: list[OrchestratorUser] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Audit Logs
# ──────────────────────────────────────────────────────────────────────────


class ListAuditLogsParams(BaseModel):
    connection_id: str = Field("", description="Which connected organization to use. Omit if only one is connected.")
    folder_id: str = Field("", description="Orchestrator Folder ID. Omit to use the connection's default folder.")


class OrchestratorAuditLogEntry(sdl.Entity):
    id: str = ""
    title: str = ""
    component: str = ""
    action: str = ""
    execution_time: str = ""
    user_name: str = ""


class OrchestratorAuditLogList(sdl.Entity):
    id: str = "orchestrator_audit_log_list"
    title: str = ""
    items: list[OrchestratorAuditLogEntry] = Field(default_factory=list)
