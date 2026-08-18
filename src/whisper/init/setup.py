# -*- encoding: utf-8 -*-
"""
whisper.init.setup module

WhisperSetupPage — single LocksmithFormPage with four progressive sections
that reveal themselves as each step completes (mirrors WitnessCreatePage pattern).

Sections:
  1. Choose and Upload Identifier   — always visible
  2. Wait for Peers                 — hidden until section 1 complete
  3. Create Group Identifier        — hidden until section 2 continue
  4. Initialization Progress        — hidden until section 3 complete
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets.buttons import (
    LocksmithButton,
)
from locksmith.ui.toolkit.widgets.fields import (
    FloatingLabelComboBox, FloatingLabelLineEdit, LocksmithLineEdit,
)
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.toolkit.widgets.extensible import ExtensibleSelectorWidget
from locksmith.ui.styles import get_monospace_font_family

from ..core import remoting
from ..db.basing import WhisperInitState
from .doers import WhisperGroupMultisigInceptDoer, CreateRegistryDoer
from .poller import UploadedIdentifierPoller
from ..ui.propagation import PropagationMode, PropagationModeWidget

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

from keri import help
from keri.vdr import credentialing as vdr_credentialing

logger = help.ogler.getLogger(__name__)


class WhisperSetupPage(LocksmithFormPage):
    """
    Single-page multi-step initialization wizard for whisper.

    All four steps are sections within this one page.  Sections are QWidget
    containers that start hidden and are revealed (with scroll) as each step
    completes.  `on_show()` resumes from the persisted init_step so users
    returning mid-setup land at the correct section.
    """

    def __init__(self, app: "LocksmithApplication", parent: "VaultPage | None" = None):
        super().__init__(
            title="Initialization",
            icon_path=":/assets/material-icons/passport.svg",
            parent=parent,
        )
        self._parent = parent
        self.app = app
        self._poller: UploadedIdentifierPoller | None = None
        self._weirwood_identifiers: list[dict] = []

        self._setup_content()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_content(self):
        layout = self.content_layout

        desc = QLabel(
            "Set up your whisper instance. You will upload your identifier to the "
            "shared weirwood server, wait for peers to join, create a group multisig "
            "identifier with those peers, and create a credential registry backed by weirwood."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 15px; color: {colors.TEXT_SUBTLE};")
        layout.addWidget(desc)
        layout.addSpacing(40)

        # Section 1
        self._build_section1(layout)

        # Section 2 (hidden initially)
        self._section2 = QWidget()
        self._section2.hide()
        s2_layout = QVBoxLayout(self._section2)
        s2_layout.setContentsMargins(0, 0, 0, 0)
        s2_layout.setSpacing(0)
        self._build_section2(s2_layout)
        layout.addWidget(self._section2)

        # Section 3 (hidden initially)
        self._section3 = QWidget()
        self._section3.hide()
        s3_layout = QVBoxLayout(self._section3)
        s3_layout.setContentsMargins(0, 0, 0, 0)
        s3_layout.setSpacing(0)
        self._build_section3(s3_layout)
        layout.addWidget(self._section3)

        # Section 4 (hidden initially)
        self._section4 = QWidget()
        self._section4.hide()
        s4_layout = QVBoxLayout(self._section4)
        s4_layout.setContentsMargins(0, 0, 0, 0)
        s4_layout.setSpacing(0)
        self._build_section4(s4_layout)
        layout.addWidget(self._section4)

        layout.addStretch()

    # -- Section 1: Choose and Upload Identifier -------------------------

    def _build_section1(self, layout: QVBoxLayout):
        # Store header labels as instance vars so we can update them after upload.
        self._s1_header_lbl = QLabel("Choose Your Identifier")
        self._s1_header_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};"
        )
        layout.addWidget(self._s1_header_lbl)
        layout.addSpacing(6)
        self._s1_subtext_lbl = QLabel(
            "Select the single (non-group) identifier that will represent you "
            "in the weirwood network. This identifier will be uploaded to weirwood "
            "so peers can discover you."
        )
        self._s1_subtext_lbl.setWordWrap(True)
        self._s1_subtext_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;"
        )
        layout.addWidget(self._s1_subtext_lbl)
        layout.addSpacing(6)

        _s1_body = QWidget()
        _s1_body_layout = QVBoxLayout(_s1_body)
        _s1_body_layout.setContentsMargins(10, 0, 0, 0)
        _s1_body_layout.setSpacing(0)

        _s1_body_layout.addSpacing(20)

        # Pre-upload: dropdown + button (hidden once upload succeeds).
        self._s1_input = QWidget()
        s1_in = QHBoxLayout(self._s1_input)
        s1_in.setContentsMargins(0, 0, 0, 0)
        self._id_dropdown = FloatingLabelComboBox("Your Identifier")
        self._id_dropdown.setFixedWidth(380)
        self._id_dropdown.currentIndexChanged.connect(self._on_identifier_changed)
        s1_in.addWidget(self._id_dropdown)
        s1_in.addSpacing(12)
        self._upload_button = LocksmithButton("Upload to Weirwood")
        self._upload_button.setFixedWidth(200)
        self._upload_button.clicked.connect(self._on_upload_clicked)
        s1_in.addWidget(self._upload_button)
        s1_in.addStretch()
        _s1_body_layout.addWidget(self._s1_input)

        self._id_aid_label = QLabel("")
        self._id_aid_label.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        _s1_body_layout.addWidget(self._id_aid_label)

        # Post-upload: chosen identifier summary (hidden until upload succeeds).
        self._s1_chosen = QWidget()
        s1_ch = QVBoxLayout(self._s1_chosen)
        s1_ch.setContentsMargins(0, 0, 0, 0)
        s1_ch.setSpacing(4)
        self._s1_chosen_name_lbl = QLabel("—")
        self._s1_chosen_name_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        s1_ch.addWidget(self._s1_chosen_name_lbl)
        self._s1_chosen_aid_lbl = QLabel("—")
        self._s1_chosen_aid_lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        s1_ch.addWidget(self._s1_chosen_aid_lbl)
        self._s1_chosen.hide()
        _s1_body_layout.addWidget(self._s1_chosen)

        layout.addWidget(_s1_body)
        layout.addSpacing(40)

    # -- Section 2: Wait for Peers --------------------------------------

    def _build_section2(self, layout: QVBoxLayout):
        self._s2_header_lbl = QLabel("Waiting for Peers")
        self._s2_header_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};"
        )
        layout.addWidget(self._s2_header_lbl)
        layout.addSpacing(6)
        self._s2_subtext_lbl = QLabel(
            "Your identifier has been uploaded. Waiting for at least one peer to "
            "join before group identifier creation can begin."
        )
        self._s2_subtext_lbl.setWordWrap(True)
        self._s2_subtext_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;"
        )
        layout.addWidget(self._s2_subtext_lbl)
        layout.addSpacing(6)

        _s2_body = QWidget()
        _s2_body_layout = QVBoxLayout(_s2_body)
        _s2_body_layout.setContentsMargins(10, 0, 0, 0)
        _s2_body_layout.setSpacing(0)

        _s2_body_layout.addSpacing(12)

        self._peer_count_label = QLabel("0 peer(s) have joined weirwood")
        self._peer_count_label.setStyleSheet(
            f"font-size: 14px; color: {colors.TEXT_SUBTLE};"
        )
        _s2_body_layout.addWidget(self._peer_count_label)

        layout.addWidget(_s2_body)
        layout.addSpacing(40)

    # -- Section 3: Create Group Identifier -----------------------------

    def _build_section3(self, layout: QVBoxLayout):
        self._s3_header_lbl = QLabel("Create Group Identifier or Wait to Join a Group")
        self._s3_header_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};"
        )
        layout.addWidget(self._s3_header_lbl)
        layout.addSpacing(6)
        self._s3_subtext_lbl = QLabel(
            "Select peers to include in your group multisig identifier and create it, "
            "or wait here — if a peer invites you to join their group you will receive "
            "a notification to accept.",
        )
        self._s3_subtext_lbl.setWordWrap(True)
        self._s3_subtext_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;"
        )
        layout.addWidget(self._s3_subtext_lbl)
        layout.addSpacing(6)

        _s3_body = QWidget()
        _s3_body_layout = QVBoxLayout(_s3_body)
        _s3_body_layout.setContentsMargins(10, 0, 0, 0)
        _s3_body_layout.setSpacing(0)

        _s3_body_layout.addSpacing(12)

        self._group_alias_field = FloatingLabelLineEdit("Group Identifier Alias")
        self._group_alias_field.setFixedWidth(500)
        _s3_body_layout.addWidget(self._group_alias_field)
        _s3_body_layout.addSpacing(16)

        participants_lbl = QLabel("Group Participants")
        participants_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        _s3_body_layout.addWidget(participants_lbl)

        self._participants_container = QWidget()
        self._participants_container_layout = QVBoxLayout(self._participants_container)
        self._participants_container_layout.setContentsMargins(0, 0, 0, 0)
        self._participants_selector: ExtensibleSelectorWidget | None = None
        _s3_body_layout.addWidget(self._participants_container)
        _s3_body_layout.addSpacing(4)

        # Frozen participant list (replaces selector when section 3 is locked)
        self._s3_frozen_participants_widget = QWidget()
        self._s3_frozen_participants_widget.hide()
        self._s3_frozen_participants_layout = QVBoxLayout(self._s3_frozen_participants_widget)
        self._s3_frozen_participants_layout.setContentsMargins(0, 0, 0, 0)
        self._s3_frozen_participants_layout.setSpacing(0)
        _s3_body_layout.addWidget(self._s3_frozen_participants_widget)

        _s3_body_layout.addSpacing(8)

        # Self-identity labels — always visible once section 3 is revealed
        self._s3_self_widget = QWidget()
        s3_self_vbox = QVBoxLayout(self._s3_self_widget)
        s3_self_vbox.setContentsMargins(8, 0, 0, 0)
        s3_self_vbox.setSpacing(4)
        self._s3_self_name_lbl = QLabel("—")
        self._s3_self_name_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        s3_self_vbox.addWidget(self._s3_self_name_lbl)
        self._s3_self_aid_lbl = QLabel("—")
        self._s3_self_aid_lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        s3_self_vbox.addWidget(self._s3_self_aid_lbl)
        _s3_body_layout.addWidget(self._s3_self_widget)
        _s3_body_layout.addSpacing(16)

        thresholds_lbl = QLabel("Thresholds")
        thresholds_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        _s3_body_layout.addWidget(thresholds_lbl)

        thresh_row = QHBoxLayout()
        self._signing_threshold = FloatingLabelLineEdit("Signing Threshold")
        self._signing_threshold.setText("1")
        self._signing_threshold.setFixedWidth(240)
        thresh_row.addWidget(self._signing_threshold)
        thresh_row.addSpacing(8)
        self._rotation_threshold = FloatingLabelLineEdit("Rotation Threshold")
        self._rotation_threshold.setText("1")
        self._rotation_threshold.setFixedWidth(240)
        thresh_row.addWidget(self._rotation_threshold)
        thresh_row.addStretch()
        _s3_body_layout.addLayout(thresh_row)
        _s3_body_layout.addSpacing(8)

        # TODO: Implement delegation, we will also need to lock delegation selection on section progression
        delegator_lbl = QLabel("Delegator")
        delegator_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        _s3_body_layout.addWidget(delegator_lbl)

        self._delegator_container = QWidget()
        self._delegator_container_layout = QVBoxLayout(self._delegator_container)
        self._delegator_container_layout.setContentsMargins(0, 0, 0, 0)
        self._delegator_selector: ExtensibleSelectorWidget | None = None
        _s3_body_layout.addWidget(self._delegator_container)
        _s3_body_layout.addSpacing(4)

        self._s3_propagation_widget = PropagationModeWidget(include_mailbox_only=False)
        _s3_body_layout.addWidget(self._s3_propagation_widget)
        _s3_body_layout.addSpacing(12)

        toad_row = QHBoxLayout()
        toad_lbl = QLabel("Threshold of Acceptable Duplicity: ")
        toad_lbl.setStyleSheet("font-size: 14px;")
        toad_row.addWidget(toad_lbl)
        self._toad_field = LocksmithLineEdit()
        self._toad_field.setText("0")
        self._toad_field.setFixedWidth(50)
        self._toad_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toad_row.addWidget(self._toad_field)
        toad_row.addStretch()
        _s3_body_layout.addLayout(toad_row)
        _s3_body_layout.addSpacing(20)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._create_group_button = LocksmithButton("Create Group Identifier")
        self._create_group_button.setFixedWidth(220)
        self._create_group_button.clicked.connect(self._on_create_group_clicked)
        btn_row.addWidget(self._create_group_button)
        btn_row.addStretch()
        _s3_body_layout.addLayout(btn_row)

        layout.addWidget(_s3_body)
        layout.addSpacing(40)

    # -- Section 4: Progress --------------------------------------------
    def _build_section4(self, layout: QVBoxLayout):
        self._s4_header_lbl = QLabel("Initializing…")
        self._s4_header_lbl.setStyleSheet(f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};")
        layout.addWidget(self._s4_header_lbl)
        layout.addSpacing(6)
        self._s4_subtext_lbl = QLabel("Coordinating signatures across participants.")
        self._s4_subtext_lbl.setWordWrap(True)
        self._s4_subtext_lbl.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;")
        layout.addWidget(self._s4_subtext_lbl)
        layout.addSpacing(6)

        _s4_body = QWidget()
        _s4_body_layout = QVBoxLayout(_s4_body)
        _s4_body_layout.setContentsMargins(10, 0, 0, 0)
        _s4_body_layout.setSpacing(0)

        _s4_body_layout.addSpacing(12)

        self._round1_frame, self._round1_participants_layout = self._make_progress_frame(
            "Step 1 of 2 — Group Identifier"
        )
        _s4_body_layout.addWidget(self._round1_frame)
        _s4_body_layout.addSpacing(12)

        self._round2_frame, self._round2_participants_layout = self._make_progress_frame(
            "Step 2 of 2 — Registry"
        )
        _s4_body_layout.addWidget(self._round2_frame)

        layout.addWidget(_s4_body)
        layout.addSpacing(40)

    def _make_progress_frame(self, title: str) -> tuple["QFrame", "QVBoxLayout"]:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {colors.BORDER}; border-radius: 8px; "
            f"background: {colors.BACKGROUND_CONTENT}; padding: 16px; }}"
        )
        frame.setFixedWidth(510)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 8, 8, 8)
        fl.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 15px; color: {colors.TEXT_MENU};"
        )
        fl.addWidget(title_lbl)

        participants_container = QWidget()
        participants_layout = QVBoxLayout(participants_container)
        participants_layout.setContentsMargins(0, 0, 0, 0)
        participants_layout.setSpacing(0)
        fl.addWidget(participants_container)

        return frame, participants_layout

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self):
        QTimer.singleShot(
            100,
            lambda: self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            ),
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _get_init_state(self) -> WhisperInitState:
        db = self.app.vault.plugin_state.get("whisper", {}).get("db")
        if db is None:
            return WhisperInitState()
        return db.whisperInitState.get(keys=("init",)) or WhisperInitState()

    def _save_init_state(self, state: WhisperInitState):
        db = self.app.vault.plugin_state.get("whisper", {}).get("db")
        if db is not None:
            db.whisperInitState.pin(keys=("init",), val=state)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """Qt lifecycle hook — fires whenever setCurrentWidget makes us visible."""
        super().showEvent(event)
        if self.app.vault:
            self.on_show()

    def on_show(self):
        """Called when the page becomes visible.  Resumes from saved step."""
        self.clear_error()
        self.clear_success()

        # Reset all progressive sections — required when switching vaults so
        # that sections revealed for a previous vault are hidden for the new one.
        self._section2.hide()
        self._section3.hide()
        self._section4.hide()
        self._s3_propagation_widget.setEnabled(True)

        # Reset section 1 to pre-upload state
        self._s1_header_lbl.setText("Choose Your Identifier")
        self._s1_subtext_lbl.setText(
            "Select the single (non-group) identifier that will represent you "
            "in the weirwood network. This identifier will be uploaded to weirwood "
            "so peers can discover you."
        )
        self._s1_input.show()
        self._id_aid_label.show()
        self._s1_chosen.hide()

        # Stop any poller bound to the previous vault.
        if self._poller is not None:
            try:
                self._poller.signals.identifiers_changed.disconnect(self._on_identifiers_changed)
            except Exception:
                pass
            self._poller = None
        self._weirwood_identifiers = []
        self._round1_participant_labels: dict[str, "QLabel"] = {}
        self._round2_participant_labels: dict[str, "QLabel"] = {}

        self._load_identifier_dropdown()

        state = self._get_init_state()

        if state.init_step >= 2:
            alias = state.chosen_identifier_alias
            hab = self.app.vault.hby.habByName(alias) if alias else None
            if hab:
                self._apply_s1_uploaded(alias, hab.pre)
            self._section2.show()
            self._start_poller()

        if state.init_step >= 3:
            self._section3.show()
            self._populate_section3(state)   # sets self-label; skips selector if locked

            # Determine whether section 4 should be visible
        _show_s4 = state.init_step >= 4 or (state.init_step == 3 and state.section4_started)

        if _show_s4 and state.group_identifier_alias:
            smids = self._get_group_smids()
            if smids:
                # If counselor already complete but init_step not yet advanced, do it now
                if state.init_step == 3 and state.section4_started:
                    from keri.core import coring as _kc
                    _ghab = self.app.vault.hby.habByName(state.group_identifier_alias)
                    if _ghab is not None:
                        _pfx = _kc.Prefixer(qb64=_ghab.pre)
                        _seq = _kc.Seqner(sn=0)
                        if self.app.vault.counselor.complete(_pfx, _seq):
                            state.init_step = 4
                            if not state.group_signed_aids:
                                state.group_signed_aids = list(smids)
                            self._save_init_state(state)

                self._lock_section3(state, smids)
                self._section4.show()

                self._build_signing_rows(
                    self._round1_participants_layout,
                    self._round1_participant_labels,
                    smids,
                    state.group_signed_aids,
                )
                self._build_signing_rows(
                    self._round2_participants_layout,
                    self._round2_participant_labels,
                    smids,
                    state.registry_signed_aids,
                )

                if state.init_step >= 4 and not state.init_complete:
                    registry_name = f"{state.group_identifier_alias}-registry"
                    registry = self.app.vault.rgy.registryByName(registry_name)
                    if registry is not None:
                        _reg = vdr_credentialing.Registrar(
                            hby=self.app.vault.hby,
                            rgy=self.app.vault.rgy,
                            counselor=self.app.vault.counselor,
                        )
                        if _reg.complete(pre=registry.regk, sn=0):
                            self._on_init_complete(registry.regk)
                        elif state.is_proposer:
                            self._launch_create_registry_doer(state.group_identifier_alias)
                        # else joiner: registry exists but not complete — waiting
                    elif state.is_proposer:
                        self._launch_create_registry_doer(state.group_identifier_alias)
                    # else joiner at init_step==4 with no registry: waiting for /multisig/vcp
                # else: init_step==3 + section4_started — WhisperCounselingCompletionDoer running

        # Reconnect doer event listener for the current vault.
        if self.app.vault and hasattr(self.app.vault, "signals"):
            try:
                self.app.vault.signals.doer_event.disconnect(self._on_doer_event)
            except Exception:
                pass
            self.app.vault.signals.doer_event.connect(self._on_doer_event)

    # ------------------------------------------------------------------
    # Section 1
    # ------------------------------------------------------------------

    def _load_identifier_dropdown(self):
        """Populate dropdown with local non-group habs."""
        if not self.app.vault:
            return
        from keri.app.habbing import GroupHab
        self._id_dropdown.clear()
        self._id_alias_map: dict[str, str] = {}
        for aid, hab in self.app.vault.hby.habs.items():
            if isinstance(hab, GroupHab):
                continue
            display = f"{hab.name} - {aid}"
            self._id_alias_map[display] = aid
            self._id_dropdown.addItem(display)
        self._id_dropdown.setCurrentIndex(-1)

    def _on_identifier_changed(self, index: int):
        if index < 0:
            self._id_aid_label.setText("")
            return
        display = self._id_dropdown.currentText()
        aid = self._id_alias_map.get(display)
        hab = self.app.vault.hby.habs.get(aid) if aid else None
        if hab:
            self._id_aid_label.setText(f"{hab.name} - {aid}")

    def _apply_s1_uploaded(self, alias: str, aid: str):
        """Swap section 1 from selection mode to confirmation mode."""
        self._s1_header_lbl.setText("Your Whisper Identifier Has Been Chosen!")
        self._s1_subtext_lbl.setText(
            "This identifier has been uploaded to weirwood and will represent "
            "you in the shared network."
        )
        self._s1_chosen_name_lbl.setText(alias)
        self._s1_chosen_aid_lbl.setText(aid)
        self._s1_input.hide()
        self._id_aid_label.hide()
        self._s1_chosen.show()

    @qasync.asyncSlot()
    async def _on_upload_clicked(self):
        state = self._get_init_state()
        display = self._id_dropdown.currentText()
        if not display:
            self.show_error("Please select an identifier.")
            return

        aid = self._id_alias_map.get(display)
        hab = self.app.vault.hby.habs.get(aid) if aid else None
        if hab is None:
            self.show_error("Selected identifier not found.")
            return

        # Build OOBI if available
        oobi = ""
        try:
            oobi_result = hab.makeOwnEndRole()
            if oobi_result:
                oobi = oobi_result.decode() if isinstance(oobi_result, bytes) else str(oobi_result)
        except Exception:
            pass

        # Serialize the full KEL (events + attachments) from local LMDB.
        try:
            kel_bytes = b"".join(self.app.vault.hby.db.clonePreIter(pre=hab.pre, fn=0))
        except Exception as e:
            self.show_error(f"Failed to serialize KEL for upload: {e}")
            return

        if not kel_bytes:
            self.show_error("No KEL events found for selected identifier — cannot upload.")
            return

        self._upload_button.setEnabled(False)
        self._upload_button.setText("Uploading…")
        self.clear_error()

        result = await remoting.upload_identifier(self.app, aid=hab.pre, alias=hab.name, kel_bytes=kel_bytes, oobi=oobi)

        self._upload_button.setEnabled(True)
        self._upload_button.setText("Upload to Weirwood")

        if result.get("conflict"):
            self.show_error(
                f"The alias '{hab.name}' is already uploaded to weirwood. "
                "Rename your local identifier if this is your first upload."
            )
            return

        if not result.get("success"):
            self.show_error(f"Upload failed: {result.get('error', 'unknown error')}")
            return

        self.clear_error()
        state.chosen_identifier_alias = hab.name
        state.chosen_identifier_aid = hab.pre
        state.identifier_uploaded = True
        state.init_step = 2
        self._save_init_state(state)

        self._apply_s1_uploaded(hab.name, hab.pre)
        self._section2.show()
        self._scroll_to_bottom()
        self._start_poller()

    # ------------------------------------------------------------------
    # Section 2
    # ------------------------------------------------------------------

    def _start_poller(self):
        if self._poller is not None:
            return
        self._poller = UploadedIdentifierPoller(self.app)
        self._poller.signals.identifiers_changed.connect(self._on_identifiers_changed)
        self.app.vault.extend([self._poller])
        # Trigger an immediate poll
        self._poller._poll()

    def _on_identifiers_changed(self, identifiers: list[dict]):
        self._weirwood_identifiers = identifiers
        state = self._get_init_state()
        chosen_alias = state.chosen_identifier_alias
        chosen_hab = self.app.vault.hby.habByName(chosen_alias)
        chosen_aid = chosen_hab.pre if chosen_hab else ""
        peers = [i for i in identifiers if i["aid"] != chosen_aid]

        count = len(peers)
        self._peer_count_label.setText(f"{count} peer(s) have joined weirwood")

        if count >= 1:
            self._s2_header_lbl.setText("Weirwood Peers are Available!")
            self._s2_subtext_lbl.setText(
                "Multiple Weirwood peers are available to form a group identifier."
            )
            # Auto-advance to section 3 if not already there.
            if not self._section3.isVisible():
                state.init_step = 3
                self._save_init_state(state)
                self._populate_section3(state)
                self._section3.show()
                self._scroll_to_bottom()
            else:
                # Refresh participant selector with updated identifiers.
                self._populate_section3(state)
        else:
            # If section 3 is already visible, still refresh the participant selector.
            if self._section3.isVisible():
                self._populate_section3(state)

    # ------------------------------------------------------------------
    # Section 3
    # ------------------------------------------------------------------

    def _populate_section3(self, state: WhisperInitState):
        """Populate participant selector from current weirwood identifiers."""
        alias = state.chosen_identifier_alias
        hab = self.app.vault.hby.habByName(alias)

        # Rebuild participant selector from weirwood identifiers (excluding own)
        chosen_aid = hab.pre if hab else ""
        # Always update self-identity labels
        if hab:
            self._s3_self_name_lbl.setText(alias or "—")
            self._s3_self_aid_lbl.setText(chosen_aid or "—")
        # Skip rebuilding selector if section 3 is already locked
        if state.section4_started or state.init_step >= 4:
            return
        items = [
            (i["alias"], {"aid": i["aid"], "alias": i["alias"], "oobi": i.get("oobi", "")})
            for i in self._weirwood_identifiers
            if i["aid"] != chosen_aid
        ]

        if self._participants_selector is not None:
            self._participants_container_layout.removeWidget(self._participants_selector)
            self._participants_selector.deleteLater()
            self._participants_selector = None

        self._participants_selector = ExtensibleSelectorWidget(
            dropdown_label="Select Participant",
            selector_dropdown_items=items,
            parent=self,
            max_scrollable_height=200,
        )
        self._participants_selector.setFixedWidth(500)
        self._participants_container_layout.addWidget(self._participants_selector)

        # TODO Implement delegation, we will also need to lock delegation selection on section progression

        if self._delegator_selector is not None:
            self._delegator_container_layout.removeWidget(self._delegator_selector)
            self._delegator_selector.deleteLater()
            self._delegator_selector = None

        self._delegator_selector = ExtensibleSelectorWidget(
            dropdown_label="Select Delegator",
            selector_dropdown_items=items,
            parent=self,
            max_scrollable_height=200,
        )
        self._delegator_selector.setFixedWidth(500)
        self._delegator_container_layout.addWidget(self._delegator_selector)

    def _on_create_group_clicked(self):
        state = self._get_init_state()
        alias = self._group_alias_field.text().strip()
        if not alias:
            self.show_error("Please enter a group identifier alias.")
            return

        chosen_alias = state.chosen_identifier_alias
        mhab = self.app.vault.hby.habByName(chosen_alias)
        if mhab is None:
            self.show_error("Your signing identifier was not found in the vault.")
            return

        if self._participants_selector is None:
            self.show_error("Participants selector not initialized.")
            return

        selected = self._participants_selector.get_selected_items()
        if not selected:
            self.show_error("Select at least one other participant.")
            return

        smids = [mhab.pre]
        for _, data in selected:
            aid = data.get("aid")
            if aid and aid not in smids:
                smids.append(aid)

        isith = self._signing_threshold.text().strip() or "1"
        nsith = self._rotation_threshold.text().strip() or "1"
        toad = int(self._toad_field.text().strip() or "0")

        state.group_identifier_alias = alias
        state.is_proposer = True
        self._save_init_state(state)

        self._create_group_button.setEnabled(False)
        self._create_group_button.setText("Creating…")
        self.clear_error()

        doer = WhisperGroupMultisigInceptDoer(
            app=self.app,
            alias=alias,
            mhab=mhab,
            smids=smids,
            isith=isith,
            nsith=nsith,
            toad=toad,
            propagation_mode=self._s3_propagation_widget.current_mode(),
            signal_bridge=self.app.vault.signals,
        )
        self.app.vault.extend([doer])

    # ------------------------------------------------------------------
    # Section 4
    # ------------------------------------------------------------------

    def _lock_section3(self, state: "WhisperInitState", smids: list[str]) -> None:
        """Freeze all section 3 inputs and display frozen participant list."""
        # Update header
        if state.is_proposer:
            self._s3_header_lbl.setText("Group Identifier Created")
            self._s3_subtext_lbl.setText(
                "The fields below reflect the parameters of the created group identifier."
            )
        else:
            self._s3_header_lbl.setText("Group Identifier Joined")
            self._s3_subtext_lbl.setText(
                "The fields below reflect the parameters of the group identifier you joined."
            )

        # For joiner: populate fields from persisted state before disabling
        if not state.is_proposer:
            self._group_alias_field.setText(state.group_identifier_alias)
            self._signing_threshold.setText(state.group_isith or "1")
            self._rotation_threshold.setText(state.group_nsith or "1")
            self._toad_field.setText(state.group_toad or "0")

        # Disable all inputs
        self._group_alias_field.setReadOnly(True)
        self._signing_threshold.setReadOnly(True)
        self._rotation_threshold.setReadOnly(True)
        self._s3_propagation_widget.setEnabled(False)
        self._toad_field.setReadOnly(True)
        self._create_group_button.hide()

        # Hide interactive selector, show frozen list of other participants
        self._participants_container.hide()
        # Clear and rebuild frozen list
        while self._s3_frozen_participants_layout.count():
            item = self._s3_frozen_participants_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        own_aid = state.chosen_identifier_aid
        others = [aid for aid in smids if aid != own_aid]

        if len(others) > 4:
            from PySide6.QtWidgets import QScrollArea
            scroll = QScrollArea()
            scroll.setMaximumHeight(260)   # ~4 rows
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            container = QWidget()
            c_layout = QVBoxLayout(container)
            c_layout.setContentsMargins(0, 0, 0, 0)
            c_layout.setSpacing(0)
            for aid in others:
                c_layout.addWidget(self._make_participant_label_row(aid))
            scroll.setWidget(container)
            self._s3_frozen_participants_layout.addWidget(scroll)
        else:
            for aid in others:
                self._s3_frozen_participants_layout.addWidget(self._make_participant_label_row(aid))

        self._s3_frozen_participants_widget.show()


    def _reveal_section4_waiting(
            self, group_alias: str, smids: list[str], is_proposer: bool, data: dict
    ) -> None:
        """Show section 4 before group inception is complete. Lock section 3."""
        state = self._get_init_state()
        state.group_identifier_alias = group_alias
        state.is_proposer = is_proposer
        state.section4_started = True
        state.group_isith = data.get("isith", "1")
        state.group_nsith = data.get("nsith", "1")
        state.group_toad = data.get("toad", "0")

        # Proposer's own AID signs first
        if is_proposer:
            own_aid = state.chosen_identifier_aid
            if own_aid and own_aid not in state.group_signed_aids:
                state.group_signed_aids.append(own_aid)

        self._save_init_state(state)
        self._lock_section3(state, smids)

        self._section4.show()
        self._scroll_to_bottom()

        # Build Round 1 rows (own ✓ for proposer, all ○ for joiner)
        self._build_signing_rows(
            self._round1_participants_layout,
            self._round1_participant_labels,
            smids,
            state.group_signed_aids,
        )
        # Build Round 2 rows (all ○)
        self._build_signing_rows(
            self._round2_participants_layout,
            self._round2_participant_labels,
            smids,
            [],
        )
    def _launch_create_registry_doer(self, group_alias: str):
        """Launch CreateRegistryDoer for the given group alias."""
        weirwood_cfg = self.app.config.plugin_configs.get("whisper", {})
        backer_aid = self.app.vault.plugin_state.get("whisper", {}).get("backer_aid", "")
        weirwood_aid = backer_aid or weirwood_cfg.get("weirwood_aid", "")
        registry_name = f"{group_alias}-registry"
        doer = CreateRegistryDoer(
            app=self.app,
            hab_alias=group_alias,
            registry_name=registry_name,
            weirwood_aid=weirwood_aid,
            signal_bridge=self.app.vault.signals,
        )
        self.app.vault.extend([doer])

    # ------------------------------------------------------------------
    # Doer event listener
    # ------------------------------------------------------------------

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        # ---- WhisperGroupMultisigInceptDoer ----
        if doer_name == "WhisperGroupMultisigInceptDoer":
            if event_type == "group_inception_exn_sent":
                smids = data.get("smids", [])
                alias = data.get("alias", "")
                if smids and alias:
                    self._reveal_section4_waiting(alias, smids, is_proposer=True, data=data)

            elif event_type == "group_participant_signed":
                signer_aid = data.get("signer_aid", "")
                if signer_aid:
                    self._update_signing_row(self._round1_participant_labels, signer_aid, signed=True)

            elif event_type == "group_identifier_created":
                state = self._get_init_state()
                state.init_step = 4
                smids = self._get_group_smids()
                # Mark all Round 1 as confirmed
                for aid in smids:
                    self._update_signing_row(self._round1_participant_labels, aid, signed=True)
                state.group_signed_aids = list(smids)
                # Proposer's own AID begins registry signing
                own_aid = state.chosen_identifier_aid
                if own_aid and own_aid not in state.registry_signed_aids:
                    state.registry_signed_aids.append(own_aid)
                self._save_init_state(state)
                # Flip proposer's Round 2 row to signed
                self._update_signing_row(self._round2_participant_labels, own_aid, signed=True)
                self._launch_create_registry_doer(data.get("alias", ""))

            elif event_type == "group_inception_failed":
                state = self._get_init_state()
                if not state.section4_started:
                    # Section 4 was never revealed — restore create button
                    self._create_group_button.setEnabled(True)
                    self._create_group_button.setText("Create Group Identifier")
                    self._create_group_button.show()
                self.show_error(f"Group creation failed: {data.get('error')}")

        # ---- WhisperMultisigJoinDoer ----
        elif doer_name == "WhisperMultisigJoinDoer":
            if event_type == "group_join_waiting":
                smids = data.get("smids", [])
                alias = data.get("alias", "")
                if smids and alias:
                    self._reveal_section4_waiting(alias, smids, is_proposer=False, data=data)

            elif event_type == "group_identifier_joined":
                state = self._get_init_state()
                state.init_step = 4
                smids = self._get_group_smids()
                for aid in smids:
                    self._update_signing_row(self._round1_participant_labels, aid, signed=True)
                state.group_signed_aids = list(smids)
                self._save_init_state(state)
                # Round 2 stays all-pending; joiner waits for registry proposal

            elif event_type == "group_join_failed":
                state = self._get_init_state()
                if not state.section4_started:
                    self._create_group_button.setEnabled(True)
                    self._create_group_button.setText("Create Group Identifier")
                    self._create_group_button.show()
                self.show_error(f"Group join failed: {data.get('error')}")

        # ---- CreateRegistryDoer ----
        elif doer_name == "CreateRegistryDoer":
            if event_type == "registry_participant_signed":
                signer_aid = data.get("signer_aid", "")
                if signer_aid:
                    self._update_signing_row(self._round2_participant_labels, signer_aid, signed=True)

            elif event_type == "registry_created":
                smids = self._get_group_smids()
                for aid in smids:
                    self._update_signing_row(self._round2_participant_labels, aid, signed=True)
                state = self._get_init_state()
                state.registry_signed_aids = list(smids)
                self._save_init_state(state)
                self._on_init_complete(data.get("regk", ""))

            elif event_type == "registry_creation_failed":
                self.show_error(f"Registry creation failed: {data.get('error')}")

        # ---- WhisperRegistryAcceptDoer ----
        elif doer_name == "WhisperRegistryAcceptDoer":
            if event_type == "registry_accept_waiting":
                own_aid = data.get("own_aid", "")
                if own_aid:
                    state = self._get_init_state()
                    if own_aid not in state.registry_signed_aids:
                        state.registry_signed_aids.append(own_aid)
                        self._save_init_state(state)
                    self._update_signing_row(self._round2_participant_labels, own_aid, signed=True)

            elif event_type == "registry_accepted":
                smids = self._get_group_smids()
                for aid in smids:
                    self._update_signing_row(self._round2_participant_labels, aid, signed=True)
                state = self._get_init_state()
                state.registry_signed_aids = list(smids)
                self._save_init_state(state)
                self._on_init_complete(data.get("regk", ""))

            elif event_type == "registry_accept_failed":
                self.show_error(f"Registry acceptance failed: {data.get('error')}")

    def _on_init_complete(self, regk: str):
        """Mark initialization as complete and navigate to issued credentials."""
        state = self._get_init_state()
        state.init_complete = True
        self._save_init_state(state)

        self._s4_header_lbl.setText("Initialized!")
        self._s4_subtext_lbl.setText(
            "Signatures have been coordinated across participants. "
            "You are ready to issue credentials."
        )

        # Stop the poller
        if self._poller is not None:
            try:
                self.app.vault.remove([self._poller])
            except Exception:
                pass
            self._poller = None

        # Navigate to issued credentials
        vault_page = getattr(self.app, "_vault_page", None)
        if vault_page and hasattr(vault_page, "_on_plugin_entry_clicked"):
            vault_page._on_plugin_entry_clicked("whisper")

    def _resolve_aid_alias(self, aid: str) -> str:
        hab = self.app.vault.hby.habs.get(aid)
        if hab:
            return hab.name
        contact = self.app.vault.org.get(aid)
        if contact:
            return contact.get("alias", "")
        return ""

    def _get_group_smids(self) -> list[str]:
        state = self._get_init_state()
        if not state.group_identifier_alias:
            return []
        ghab = self.app.vault.hby.habByName(state.group_identifier_alias)
        if ghab is None:
            return []
        return list(self.app.vault.hby.db.signingMembers(pre=ghab.pre))

    def _build_signing_rows(
            self,
            participants_layout: "QVBoxLayout",
            participant_labels_dict: dict,
            smids: list[str],
            signed_aids: list[str],
    ) -> None:
        """Clear and rebuild participant signing rows into participants_layout."""
        # Clear existing rows
        while participants_layout.count():
            item = participants_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        participant_labels_dict.clear()

        for aid in smids:
            signed = aid in signed_aids
            alias = self._resolve_aid_alias(aid)
            text = f"{'✓ ' if signed else '○ '}{alias} — {aid}" if alias else f"{'✓ ' if signed else '○ '}{aid}"
            lbl = QLabel(text)
            # lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"font-size: 11px; color: {colors.SUCCESS if signed else colors.TEXT_SUBTLE}; border: none;"
            )
            participants_layout.addWidget(lbl)
            participant_labels_dict[aid] = lbl

    def _update_signing_row(
            self, participant_labels_dict: dict, aid: str, signed: bool
    ) -> None:
        lbl = participant_labels_dict.get(aid)
        if lbl is None:
            return
        alias = self._resolve_aid_alias(aid)
        prefix = "✓ " if signed else "○ "
        lbl.setText(f"{prefix}{alias} — {aid}" if alias else f"{prefix}{aid}")
        lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.SUCCESS if signed else colors.TEXT_SUBTLE}; border: none;"
        )

    def _make_participant_label_row(self, aid: str) -> "QWidget":
        """Two-label row (name bold 15px / AID monospace 11px) for frozen s3 display."""
        alias = self._resolve_aid_alias(aid)
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 0, 6)
        vbox.setSpacing(2)
        name_lbl = QLabel(alias if alias else aid[:24] + "…")
        name_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        aid_lbl = QLabel(aid)
        aid_lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        vbox.addWidget(name_lbl)
        vbox.addWidget(aid_lbl)
        return widget
