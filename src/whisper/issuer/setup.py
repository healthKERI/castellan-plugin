# -*- encoding: utf-8 -*-
"""
whisper.issuer.setup module

IssuerSetupPage — full-page guided flow for creating a KERI credential
registry backed by weirwood.

Follows the LocksmithFormPage pattern established in
locksmith/ui/vault/healthKERI/witnesses/create.py.
"""
from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets.buttons import (
    LocksmithButton, LocksmithInvertedButton,
)
from locksmith.ui.toolkit.widgets.fields import (
    FloatingLabelComboBox, FloatingLabelLineEdit,
)
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage

from .doers import create_registry

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = logging.getLogger(__name__)

_REGISTRY_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\-]{0,62}[a-zA-Z0-9]$|^[a-zA-Z0-9]$')


class IssuerSetupPage(LocksmithFormPage):
    """
    Full-page form for creating a KERI credential registry backed by weirwood.

    Sections (all visible, scrollable):
      1. Identifier — select an existing identifier (single-sig or group)
      2. Registry name — alphanumeric + hyphens
      3. Summary card — review before creating
      4. Action buttons — Initialize / Cancel
      5. Success panel — shown after completion (form sections hidden)
    """

    def __init__(self, app: "LocksmithApplication", parent: "VaultPage | None" = None):
        super().__init__(
            title="Initialization",
            icon_path=":/assets/material-icons/passport.svg",
            parent=parent,
        )
        self._parent = parent
        self.app = app
        self.vault_name = ""
        self._alias_by_display: dict[str, str] = {}   # display text → hab alias
        self._selected_alias: str = ""
        self._selected_aid: str = ""
        self._creating = False

        self._setup_content()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_content(self):
        layout = self.content_layout

        # ---- Description ----
        desc = QLabel(
            "Set up this vault as a credential issuer. You will create a credential "
            "registry anchored to one of your identifiers and backed by the weirwood "
            "registrar. Once complete you can upload schemas, issue credentials to "
            "other weirwood users, and revoke them when needed."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 15px; color: {colors.TEXT_SUBTLE};")
        layout.addWidget(desc)

        layout.addSpacing(50)

        # ----------------------------------------------------------------
        # Section 1 — Select Identifier
        # ----------------------------------------------------------------
        self._add_section_header(
            layout,
            header="Select an Identifier",
            sub="Choose the identifier that will act as the credential issuer. "
                "Each identifier can own at most one active registry.",
        )
        layout.addSpacing(10)

        id_row = QHBoxLayout()
        id_row.setSpacing(12)

        self._identifier_dropdown = FloatingLabelComboBox("Issuer Identifier")
        self._identifier_dropdown.setFixedWidth(500)
        self._identifier_dropdown.currentIndexChanged.connect(self._on_identifier_changed)
        id_row.addWidget(self._identifier_dropdown)

        self._group_id_button = LocksmithInvertedButton("Create Group Identifier")
        self._group_id_button.clicked.connect(self._on_create_group_identifier)
        id_row.addWidget(self._group_id_button)
        id_row.addStretch()
        layout.addLayout(id_row)

        # Truncated AID display
        self._aid_label = QLabel("")
        self._aid_label.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: monospace;"
        )
        layout.addWidget(self._aid_label)

        layout.addSpacing(40)

        # ----------------------------------------------------------------
        # Section 2 — Registry Name
        # ----------------------------------------------------------------
        self._add_section_header(
            layout,
            header="Name Your Registry",
            sub="A short, memorable name for this registry. "
                "Alphanumeric characters and hyphens only (max 64 chars).",
        )
        layout.addSpacing(10)

        self._name_field = FloatingLabelLineEdit("Registry Name")
        self._name_field.setFixedWidth(500)
        self._name_field.line_edit.textChanged.connect(self._update_summary)
        layout.addWidget(self._name_field)

        layout.addSpacing(40)

        # ----------------------------------------------------------------
        # Section 3 — Summary Card
        # ----------------------------------------------------------------
        self._add_section_header(
            layout,
            header="Review",
            sub="Confirm the details before creating your registry.",
        )
        layout.addSpacing(10)

        self._summary_frame = QFrame()
        self._summary_frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {colors.BORDER}; border-radius: 8px; "
            f"background: white; padding: 16px; }}"
        )
        summary_layout = QVBoxLayout(self._summary_frame)
        summary_layout.setSpacing(8)
        summary_layout.setContentsMargins(16, 16, 16, 16)

        self._summary_identifier = self._make_summary_row("Identifier", "—")
        self._summary_name = self._make_summary_row("Registry Name", "—")
        self._summary_backer = self._make_summary_row("Backed By", "Weirwood Registrar")

        for row in (self._summary_identifier, self._summary_name, self._summary_backer):
            summary_layout.addLayout(row)

        self._summary_frame.setFixedWidth(500)
        layout.addWidget(self._summary_frame)

        layout.addSpacing(40)

        # ----------------------------------------------------------------
        # Action buttons
        # ----------------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_button = LocksmithInvertedButton("Cancel")
        self._cancel_button.setFixedWidth(100)
        self._cancel_button.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_button)

        btn_row.addSpacing(10)

        self._initialize_button = LocksmithButton("Initialize")
        self._initialize_button.setFixedWidth(120)
        self._initialize_button.clicked.connect(self._on_initialize_clicked)
        btn_row.addWidget(self._initialize_button)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ----------------------------------------------------------------
        # Success panel (hidden until registry is created)
        # ----------------------------------------------------------------
        self._success_panel = QWidget()
        self._success_panel.hide()
        success_layout = QVBoxLayout(self._success_panel)
        success_layout.setContentsMargins(0, 30, 0, 0)
        success_layout.setSpacing(16)

        success_title = QLabel("Registry Created")
        success_title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {colors.TEXT_MENU};"
        )
        success_layout.addWidget(success_title)

        self._success_name_label = QLabel("")
        self._success_name_label.setStyleSheet(
            f"font-size: 14px; color: {colors.TEXT_SUBTLE};"
        )
        success_layout.addWidget(self._success_name_label)

        self._success_said_label = QLabel("")
        self._success_said_label.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: monospace;"
        )
        self._success_said_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        success_layout.addWidget(self._success_said_label)

        backer_note = QLabel("Weirwood is backing this registry.")
        backer_note.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
        success_layout.addWidget(backer_note)

        success_layout.addSpacing(16)

        success_btn_row = QHBoxLayout()
        success_btn_row.addStretch()

        self._add_schema_button = LocksmithInvertedButton("Add a Schema →")
        self._add_schema_button.clicked.connect(self._on_add_schema)
        success_btn_row.addWidget(self._add_schema_button)

        success_btn_row.addSpacing(10)

        self._done_button = LocksmithButton("Done")
        self._done_button.setFixedWidth(80)
        self._done_button.clicked.connect(self._on_done)
        success_btn_row.addWidget(self._done_button)

        success_btn_row.addStretch()
        success_layout.addLayout(success_btn_row)

        layout.addWidget(self._success_panel)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_section_header(self, layout: QVBoxLayout, header: str, sub: str):
        h = QLabel(header)
        h.setStyleSheet(f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};")
        layout.addWidget(h)
        layout.addSpacing(6)
        s = QLabel(sub)
        s.setWordWrap(True)
        s.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;")
        layout.addWidget(s)

    def _make_summary_row(self, label: str, value: str) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label + ":")
        lbl.setFixedWidth(140)
        lbl.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
        val = QLabel(value)
        val.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU};")
        val.setObjectName(f"summary_val_{label.lower().replace(' ', '_')}")
        row.addWidget(lbl)
        row.addWidget(val)
        row.addStretch()
        return row

    def _set_summary_value(self, row: QHBoxLayout, value: str):
        """Update the value label in a summary row."""
        for i in range(row.count()):
            item = row.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QLabel):
                if item.widget().styleSheet() and colors.TEXT_MENU in item.widget().styleSheet():
                    item.widget().setText(value)
                    break

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        """Called when the page becomes visible."""
        self._reset_form()
        self._load_identifiers()

    def _reset_form(self):
        self.clear_error()
        self.clear_success()
        self._identifier_dropdown.clear()
        self._name_field.setText("")
        self._aid_label.setText("")
        self._selected_alias = ""
        self._selected_aid = ""
        self._alias_by_display.clear()
        self._update_summary()
        self._success_panel.hide()
        self._initialize_button.setEnabled(True)
        self._initialize_button.setText("Initialize")
        self._creating = False

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_identifiers(self):
        """Populate the identifier dropdown from the local vault."""
        if not self.app or not self.app.vault:
            return

        hby = self.app.vault.hby
        rgy = self.app.vault.rgy

        self._alias_by_display.clear()
        self._identifier_dropdown.clear()

        for alias, hab in hby.habs.items():
            # Skip identifiers that already own a registry
            if rgy.registryByName(alias) is not None:
                continue
            display = alias
            self._alias_by_display[display] = alias

        self._identifier_dropdown.addItems(sorted(self._alias_by_display.keys()))
        self._identifier_dropdown.setCurrentIndex(-1)

    def _on_identifier_changed(self, index: int):
        if index < 0:
            self._selected_alias = ""
            self._selected_aid = ""
            self._aid_label.setText("")
            self._update_summary()
            return

        display = self._identifier_dropdown.currentText()
        alias = self._alias_by_display.get(display, "")
        self._selected_alias = alias

        if alias and self.app and self.app.vault:
            hab = self.app.vault.hby.habs.get(alias)
            if hab:
                self._selected_aid = hab.pre
                truncated = hab.pre[:24] + "…" + hab.pre[-8:]
                self._aid_label.setText(truncated)
            else:
                self._selected_aid = ""
                self._aid_label.setText("")

        self._update_summary()

    def _update_summary(self):
        alias = self._selected_alias or "—"
        name = self._name_field.text().strip() or "—"

        self._set_summary_value(self._summary_identifier, alias)
        self._set_summary_value(self._summary_name, name)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_create_group_identifier(self):
        """Navigate to locksmith's group identifier creation page."""
        vault_page = getattr(self.app, "_vault_page", None)
        if vault_page and hasattr(vault_page, "_show_page"):
            vault_page._show_page("group_identifier_create")
        else:
            self.show_error(
                "To create a group identifier, navigate to Identifiers → "
                "New Identifier and choose the 'Group' type."
            )

    def _on_cancel(self):
        vault_page = getattr(self.app, "_vault_page", None)
        if vault_page and hasattr(vault_page, "_show_page"):
            vault_page._show_page("whisper_registries")

    def _on_done(self):
        vault_page = getattr(self.app, "_vault_page", None)
        if vault_page and hasattr(vault_page, "_show_page"):
            vault_page._show_page("whisper_registries")

    def _on_add_schema(self):
        """Open locksmith's AddSchemaDialog so the user can progress to Step 3."""
        try:
            from locksmith.ui.vault.credentials.schema.add import AddSchemaDialog
            dialog = AddSchemaDialog(app=self.app, parent=self._parent)
            dialog.open()
        except Exception as e:
            logger.error(f"Could not open AddSchemaDialog: {e}")
            self.show_error("Could not open schema dialog. Please add schemas via the Schema section.")

    @qasync.asyncSlot()
    async def _on_initialize_clicked(self):
        """Validate inputs and create the registry."""
        if self._creating:
            return

        error = self._validate()
        if error:
            self.show_error(error)
            return

        self.clear_error()
        self._creating = True
        self._initialize_button.setEnabled(False)
        self._initialize_button.setText("Initializing…")

        whisper_cfg = self.app.config.plugin_configs.get("whisper", {})
        weirwood_aid = whisper_cfg.get("weirwood_aid", "")

        registry_name = self._name_field.text().strip()

        try:
            result = await create_registry(
                app=self.app,
                hab_alias=self._selected_alias,
                registry_name=registry_name,
                weirwood_aid=weirwood_aid,
            )
            self._show_success_panel(result)
        except Exception as e:
            logger.exception(f"Registry creation failed: {e}")
            self.show_error(str(e))
            self._initialize_button.setEnabled(True)
            self._initialize_button.setText("Initialize")
        finally:
            self._creating = False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> str | None:
        """Return an error message string, or None if valid."""
        if not self._selected_alias:
            return "Please select an identifier."

        name = self._name_field.text().strip()
        if not name:
            return "Please enter a registry name."
        if not _REGISTRY_NAME_RE.match(name):
            return (
                "Registry name must be 1–64 alphanumeric characters or hyphens, "
                "and cannot start or end with a hyphen."
            )

        whisper_cfg = self.app.config.plugin_configs.get("whisper", {})
        if not whisper_cfg.get("weirwood_aid"):
            return "Weirwood AID is not configured. Check your plugin configuration."

        return None

    # ------------------------------------------------------------------
    # Success
    # ------------------------------------------------------------------

    def _show_success_panel(self, result: dict):
        """Hide the form and show the success panel."""
        self.show_success(f"Registry '{result['name']}' created successfully.")
        self._success_name_label.setText(f"Registry: {result['name']}")
        self._success_said_label.setText(f"SAID: {result['regk']}")
        self._success_panel.show()
        self._initialize_button.hide()
        self._cancel_button.hide()