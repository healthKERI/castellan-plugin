# -*- encoding: utf-8 -*-
"""
whisper.issuer.list module

RegistryListPage — shows all local KERI credential registries owned by this vault.

Data is read directly from vault.rgy (LMDB) — no remote call needed.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout

from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget

from .view import RegistryDetailDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = logging.getLogger(__name__)


class RegistryListPage(QWidget):
    """Paginated list of local KERI credential registries."""

    def __init__(self, app, parent: "VaultPage | None" = None):
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.vault_name = ""
        self._registry_cache: dict[str, dict[str, Any]] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.table = PaginatedTableWidget(
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
            show_add_button=True,
            add_button_text="New Registry",
            row_actions=["View"],
            row_action_icons={"View": ":/assets/material-icons/view.svg"},
            items_per_page=10,
            show_search=False,
            transform_func=self._transform_registry_to_row,
            parent=self,
        )

        self.table.add_clicked.connect(self._on_new_registry)
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)

        layout.addWidget(self.table)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _build_registry_rows(self) -> list[dict[str, Any]]:
        """Read registries from vault.rgy and build row dicts."""
        if not self.app or not self.app.vault:
            return []

        rgy = self.app.vault.rgy
        rows = []

        for reg_name, registry in rgy.regs.items():
            try:
                hab = getattr(registry, "hab", None)
                identifier = hab.name if hab else "—"
                regk = getattr(registry, "regk", "—")

                # Derive backer info from vcp KED
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

    def _transform_registry_to_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return row

    # ------------------------------------------------------------------
    # PaginatedTableWidget integration
    # ------------------------------------------------------------------

    def _on_load_requested(self, params: dict):
        """Load local registry data and feed into the table."""
        self._registry_cache.clear()
        rows = self._build_registry_rows()

        # PaginatedTableWidget expects a response dict with a data_key list
        page = params.get("page", 0)
        page_size = params.get("page_size", 20)
        total = len(rows)

        import math
        num_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
        start = page * page_size
        page_rows = rows[start: start + page_size]

        self.table.set_page_data(
            {
                "registries": page_rows,
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

    def _on_new_registry(self):
        vault_page = getattr(self.app, "_vault_page", None)
        if vault_page and hasattr(vault_page, "_show_page"):
            vault_page._show_page("whisper_issuer_setup")

    def _on_row_clicked(self, row_data: Any):
        if isinstance(row_data, dict):
            self._view_registry(row_data.get("_regk", ""))

    def _on_row_action_signal(self, row_data: object, action: str):
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

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        self._registry_cache.clear()
        self.table.request_load()