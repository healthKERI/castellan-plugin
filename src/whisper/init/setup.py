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
    LocksmithButton, LocksmithInvertedButton,
)
from locksmith.ui.toolkit.widgets.fields import (
    FloatingLabelComboBox, FloatingLabelLineEdit, LocksmithLineEdit,
)
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.toolkit.widgets.extensible import ExtensibleSelectorWidget

from ..core import remoting
from ..db.basing import WhisperInitState
from .doers import WhisperGroupMultisigInceptDoer, CreateRegistryDoer
from .poller import UploadedIdentifierPoller

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

from keri import help

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
        layout.addSpacing(20)

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
        self._upload_button.setFixedWidth(180)
        self._upload_button.clicked.connect(self._on_upload_clicked)
        s1_in.addWidget(self._upload_button)
        s1_in.addStretch()
        layout.addWidget(self._s1_input)

        self._id_aid_label = QLabel("")
        self._id_aid_label.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: monospace;"
        )
        layout.addWidget(self._id_aid_label)

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
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: monospace;"
        )
        s1_ch.addWidget(self._s1_chosen_aid_lbl)
        self._s1_chosen.hide()
        layout.addWidget(self._s1_chosen)

        layout.addSpacing(40)

    # -- Section 2: Wait for Peers --------------------------------------

    def _build_section2(self, layout: QVBoxLayout):
        self._add_section_header(
            layout,
            "Waiting for Peers",
            "Your identifier has been uploaded. Waiting for at least one peer to "
            "join before group identifier creation can begin.",
        )
        layout.addSpacing(12)

        self._peer_count_label = QLabel("0 peer(s) have joined weirwood")
        self._peer_count_label.setStyleSheet(
            f"font-size: 14px; color: {colors.TEXT_SUBTLE};"
        )
        layout.addWidget(self._peer_count_label)
        layout.addSpacing(20)

        self._continue_button = LocksmithButton("Continue to Group Setup →")
        self._continue_button.setFixedWidth(240)
        self._continue_button.setEnabled(False)
        self._continue_button.clicked.connect(self._on_continue_to_group)
        layout.addWidget(self._continue_button)
        layout.addSpacing(40)

    # -- Section 3: Create Group Identifier -----------------------------

    def _build_section3(self, layout: QVBoxLayout):
        self._add_section_header(
            layout,
            "Create Group Identifier or Wait to Join a Group",
            "Select peers to include in your group multisig identifier and create it, "
            "or wait here — if a peer invites you to join their group you will receive "
            "a notification to accept.",
        )
        layout.addSpacing(12)

        self._group_alias_field = FloatingLabelLineEdit("Group Identifier Alias")
        self._group_alias_field.setFixedWidth(500)
        layout.addWidget(self._group_alias_field)
        layout.addSpacing(12)

        participants_lbl = QLabel("Group Participants")
        participants_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(participants_lbl)

        self._participants_container = QWidget()
        self._participants_container_layout = QVBoxLayout(self._participants_container)
        self._participants_container_layout.setContentsMargins(0, 0, 0, 0)
        self._participants_selector: ExtensibleSelectorWidget | None = None
        layout.addWidget(self._participants_container)
        layout.addSpacing(12)

        thresholds_lbl = QLabel("Thresholds")
        thresholds_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(thresholds_lbl)

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
        layout.addLayout(thresh_row)
        layout.addSpacing(8)

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
        layout.addLayout(toad_row)
        layout.addSpacing(20)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._create_group_button = LocksmithButton("Create Group Identifier")
        self._create_group_button.setFixedWidth(220)
        self._create_group_button.clicked.connect(self._on_create_group_clicked)
        btn_row.addWidget(self._create_group_button)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addSpacing(40)

    # -- Section 4: Progress --------------------------------------------

    def _build_section4(self, layout: QVBoxLayout):
        self._add_section_header(
            layout,
            "Initializing…",
            "Coordinating signatures across participants. This may take a moment.",
        )
        layout.addSpacing(12)

        # Round 1 frame
        self._round1_frame = self._make_progress_frame(
            "Step 1 of 2 — Group Identifier",
            "Waiting for all participants to sign the group inception…",
        )
        layout.addWidget(self._round1_frame)
        layout.addSpacing(12)

        # Round 2 frame (dimmed until round 1 complete)
        self._round2_frame = self._make_progress_frame(
            "Step 2 of 2 — Registry",
            "Will begin after group identifier is confirmed.",
        )
        self._round2_status_label = self._round2_frame.findChild(QLabel, "status_label")
        layout.addWidget(self._round2_frame)
        layout.addSpacing(40)

    def _make_progress_frame(self, title: str, status: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {colors.BORDER}; border-radius: 8px; "
            f"background: white; padding: 16px; }}"
        )
        frame.setFixedWidth(500)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(16, 16, 16, 16)
        fl.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {colors.TEXT_MENU};")
        fl.addWidget(title_lbl)

        status_lbl = QLabel(status)
        status_lbl.setObjectName("status_label")
        status_lbl.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
        status_lbl.setWordWrap(True)
        fl.addWidget(status_lbl)
        return frame

    # ------------------------------------------------------------------
    # Shared helpers
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

        # Stop any poller bound to the previous vault.
        if self._poller is not None:
            try:
                self._poller.signals.identifiers_changed.disconnect(self._on_identifiers_changed)
            except Exception:
                pass
            self._poller = None
        self._weirwood_identifiers = []

        self._load_identifier_dropdown()

        state = self._get_init_state()

        if state.init_step >= 2:
            # Restore the post-upload confirmation view for section 1.
            alias = state.chosen_identifier_alias
            hab = self.app.vault.hby.habs.get(alias) if alias else None
            if hab:
                self._apply_s1_uploaded(alias, hab.pre)
            self._section2.show()
            self._continue_button.show()
            self._continue_button.setEnabled(False)
            self._start_poller()

        if state.init_step >= 3:
            self._continue_button.hide()
            self._section3.show()
            self._populate_section3(state)

        if state.init_step >= 4:
            self._section4.show()

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
        logger.info(f"HABS HERE")
        for alias, hab in self.app.vault.hby.habs.items():
            logger.info(f"HAB HERE")
            logger.info(f"{alias}, {hab}")
            if isinstance(hab, GroupHab):
                continue
            self._id_alias_map[alias] = alias
            self._id_dropdown.addItem(alias)
        self._id_dropdown.setCurrentIndex(-1)

    def _on_identifier_changed(self, index: int):
        if index < 0:
            self._id_aid_label.setText("")
            return
        alias = self._id_dropdown.currentText()
        hab = self.app.vault.hby.habs.get(alias)
        if hab:
            self._id_aid_label.setText(f"{hab.pre[:24]}…{hab.pre[-8:]}")

    def _apply_s1_uploaded(self, alias: str, aid: str):
        """Swap section 1 from selection mode to confirmation mode."""
        self._s1_header_lbl.setText("Your Whisper Identifier Has Been Chosen!")
        self._s1_subtext_lbl.setText(
            "This identifier has been uploaded to weirwood and will represent "
            "you in the shared network."
        )
        self._s1_chosen_name_lbl.setText(alias)
        self._s1_chosen_aid_lbl.setText(f"{aid[:32]}…{aid[-8:]}" if len(aid) > 44 else aid)
        self._s1_input.hide()
        self._id_aid_label.hide()
        self._s1_chosen.show()

    @qasync.asyncSlot()
    async def _on_upload_clicked(self):
        state = self._get_init_state()
        alias = self._id_dropdown.currentText()
        if not alias:
            self.show_error("Please select an identifier.")
            return

        hab = self.app.vault.hby.habs.get(alias)
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

        self._upload_button.setEnabled(False)
        self._upload_button.setText("Uploading…")
        self.clear_error()

        result = await remoting.upload_identifier(self.app, aid=hab.pre, alias=alias, oobi=oobi)

        self._upload_button.setEnabled(True)
        self._upload_button.setText("Upload to Weirwood")

        if result.get("conflict"):
            self.show_error(
                f"The alias '{alias}' is already uploaded to weirwood. "
                "Rename your local identifier if this is your first upload."
            )
            return

        if not result.get("success"):
            self.show_error(f"Upload failed: {result.get('error', 'unknown error')}")
            return

        self.clear_error()
        state.chosen_identifier_alias = alias
        state.identifier_uploaded = True
        state.init_step = 2
        self._save_init_state(state)

        self._apply_s1_uploaded(alias, hab.pre)
        self._section2.show()
        self._start_poller()
        self._scroll_to_bottom()

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
        # Peers are all identifiers except our own
        peers = [i for i in identifiers if i["aid"] != self.app.vault.hby.habs.get(state.chosen_identifier_alias, None) and True]
        # Simpler: just exclude current user's chosen aid
        chosen_alias = state.chosen_identifier_alias
        chosen_hab = self.app.vault.hby.habs.get(chosen_alias)
        chosen_aid = chosen_hab.pre if chosen_hab else ""
        peers = [i for i in identifiers if i["aid"] != chosen_aid]

        count = len(peers)
        self._peer_count_label.setText(
            f"{count} peer(s) have joined weirwood"
        )
        self._continue_button.setEnabled(count >= 1)

        # If section 3 is visible, refresh the participant selector
        if self._section3.isVisible():
            self._populate_section3(state)

    def _on_continue_to_group(self):
        state = self._get_init_state()
        state.init_step = 3
        self._save_init_state(state)
        self._continue_button.hide()
        self._populate_section3(state)
        self._section3.show()
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Section 3
    # ------------------------------------------------------------------

    def _populate_section3(self, state: WhisperInitState):
        """Populate participant selector from current weirwood identifiers."""
        alias = state.chosen_identifier_alias
        hab = self.app.vault.hby.habs.get(alias)

        # Rebuild participant selector from weirwood identifiers (excluding own)
        chosen_aid = hab.pre if hab else ""
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

    def _on_create_group_clicked(self):
        state = self._get_init_state()
        alias = self._group_alias_field.text().strip()
        if not alias:
            self.show_error("Please enter a group identifier alias.")
            return

        chosen_alias = state.chosen_identifier_alias
        mhab = self.app.vault.hby.habs.get(chosen_alias)
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
            signal_bridge=self.app.vault.signals,
        )
        self.app.vault.extend([doer])

    # ------------------------------------------------------------------
    # Section 4
    # ------------------------------------------------------------------

    def _show_section4(self, group_alias: str):
        """Reveal section 4 and start CreateRegistryDoer."""
        state = self._get_init_state()
        state.group_identifier_alias = group_alias
        state.init_step = 4
        self._save_init_state(state)

        self._section4.show()
        self._scroll_to_bottom()

        weirwood_cfg = self.app.config.plugin_configs.get("whisper", {})
        weirwood_aid = weirwood_cfg.get("weirwood_aid", "")
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
        if doer_name == "WhisperGroupMultisigInceptDoer":
            if event_type == "group_identifier_created":
                group_alias = data.get("alias", "")
                # Update round 1 status
                r1_status = self._round1_frame.findChild(QLabel, "status_label")
                if r1_status:
                    r1_status.setText("✓ Group identifier created")
                    r1_status.setStyleSheet(f"font-size: 13px; color: {colors.SUCCESS};")
                self._show_section4(group_alias)

                # Update round 2 status label
                if self._round2_status_label:
                    self._round2_status_label.setText(
                        "Waiting for all participants to confirm registry creation…"
                    )

            elif event_type == "group_inception_failed":
                self._create_group_button.setEnabled(True)
                self._create_group_button.setText("Create Group Identifier")
                self.show_error(f"Group creation failed: {data.get('error')}")

            elif event_type == "group_inception_exn_sent":
                self._create_group_button.setText("Waiting for participants…")
        elif doer_name == "WhisperMultisigJoinDoer":
            if event_type == "group_identifier_joined":
                group_alias = data.get("alias", "")
                self._show_section4(group_alias)
        elif doer_name == "WhisperRegistryAcceptDoer":
            if event_type == "registry_accepted":
                self._on_init_complete(data.get("regk", ""))
        elif doer_name == "CreateRegistryDoer":
            if event_type == "registry_created":
                if self._round2_status_label:
                    self._round2_status_label.setText("✓ Registry created")
                    self._round2_status_label.setStyleSheet(
                        f"font-size: 13px; color: {colors.SUCCESS};"
                    )
                self._on_init_complete(data.get("regk", ""))

            elif event_type == "registry_creation_failed":
                self.show_error(f"Registry creation failed: {data.get('error')}")

    def _on_init_complete(self, regk: str):
        """Mark initialization as complete and navigate to issued credentials."""
        state = self._get_init_state()
        state.init_complete = True
        self._save_init_state(state)

        # Stop the poller
        if self._poller is not None:
            try:
                self.app.vault.remove([self._poller])
            except Exception:
                pass
            self._poller = None

        # Navigate to issued credentials
        vault_page = getattr(self.app, "_vault_page", None)
        if vault_page and hasattr(vault_page, "_show_page"):
            vault_page._show_page("whisper_issued_credentials")
