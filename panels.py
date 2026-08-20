"""Panel UI -- connections list/connect form + Orchestrator processes list.

SIDEBAR CONTENT -- NO CARDS ANYWHERE, per ~/UI_INTERFACE_STANDARD.md's
"left sidebar, no decorated cards" rule (same convention as MuleSoft
Connector's / Power Automate Connector's / n8n Connector's panels.py).

Every section (connections, connect form, processes) is a plain ui.Stack,
content stacked vertically and left-aligned, sections separated by
ui.Divider() -- no Card border/background/shadow anywhere in this slot.
Disconnect lives only in the "App settings" screen (panels_settings.py).
The one secondary "App settings" button is always the LAST element at the
bottom of the sidebar.

WHY A FULL FORM, NOT A TOKEN LIKE n8n/Make.com/Slack.

UiPath's External Application auth needs client_id + client_secret +
organization_name + tenant_name + default_folder_id -- see app.py's module
docstring for the full reasoning (External Applications overview,
Folder-scoped Orchestrator resources). The form therefore asks for all
five required fields plus an optional label, with a help panel (opened via
ui.Call("__panel__uipath_connect_help")) explaining where to find each one
-- the same shape as MuleSoft Connector's 5-field form. No intro heading/
description text lives in the sidebar itself -- that walkthrough lives
ONLY in the help panel's content, per UI_INTERFACE_STANDARD.md's "no
sidebar instructions duplicating the modal" rule.

CENTER SLOT -- per ~/UI_INTERFACE_STANDARD.md, an app with no dedicated
center content needs a base (non-overlay) center panel with the canonical
"Nothing to show here" text, registered with center_overlay=True so the
session-init batch actually picks it up (same lesson learned and recorded
for MuleSoft/Make.com/n8n/Power Automate Connector).
"""
from __future__ import annotations

from imperal_sdk import ui

import uipath_client as uc
from app import ext
import handlers as h


def _settings_button() -> ui.UINode:
    """The one required secondary entry point into the settings screen --
    always the last element at the bottom of the sidebar."""
    return ui.Button(
        "App settings", variant="secondary", size="sm", full_width=True,
        icon="settings", on_click=ui.Call("__panel__uipath_settings"),
    )


def _connection_row(c: dict) -> ui.UINode:
    label = c.get("label") or c.get("detail", "")
    return ui.Stack(direction="v", gap=1, children=[
        ui.Text(label, variant="body"),
        ui.Text(c.get("detail", ""), variant="caption"),
    ])


def _connections_section(connections: list[dict]) -> ui.UINode:
    if not connections:
        return ui.Text("No organizations connected yet.", variant="caption")
    children: list[ui.UINode] = []
    for i, c in enumerate(connections):
        if i > 0:
            children.append(ui.Divider())
        children.append(_connection_row(c))
    return ui.Stack(direction="v", gap=2, children=children)


def _process_row(p) -> ui.UINode:
    """One Orchestrator process row -- plain content, no Card wrapper, no
    padding/border, per Vlad's standing sidebar rule."""
    return ui.Stack(direction="v", gap=1, children=[
        ui.Text(p.title, variant="body"),
        ui.Text(p.process_key or p.version, variant="caption"),
    ])


def _processes_section(processes: list) -> ui.UINode:
    if not processes:
        return ui.Text("No processes yet.", variant="caption")
    children: list[ui.UINode] = []
    for i, p in enumerate(processes[:20]):
        if i > 0:
            children.append(ui.Divider())
        children.append(_process_row(p))
    return ui.Stack(direction="v", gap=2, children=children)


def _connect_section() -> ui.UINode:
    """Plain content, no Card wrapper. Stretched full-width per
    UI_INTERFACE_STANDARD.md (2026-08-20). No intro heading/description
    text here -- the External Application walkthrough lives ONLY in
    uipath_connect_help's panel (button below opens it); repeating it here
    would duplicate that instruction."""
    return ui.Stack(direction="v", gap=3, align="stretch", children=[
        ui.Button("How do I set this up?", variant="ghost", size="sm",
                  icon="HelpCircle",
                  on_click=ui.Call("__panel__uipath_connect_help")),
        ui.Form(
            action="connect_uipath",
            submit_label="Verify and connect",
            children=[
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("External Application client ID", variant="caption"),
                    ui.Input(param_name="client_id", placeholder="External Application client ID"),
                ]),
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("External Application client secret", variant="caption"),
                    ui.Password(param_name="client_secret",
                                 placeholder="External Application client secret"),
                ]),
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Organization name", variant="caption"),
                    ui.Input(param_name="organization_name", placeholder="e.g. acme-robotics"),
                ]),
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Tenant name", variant="caption"),
                    ui.Input(param_name="tenant_name", placeholder="e.g. DefaultTenant"),
                ]),
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Default Folder ID", variant="caption"),
                    ui.Input(param_name="default_folder_id", placeholder="e.g. 148213"),
                ]),
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Label (optional)", variant="caption"),
                    ui.Input(param_name="label", placeholder="e.g. Production RPA"),
                ]),
            ],
        ),
    ])


@ext.panel("uipath_connect", slot="left", title="UiPath", icon="🤖",
           default_width=320, min_width=260, max_width=420)
async def uipath_connect_panel(ctx, **kwargs) -> object:
    connections = await h._load_connections(ctx)
    connected = bool(connections)

    header = ui.Header(text="UiPath", level=2,
                        subtitle="Manage your Orchestrator processes, jobs and queues from Imperal")

    if not connected:
        return ui.Stack(direction="v", gap=4, align="stretch", children=[
            header,
            _connect_section(),
            ui.Divider(),
            _settings_button(),
        ])

    processes: list = []
    first = connections[0]
    try:
        tok = await uc.get_access_token(ctx, first["client_id"], first["client_secret"])
        if tok.get("ok"):
            raw = await uc.list_processes(ctx, tok["access_token"], first["organization_name"], first["tenant_name"], first.get("default_folder_id", ""))
            from schemas import OrchestratorProcess
            processes = [
                OrchestratorProcess(
                    id=str(p.get("Id", "")), title=p.get("Name", ""),
                    key=p.get("Key", ""), version=p.get("ProcessVersion", ""),
                    process_key=p.get("ProcessKey", ""), description=p.get("Description", "") or "",
                )
                for p in raw
            ]
    except uc.ClientFail:
        processes = []

    return ui.Stack(direction="v", gap=4, align="stretch", children=[
        header,
        ui.Text("Connected organizations", variant="subtitle"),
        _connections_section(connections),
        ui.Divider(),
        _connect_section(),
        ui.Divider(),
        ui.Text(f"Processes -- {first.get('label') or first.get('organization_name', '')}", variant="subtitle"),
        _processes_section(processes),
        ui.Divider(),
        _settings_button(),
    ])


@ext.panel("uipath_connect_help", slot="center",
           title="How to connect UiPath", center_overlay=True)
async def uipath_connect_help(ctx, **kwargs) -> object:
    content = ui.Stack(direction="v", gap=3, children=[
        ui.Text("1. In UiPath Automation Cloud, open Admin > External Applications > Add Application."),
        ui.Text("2. Choose \"Confidential Application\" (machine-to-machine, no user login involved)."),
        ui.Text("3. Grant the OR.* scopes you want to use (e.g. OR.Jobs, OR.Queues, OR.Robots, OR.Assets, OR.Folders)."),
        ui.Text("4. Copy the Application ID (client ID) and App Secret (client secret) from the application's details page."),
        ui.Text("5. Your organization name and tenant name come from your Automation Cloud URL: cloud.uipath.com/<organization_name>/<tenant_name>."),
        ui.Text("6. The default Folder ID is found in Orchestrator > Folders -- open a folder and check its settings or the URL for its numeric id. Almost every Orchestrator call is scoped to one Folder."),
        ui.Divider(),
        ui.Alert(
            title="Orchestrator resources only",
            message=(
                "This manages Orchestrator processes, jobs, queues, robots, "
                "and assets. Studio automation design and Insights analytics "
                "are out of scope here."
            ),
            type="warning",
        ),
        ui.Divider(),
        ui.Link(
            label="Open UiPath's official External Applications guide",
            href="https://docs.uipath.com/automation-cloud/automation-cloud/latest/api-guide/accessing-uipath-resources-using-external-applications",
        ),
    ])
    return ui.Dialog(
        title="How to connect UiPath",
        content=content,
        confirm_label="",
        cancel_label="Close",
    )


@ext.panel("uipath_center", slot="center", title="UiPath", icon="🤖", center_overlay=True)
async def uipath_center_panel(ctx, **kwargs) -> object:
    """Base center panel -- per UI_INTERFACE_STANDARD.md (2026-08-20).
    This app has no list/detail content of its own to show in the center
    by default (everything lives in the sidebar). MUST carry
    center_overlay=True: per docs.imperal.io/en/concepts/panels, a plain
    slot="center" panel is registered but the Panel app never fetches it
    at session-init without that flag. Text is the shared canonical
    wording -- must stay identical across every app in this situation."""
    return ui.Empty(
        message="Nothing to show here -- this app is managed entirely from the sidebar.",
        icon="👈",
    )
