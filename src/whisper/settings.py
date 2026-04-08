# -*- encoding: utf-8 -*-
"""
whisper.settings module

WhisperSettingsPage — LocksmithFormPage hosting the registry list and a
placeholder for the default issuing identifier setting.

Registry list logic is adapted from issuer/list.py.  The old RegistryListPage
(whisper_registries) is replaced by this page (whisper_settings).
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout

from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox

from .issuer.view import RegistryDetailDialog

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = logging.getLogger(__name__)


class WhisperSettingsPage(LocksmithFormPage):
    """
    Settings page for the whisper plugin.

    Section 1: Registry list (read from vault.rgy).
    Section 2: Default Issuing Identifier placeholder (wired in future issuance spike).
    """

    def __init__(self, app: "LocksmithApplication", parent: "VaultPage | None" = None):
        super().__init__(
            title="Whisper Settings",
            icon_path=":/assets/material-icons/settings.svg",
            parent=parent,
        )
        self.app = app
        self._registry_cache: dict[str, dict[str, Any]] = {}
        self._build_content()

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _build_content(self):
        self._build_registry_section()
        self._build_default_identifier_section()

    def _build_registry_section(self):
        self.registry_table = PaginatedTableWidget(
            columns=["Registry Name", "Identifier", "Registry SAID", "Backed By"],
            column_widths={
                "Registry Name": 200,
                "Identifier": 160,
                "Registry SAID": 320,
                "Backed By": 160,
                "Actions": 50,
            },
            title="Registries",
            icon_path=":/assets/material-icons/badge.svg",
            show_add_button=False,
            row_actions=["View"],
            row_action_icons={"View": ":/assets/material-icons/view.svg"},
            items_per_page=10,
            show_search=False,
            transform_func=lambda row: row,
            parent=self,
        )
        self.registry_table.row_action_triggered.connect(self._on_row_action)
        self.registry_table.row_clicked.connect(self._on_row_clicked)
        self.registry_table.load_requested.connect(self._on_load_requested)
        self.registry_table.load_error.connect(self._on_load_error)
        self.content_layout.addWidget(self.registry_table)

    def _build_default_identifier_section(self):
        """Placeholder section for default issuing identifier (future spike)."""
        self.content_layout.addSpacing(24)

        header = QLabel("Default Issuing Identifier")
        header.setStyleSheet("font-weight: 600; font-size: 16px;")
        self.content_layout.addWidget(header)

        hint = QLabel("Select which group identifier is used by default when issuing credentials.")
        hint.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
        hint.setWordWrap(True)
        self.content_layout.addWidget(hint)

        self._default_id_dropdown = FloatingLabelComboBox("Default Identifier")
        self._default_id_dropdown.setFixedWidth(420)
        self._default_id_dropdown.setEnabled(False)  # placeholder — wired in future spike
        self.content_layout.addWidget(self._default_id_dropdown)

        self.content_layout.addStretch()

    # ------------------------------------------------------------------
    # Registry data
    # ------------------------------------------------------------------

    def _build_registry_rows(self) -> list[dict[str, Any]]:
        if not self.app or not self.app.vault:
            return []
        rgy = self.app.vault.rgy
        rows = []
        for reg_name, registry in rgy.regs.items():
            try:
                hab = getattr(registry, "hab", None)
                identifier = hab.name if hab else "—"
                regk = getattr(registry, "regk", "—")
                backers = []
                try:
                    baks = registry.vcp.ked.get("b", [])
                    backers = baks if isinstance(baks, list) else []
                except Exception:
                    pass
                backed_by = "Weirwood" if backers else "None"
                row = {
                    "Registry Name": reg_name,
                    "Identifier": identifier,
                    "Registry SAID": regk,
                    "Backed By": backed_by,
                    "_regk": regk,
                    "_reg_name": reg_name,
                }
                self._registry_cache[regk] = {
                    "name": reg_name,
                    "identifier": identifier,
                    "regk": regk,
                    "backers": backers,
                    "vcp_ked": registry.vcp.ked if hasattr(registry, "vcp") else {},
                }
                rows.append(row)
            except Exception as e:
                logger.warning(f"Error reading registry '{reg_name}': {e}")
        return rows

    # ------------------------------------------------------------------
    # PaginatedTableWidget integration
    # ------------------------------------------------------------------

    def _on_load_requested(self, params: dict):
        self._registry_cache.clear()
        rows = self._build_registry_rows()
        page = params.get("page", 0)
        page_size = params.get("page_size", 10)
        total = len(rows)
        num_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
        start = page * page_size
        self.registry_table.set_page_data(
            {
                "registries": rows[start: start + page_size],
                "count": total,
                "page": page,
                "num_pages": num_pages,
            },
            data_key="registries",
        )

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Registry table load error: {error_msg}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_row_clicked(self, row_data: Any):
        if isinstance(row_data, dict):
            self._view_registry(row_data.get("_regk", ""))

    def _on_row_action(self, row_data: object, action: str):
        if isinstance(row_data, dict) and action == "View":
            self._view_registry(row_data.get("_regk", ""))

    def _view_registry(self, regk: str):
        data = self._registry_cache.get(regk)
        if not data:
            logger.warning(f"Registry {regk} not in cache")
            return
        dialog = RegistryDetailDialog(registry_data=data, parent=self)
        dialog.show()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_show(self):
        self._registry_cache.clear()
        self.registry_table.request_load()
