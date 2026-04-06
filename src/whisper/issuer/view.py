# -*- encoding: utf-8 -*-
"""
whisper.issuer.view module

RegistryDetailDialog — read-only view of a single KERI credential registry.

Follows the pattern established in
locksmith/ui/vault/credentials/schema/view.py.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPlainTextEdit,
)

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog
from locksmith.ui.toolkit.widgets.buttons import LocksmithButton, LocksmithCopyButton

logger = logging.getLogger(__name__)


class RegistryDetailDialog(LocksmithDialog):
    """
    Read-only dialog showing KERI registry details.

    Displays: Registry Name, Registry SAID (with copy), Identifier alias,
    Backer AID(s), and the raw vcp KED as formatted JSON.
    """

    def __init__(self, registry_data: dict[str, Any], parent=None):
        self._registry_data = registry_data

        content = self._build_content()
        buttons = self._build_buttons()

        super().__init__(
            parent=parent,
            title="Registry Details",
            title_icon=":/assets/material-icons/badge.svg",
            content=content,
            buttons=buttons,
        )

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _build_content(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        name = self._registry_data.get("name", "—")
        regk = self._registry_data.get("regk", "—")
        identifier = self._registry_data.get("identifier", "—")
        backers: list = self._registry_data.get("backers", [])
        vcp_ked: dict = self._registry_data.get("vcp_ked", {})

        # ---- SAID row ----
        said_row = QHBoxLayout()
        said_lbl = QLabel("Registry SAID:")
        said_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; min-width: 130px;"
        )
        said_val = QLabel(regk)
        said_val.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_MENU}; font-family: monospace;"
        )
        said_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy_btn = LocksmithCopyButton(text_to_copy=regk)
        said_row.addWidget(said_lbl)
        said_row.addWidget(said_val)
        said_row.addWidget(copy_btn)
        said_row.addStretch()
        layout.addLayout(said_row)

        # ---- Info frame ----
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {colors.BORDER}; border-radius: 8px; "
            f"background: white; }}"
        )
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(16, 12, 16, 12)
        frame_layout.setSpacing(8)

        for label, value in [
            ("Registry Name", name),
            ("Identifier", identifier),
            ("Backed By", ", ".join(backers) if backers else "None"),
            ("Backer Count", str(len(backers))),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(130)
            lbl.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
            val = QLabel(value)
            val.setWordWrap(True)
            val.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU};")
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            frame_layout.addLayout(row)

        layout.addWidget(frame)

        # ---- Raw vcp KED ----
        if vcp_ked:
            raw_lbl = QLabel("Registry Inception Event (vcp):")
            raw_lbl.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
            layout.addWidget(raw_lbl)

            vcp_json = json.dumps(vcp_ked, indent=2)

            raw_text = QPlainTextEdit()
            raw_text.setPlainText(vcp_json)
            raw_text.setReadOnly(True)
            raw_text.setFixedHeight(180)
            raw_text.setStyleSheet(
                "font-family: 'Menlo', 'SF Mono', 'Courier New', monospace; "
                "font-size: 11px;"
            )
            layout.addWidget(raw_text)

            copy_vcp_btn = LocksmithCopyButton(text_to_copy=vcp_json)
            copy_vcp_row = QHBoxLayout()
            copy_vcp_row.addStretch()
            copy_vcp_row.addWidget(copy_vcp_btn)
            layout.addLayout(copy_vcp_row)

        return widget

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        close_btn = LocksmithButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)
        return row