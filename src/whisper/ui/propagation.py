# -*- encoding: utf-8 -*-
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QButtonGroup

from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton


class PropagationMode:
    WEIRWOOD_ONLY = "weirwood"
    MAILBOX_ONLY = "mailbox"
    WEIRWOOD_AND_MAILBOX = "both"


class PropagationModeWidget(QWidget):
    """Radio-button group for selecting multisig EXN propagation transport."""

    def __init__(self, include_mailbox_only: bool = True, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel("Propagation Mode")
        lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(lbl)

        self._group = QButtonGroup(self)

        self._weirwood_btn = LocksmithRadioButton("Weirwood only")
        self._weirwood_btn.setChecked(True)
        layout.addWidget(self._weirwood_btn)
        self._group.addButton(self._weirwood_btn)

        self._both_btn = LocksmithRadioButton("Weirwood + Mailbox")
        layout.addWidget(self._both_btn)
        self._group.addButton(self._both_btn)

        if include_mailbox_only:
            self._mailbox_btn = LocksmithRadioButton("Mailbox only")
            layout.addWidget(self._mailbox_btn)
            self._group.addButton(self._mailbox_btn)
        else:
            self._mailbox_btn = None

    def current_mode(self) -> str:
        if self._mailbox_btn and self._mailbox_btn.isChecked():
            return PropagationMode.MAILBOX_ONLY
        if self._both_btn.isChecked():
            return PropagationMode.WEIRWOOD_AND_MAILBOX
        return PropagationMode.WEIRWOOD_ONLY