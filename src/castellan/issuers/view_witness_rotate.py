# -*- encoding: utf-8 -*-
"""
castellan.issuers.view_witness_rotate module

Dialog for viewing a witness rotation that is being coordinated for a multisig identifier.
Shows proposed witnesses, resolution status, and allows approving the rotation.
"""

import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from keri import help, kering
from keri.core import coring, Siger
from keri.core.serdering import SerderKERI
from keri.db import basing, dbing
from keri.help import helping
from locksmith.core.remoting import resolve_oobi_sync
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton, LocksmithButton
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

from ..core import remoting, identifying

logger = help.ogler.getLogger(__name__)


class ViewWitnessRotateDialog(LocksmithDialog):
    """Dialog for viewing a witness rotation being coordinated for a multisig identifier."""

    closed = Signal()

    def __init__(self, app, identifier: dict, row_data: dict, parent=None):
        self.app = app
        self.identifier = identifier
        self.row_data = row_data
        self.state = identifier.get("_state")
        self.aid = identifier.get('aid')
        alias = identifier.get('alias', '')

        # Store witness resolve buttons for UI updates
        self._resolve_buttons = {}
        self._status_labels = {}

        # Create content widget and layout
        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setSpacing(5)

        # Build content
        self._build_content()

        # Add close button
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithInvertedButton("Close")
        button_row.addWidget(close_btn)
        button_row.addStretch()

        # Create title
        title_content = QWidget()
        title_content_layout = QVBoxLayout(title_content)
        title_content_layout.setContentsMargins(0, 0, 0, 0)
        display_title = alias or (self.aid[:24] + "..." if self.aid else "Witness Rotation")
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)

        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/witness2.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self._finished)
        self.setFixedSize(675, 775)

    def _finished(self):
        self.closed.emit()
        self.close()

    def _build_content(self):
        """Build the dialog content."""
        # AID field
        self._add_aid_field()

        # State badge
        self._add_state_badge()

        # Uploaded timestamp
        self._add_timestamp_field()

        self.content_layout.addSpacing(12)

        if self.state == "witness_rotate":
            # Original flow: Show witness auth section + witnesses section + approve section
            self._add_witness_auth_section()

            self.content_layout.addSpacing(16)

            self._add_witnesses_section()

            self.content_layout.addSpacing(16)

            # Threshold display
            self._add_threshold_display()

            self.content_layout.addSpacing(16)

            # Approve section
            self._add_approve_section()
        else:
            # witness_rotate_created or witness_rotate_signed: Show members section
            self._add_members_section()

            self.content_layout.addSpacing(16)

            # Signing section or signed message
            if self.state == "witness_rotate_created":
                self._add_signing_section()
            elif self.state == "witness_rotate_signed":
                self._add_signed_message()

    def _add_aid_field(self):
        """Add AID field."""
        field_layout = QHBoxLayout()
        field_layout.setSpacing(8)

        label = QLabel("AID:")
        label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        field_layout.addWidget(label)

        # Truncate AID with "..." if too long
        aid_display = self.aid or "Unknown"
        if len(aid_display) > 50:
            aid_display = aid_display[:24] + "..." + aid_display[-20:]
        value_label = QLabel(aid_display)
        value_label.setStyleSheet(f"color: {colors.TEXT_MENU};")
        value_label.setWordWrap(False)
        field_layout.addWidget(value_label)

        field_layout.addStretch()
        self.content_layout.addLayout(field_layout)
        self.content_layout.addSpacing(12)

    def _add_state_badge(self):
        """Add visual badge showing witness rotation state."""
        match self.state:
            case "witness_rotate":
                badge = QLabel("Pending your approval")
                badge.setStyleSheet("""
                    QLabel {
                        background: #fef3c7;
                        color: #92400e;
                        padding: 4px 12px;
                        border-radius: 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)
            case "witness_rotate_created":
                badge = QLabel("Pending your signature")
                badge.setStyleSheet("""
                    QLabel {
                        background: #fef3c7;
                        color: #92400e;
                        padding: 4px 12px;
                        border-radius: 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)
            case "witness_rotate_signed":
                badge = QLabel("Pending other signatures")
                badge.setStyleSheet("""
                    QLabel {
                        background: #d1fae5;
                        color: #065f46;
                        padding: 4px 12px;
                        border-radius: 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)
            case _:
                badge = QLabel("Unknown")
                badge.setStyleSheet("""
                    QLabel {
                        background: #dbeafe;
                        color: #1e40af;
                        padding: 4px 12px;
                        border-radius: 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)

        badge_layout = QHBoxLayout()
        badge_layout.addWidget(badge)
        badge_layout.addStretch()
        self.content_layout.addLayout(badge_layout)
        self.content_layout.addSpacing(8)

    def _add_timestamp_field(self):
        """Add uploaded timestamp field."""
        created_at = self.identifier.get('created_at', '')
        if created_at:
            dt = helping.fromIso8601(created_at)
            row = QHBoxLayout()
            label_widget = QLabel("Uploaded:")
            label_widget.setStyleSheet("font-weight: 500; font-size: 13px;")
            row.addWidget(label_widget)
            value_widget = QLabel(dt.strftime("%b %d, %Y %I:%M %p"))
            value_widget.setStyleSheet("font-size: 13px;")
            value_widget.setWordWrap(True)
            row.addWidget(value_widget)
            row.addStretch()
            self.content_layout.addLayout(row)

    def _add_witness_auth_section(self):
        """Display witness authentication QR codes and TOTP URLs."""
        from locksmith.ui.toolkit.widgets.panels import LocksmithQRPanel
        from PySide6.QtWidgets import QPushButton

        # Get witness rotate data
        witness_rotate = self.identifier.get('witness_rotate', {})
        adds = witness_rotate.get('adds', [])

        # Only show if there are witnesses with TOTP data
        witnesses_with_totp = [w for w in adds if w.get('witness_totps')]
        if not witnesses_with_totp:
            return

        # Section header
        section_label = QLabel("Witness Authentication")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
        self.content_layout.addWidget(section_label)
        self.content_layout.addSpacing(8)

        description_label = QLabel(
            "Scan the QR codes below with your authenticator app to set up 2FA for each witness."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
        self.content_layout.addWidget(description_label)
        self.content_layout.addSpacing(12)

        # Toggle QR button
        toggle_qr_button = QPushButton("( Toggle QR Codes )")
        toggle_qr_button.setFixedWidth(180)
        toggle_qr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_qr_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {colors.PRIMARY};
                border: none;
                font-size: 13px;
                text-align: left;
                padding: 4px;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        toggle_qr_button.clicked.connect(self._toggle_all_qr_codes)
        self.content_layout.addWidget(toggle_qr_button)
        self.content_layout.addSpacing(12)

        # Store panels for toggling
        self._auth_panels = []

        # Get controller info
        alias = self.identifier.get('alias', '')

        # Create panels for each witness
        PANELS_PER_ROW = 2
        for row_start in range(0, len(witnesses_with_totp), PANELS_PER_ROW):
            row_witnesses = witnesses_with_totp[row_start:row_start + PANELS_PER_ROW]
            panels_row = QHBoxLayout()
            panels_row.setSpacing(16)

            for idx, witness in enumerate(row_witnesses, start=row_start):
                witness_alias = witness.get('witness_alias', 'Unknown')
                witness_aid = witness.get('witness_aid', '')
                totps = witness.get('witness_totps', [])

                # Find the correct TOTP for my member and decrypt it
                ghab = self.app.vault.hby.habs[self.aid]
                my_idx = ghab.smids.index(ghab.mhab.pre)
                m = coring.Matter(qb64=totps[my_idx])
                d = coring.Matter(qb64=ghab.mhab.decrypt(ser=m.raw))
                secret_b32 = d.raw.decode('utf-8')
                totp_url = f"otpauth://totp/{ghab.pre}?secret={secret_b32}"

                panel = LocksmithQRPanel(
                    number=str(idx + 1),
                    witness_name=witness_alias,
                    witness_eid=witness_aid,
                    controller_alias=alias,
                    controller_aid=self.aid,
                    url=totp_url,
                    qr_visible=False  # Hidden initially
                )
                panels_row.addWidget(panel)
                self._auth_panels.append(panel)

            panels_row.addStretch()
            self.content_layout.addLayout(panels_row)

            # Add spacing between rows
            if row_start + PANELS_PER_ROW < len(witnesses_with_totp):
                self.content_layout.addSpacing(12)

    def _toggle_all_qr_codes(self):
        """Toggle QR code visibility for all auth panels."""
        if hasattr(self, '_auth_panels'):
            for panel in self._auth_panels:
                panel.toggle_qr_visibility()

    def _add_witnesses_section(self):
        """Display proposed witnesses with resolve buttons."""
        section_label = QLabel("Proposed Witnesses")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
        self.content_layout.addWidget(section_label)
        self.content_layout.addSpacing(8)

        # Create witnesses frame
        self.witnesses_frame = QFrame()
        self.witnesses_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                background: {colors.BACKGROUND_CONTENT};
                padding: 12px;
            }}
        """)

        self.witnesses_layout = QVBoxLayout(self.witnesses_frame)
        self.witnesses_layout.setContentsMargins(8, 8, 8, 8)
        self.witnesses_layout.setSpacing(8)

        # Get witness rotate data
        witness_rotate = self.identifier.get('witness_rotate', {})
        adds = witness_rotate.get('adds', [])

        for witness in adds:
            witness_row = self._create_witness_row(witness)
            self.witnesses_layout.addWidget(witness_row)

        if not adds:
            no_witnesses_label = QLabel("No witnesses to add")
            no_witnesses_label.setStyleSheet(f"font-style: italic; color: {colors.TEXT_SUBTLE};")
            self.witnesses_layout.addWidget(no_witnesses_label)

        self.content_layout.addWidget(self.witnesses_frame)

    def _create_witness_row(self, witness: dict) -> QWidget:
        """Create a single witness row display with resolve/resolved status."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        witness_aid = witness.get('witness_aid', '')
        witness_alias = witness.get('witness_alias', 'Unknown')

        # Alias
        alias_label = QLabel(witness_alias)
        alias_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        row_layout.addWidget(alias_label, stretch=2)

        # AID (truncated)
        aid_display = witness_aid
        if len(aid_display) > 24:
            aid_display = aid_display[:12] + "..." + aid_display[-8:]
        aid_label = QLabel(aid_display)
        aid_label.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-family: monospace; font-size: 11px;")
        row_layout.addWidget(aid_label, stretch=3)

        # Status badge or resolve button
        if self._is_witness_resolved(witness_aid):
            status_label = QLabel("Resolved")
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setStyleSheet("""
                QLabel {
                    background: #d1fae5;
                    color: #065f46;
                    padding: 2px 8px;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
            """)
            status_label.setFixedWidth(80)
            row_layout.addWidget(status_label)
            self._status_labels[witness_aid] = status_label
        else:
            resolve_btn = LocksmithInvertedButton("Resolve")
            resolve_btn.setFixedWidth(110)
            resolve_btn.setFixedHeight(36)
            resolve_btn.clicked.connect(lambda: self._on_resolve_clicked(witness))
            row_layout.addWidget(resolve_btn)
            self._resolve_buttons[witness_aid] = resolve_btn

        return row

    def _is_witness_resolved(self, witness_aid: str) -> bool:
        """Check if witness AID is in kevers (already resolved)."""
        return witness_aid in self.app.vault.kvy.kevers

    def _all_witnesses_resolved(self) -> bool:
        """Check if ALL witnesses are resolved."""
        witness_rotate = self.identifier.get('witness_rotate', {})
        adds = witness_rotate.get('adds', [])

        for witness in adds:
            witness_aid = witness.get('witness_aid', '')
            if not self._is_witness_resolved(witness_aid):
                return False

        return True

    def _update_approve_button_state(self):
        """Enable/disable approve button based on resolution status."""
        if hasattr(self, 'approve_btn'):
            all_resolved = self._all_witnesses_resolved()
            self.approve_btn.setEnabled(all_resolved)
            if not all_resolved:
                self.approve_btn.setToolTip("All witnesses must be resolved before approval")
            else:
                self.approve_btn.setToolTip("")

    def _add_threshold_display(self):
        """Display the proposed witness threshold."""
        witness_rotate = self.identifier.get('witness_rotate', {})
        threshold = witness_rotate.get('threshold', 1)

        threshold_layout = QHBoxLayout()
        threshold_layout.setSpacing(8)

        label = QLabel("Proposed Threshold:")
        label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        threshold_layout.addWidget(label)

        value_label = QLabel(str(threshold))
        value_label.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {colors.PRIMARY};")
        threshold_layout.addWidget(value_label)

        threshold_layout.addStretch()
        self.content_layout.addLayout(threshold_layout)

    def _add_approve_section(self):
        """Add approve button and instructions."""
        info = QLabel(
            "Once all witnesses are resolved, click the button below to approve "
            "this witness rotation and notify other members."
        )
        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;")
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Approve button
        approve_btn_layout = QHBoxLayout()
        self.approve_btn = LocksmithButton("Approve Witnesses")
        self.approve_btn.setFixedWidth(200)
        self.approve_btn.clicked.connect(self._on_approve_clicked)
        approve_btn_layout.addWidget(self.approve_btn)
        approve_btn_layout.addStretch()

        self.content_layout.addLayout(approve_btn_layout)

        # Update button state based on resolution status
        self._update_approve_button_state()

    @qasync.asyncSlot()
    async def _on_resolve_clicked(self, witness: dict):
        """Handle resolve button click - fetch and parse witness OOBI/KEL."""
        witness_aid = witness.get('witness_aid')
        witness_oobi = witness.get('witness_oobi')
        witness_alias = witness.get('witness_alias')

        # Get the resolve button for this witness
        resolve_btn = self._resolve_buttons.get(witness_aid)
        if resolve_btn:
            resolve_btn.setEnabled(False)
            resolve_btn.setText("...")

        obr = basing.OobiRecord(date=helping.nowIso8601(), oobialias=witness_alias)
        self.app.vault.hby.db.oobis.put(keys=(witness_oobi,), val=obr)

        self.app.vault.signals.doer_event.connect(self._on_doer_event)

        resolve_oobi_sync(
            app=self.app,
            pre=witness_aid,  # Use mailbox EID (not CID)
            oobi=witness_oobi,
            force=True,
            alias=witness_aid,
            cid=self.aid  # Pass controller as metadata
        )

    async def _refresh_witnesses_section(self):
        """Refresh the witnesses section to reflect updated resolution status."""
        # Clear the witnesses layout
        while self.witnesses_layout.count():
            item = self.witnesses_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Clear stored references
        self._resolve_buttons.clear()
        self._status_labels.clear()

        # Rebuild witness rows
        witness_rotate = self.identifier.get('witness_rotate', {})
        adds = witness_rotate.get('adds', [])

        for witness in adds:
            witness_row = self._create_witness_row(witness)
            self.witnesses_layout.addWidget(witness_row)

        if not adds:
            no_witnesses_label = QLabel("No witnesses to add")
            no_witnesses_label.setStyleSheet(f"font-style: italic; color: {colors.TEXT_SUBTLE};")
            self.witnesses_layout.addWidget(no_witnesses_label)

        # Update approve button state
        self._update_approve_button_state()

    @qasync.asyncSlot()
    async def _on_approve_clicked(self):
        """Handle approve button click - call API to update multisig witnesses."""
        self.approve_btn.setEnabled(False)
        self.approve_btn.setText("Approving...")

        try:
            # Get witness rotate data
            witness_rotate = self.identifier.get('witness_rotate', {})
            witness_adds = witness_rotate.get('adds', [])
            threshold = witness_rotate.get('threshold', 1)
            witness_cuts = witness_rotate.get('cuts', [])

            # Get the hab for this identifier
            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            members = self.identifier.get("members")

            verfer, diger = remoting.get_next_keys(hab.mhab)
            my_idx = hab.smids.index(hab.mhab.pre)
            members[my_idx]["public_key"] = verfer.qb64
            members[my_idx]["next_key_hash"] = diger.qb64

            member_idxs = []
            for member in members:
                if member.get("public_key"):
                    member_idxs.append(hab.smids.index(member.get("member_aid")))

            tholder = hab.kever.tholder
            # If all participants are enough to create the rotation event, do so, otherwise create without parsing
            if tholder.satisfy(member_idxs):
                verfers = []
                digers = []
                for idx, member in enumerate(members):
                    if member.get("public_key"):
                        verfers.append(coring.Verfer(qb64=member.get("public_key")))
                        digers.append(coring.Diger(qb64=member.get("next_key_hash")))
                    else:
                        verfers.append(hab.kever.verfers[idx])
                        digers.append(hab.kever.ndigers[idx])

                adds = [w.get("witness_aid") for w in witness_adds]
                cuts = [w.get("witness_aid") for w in witness_cuts]

                logger.info("Signing and submitting complete witness rotation")
                rot, sigers = identifying.create_multisig_rotation(hab, isith=hab.kever.tholder.sith,
                                                                   nsith=hab.kever.ntholder.sith,
                                                                   toad=threshold, cuts=cuts, adds=list(adds),
                                                                   data=None,
                                                                   verfers=verfers, digers=digers)

                result = await remoting.sign_multisig_witnesses(
                    app=self.app,
                    multisig_id=self.identifier.get('id'),
                    rot=rot,
                    sig=sigers[0].qb64,
                )

                if not result.get('success'):
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"Failed to approve witness rotation: {error_msg}")
                    self.show_error(f"Failed to approve: {error_msg}")
                    return

                logger.info(f"Successfully approved witness rotation for {self.aid}")
                self.show_success("Successfully approved witness rotation!")

                # Update identifier state
                self.identifier.update(result.get('data', {}))
                self.state = identifying.get_multisig_state(self.app, self.identifier)
                self.identifier["_state"] = self.state

            else:
                # Transform witness data to expected format
                formatted_adds = [
                    {
                        'aid': w.get('witness_aid'),
                        'alias': w.get('witness_alias'),
                        'oobi': w.get('witness_oobi'),
                        'totps': w.get('witness_totps', [])
                    }
                    for w in witness_adds
                ]

                # Call API
                result = await remoting.update_multisig_witnesses(
                    app=self.app,
                    multisig_id=self.identifier.get('id'),
                    verfer=verfer,
                    diger=diger,
                    adds=formatted_adds,
                    witness_threshold=threshold,
                    cuts=witness_cuts,
                )

                if not result.get('success'):
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"Failed to approve witness rotation: {error_msg}")
                    self.show_error(f"Failed to approve: {error_msg}")
                    return

                logger.info(f"Successfully approved witness rotation for {self.aid}")
                self.show_success("Successfully approved witness rotation!")

                # Update identifier state
                self.identifier.update(result.get('data', {}))
                self.state = identifying.get_multisig_state(self.app, self.identifier)
                self.identifier["_state"] = self.state

        except Exception as e:
            logger.exception(f"Error approving witness rotation: {e}")
            self.show_error(f"Error approving: {str(e)}")

        finally:
            self.approve_btn.setEnabled(True)
            self.approve_btn.setText("Approve Witnesses")

    def _add_members_section(self):
        """Display table of multisig members with their signature status."""
        section_label = QLabel("Members")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
        self.content_layout.addWidget(section_label)
        self.content_layout.addSpacing(8)

        members = self.identifier.get('members', [])
        my_account_aid = self._get_current_account_aid()

        # Create table frame
        members_frame = QFrame()
        members_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                background: {colors.BACKGROUND_CONTENT};
                padding: 12px;
            }}
        """)

        members_layout = QVBoxLayout(members_frame)
        members_layout.setContentsMargins(8, 8, 8, 8)
        members_layout.setSpacing(8)

        for member in members:
            member_row = self._create_member_row(member, my_account_aid)
            members_layout.addWidget(member_row)

        self.content_layout.addWidget(members_frame)

    def _create_member_row(self, member: dict, my_account_aid: str) -> QWidget:
        """Create a single member row display."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        # Username
        username = member.get('account_username', 'Unknown')
        is_me = member.get('account_aid') == my_account_aid

        name_label = QLabel(username + (" (You)" if is_me else ""))
        if is_me:
            name_label.setStyleSheet(f"font-weight: 600; color: {colors.PRIMARY};")
        else:
            name_label.setStyleSheet(f"color: {colors.TEXT_MENU};")

        row_layout.addWidget(name_label, stretch=3)

        # Status badge - check if member has signed
        has_signed = member.get('current_signature', None) is not None
        status_label = QLabel("Signed" if has_signed else "Not Signed")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if has_signed:
            status_label.setStyleSheet("""
                QLabel {
                    background: #d1fae5;
                    color: #065f46;
                    padding: 2px 8px;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
            """)
        else:
            status_label.setStyleSheet("""
                QLabel {
                    background: #fee2e2;
                    color: #991b1b;
                    padding: 2px 8px;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
            """)

        status_label.setFixedWidth(105)
        row_layout.addWidget(status_label)

        return row

    def _add_signing_section(self):
        """Add signing button and instructions."""
        info = QLabel(
            "The witness rotation event is ready to sign. Click the button below to sign "
            "the witness addition and notify other members."
        )
        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;")
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Sign button
        sign_btn_layout = QHBoxLayout()
        self.sign_btn = LocksmithButton("Sign Witness Rotation")
        self.sign_btn.setFixedWidth(225)
        self.sign_btn.clicked.connect(self._on_sign_clicked)
        sign_btn_layout.addWidget(self.sign_btn)
        sign_btn_layout.addStretch()

        self.content_layout.addLayout(sign_btn_layout)

    def _add_signed_message(self):
        """Add message indicating user has already signed."""
        success = QLabel("✓ You have signed this witness rotation.")
        success.setStyleSheet("font-size: 13px; color: #065f46; font-weight: 600;")
        self.content_layout.addWidget(success)

    @qasync.asyncSlot()
    async def _on_sign_clicked(self):
        """Handle Sign button click - sign the witness rotation event."""
        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Signing...")
        members = self.identifier.get("members")

        try:
            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            # Must rotate local Hab to join
            hab.mhab.rotate()

            current_event = self.identifier.get("current_event", {})
            rot = SerderKERI(sad=current_event)

            my_idx = hab.smids.index(hab.mhab.pre)
            sigers = hab.mhab.sign(ser=rot.raw, indexed=True, indices=[my_idx])

            member_idxs = [my_idx]
            sigers = [sigers[0]]

            for member in members:
                if member.get("current_signature"):
                    sigers.append(Siger(qb64=member.get("current_signature")))
                    member_idxs.append(hab.smids.index(member.get("member_aid")))

            tholder = hab.kever.tholder

            # If all participants are enough to create the rotation event, do so, otherwise create without parsing
            if tholder.satisfy(member_idxs):
                self._awaiting_auth = True

                try:
                    hab.kvy.processEvent(serder=rot, sigers=sigers)
                except Exception as ex:
                    print(ex)
                    self.show_error(f"Unable to parse rotation to valid event despite enough signatures")
                    return

                self.app.vault.signals.doer_event.connect(self._on_doer_event)
                auth_dialog = WitnessAuthenticationDialog(
                    app=self.app,
                    hab=hab,
                    witness_ids=current_event.get('ba'),
                    auth_only=False,
                    parent=self,
                )
                auth_dialog.open()

            else:
                # Build verfers and digers from members who have provided keys
                result = await remoting.sign_multisig_witnesses(
                    app=self.app,
                    multisig_id=self.identifier.get('id'),
                    rot=rot,
                    sig=sigers[0].qb64,
                )

                if not result.get('success'):
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"Failed to sign witness rotation: {error_msg}")
                    self.show_error(f"Failed to sign: {error_msg}")
                    return

                logger.info(f"Successfully signed witness rotation for {self.aid}")
                self.show_success("Successfully signed witness rotation!")

                # Update identifier state
                self.identifier.update(result.get('data', {}))
                self.state = identifying.get_multisig_state(self.app, self.identifier)
                self.identifier["_state"] = self.state

        except Exception as e:
            logger.exception(f"Error signing witness rotation: {e}")
            self.show_error(f"Error signing: {str(e)}")

        finally:
            self.sign_btn.setEnabled(True)
            self.sign_btn.setText("Sign Witness Addition")

    def _get_current_account_aid(self) -> str:
        """Get the current user's Castellan account AID."""
        if not self.app or not self.app.vault:
            return ""

        account = self.app.vault.plugin_state.get("castellan", {}).get("account", {})
        return account.get("aid", "")

    @qasync.asyncSlot(str, str, dict)
    async def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """Handle doer events from role setting and ResolveOobiDoer."""
        # Handle OOBI resolution events
        if doer_name == "ResolveOobiDoer":
            await self._refresh_witnesses_section()
            self.app.vault.signals.doer_event.disconnect(self._on_doer_event)

        elif doer_name == "AuthenticateWitnessesDoer":
            if data['pre'] != self.aid:
                return

            self.app.vault.signals.doer_event.disconnect(self._on_doer_event)

            if event_type == "witness_authentication_failed":
                error = data['error']
                logger.error(f"Failed to sign witnesses: {error}")
                self.show_error(f"Failed to sign witnesses: {error}")

                self.sign_btn.setEnabled(True)
                self.sign_btn.setText("Sign Witness Addition")
                return

            # Assumes event_type is "witness_authentication_success"
            hab = self.app.vault.hby.habs.get(self.aid)
            current_event = self.identifier.get("current_event", {})
            rot = SerderKERI(sad=current_event)

            my_idx = hab.smids.index(hab.mhab.pre)
            sigers = hab.mhab.sign(ser=rot.raw, indexed=True, indices=[my_idx])

            wigers = []
            dgkey = dbing.dgKey(hab.pre, rot.said)  # get message
            if wigs := hab.db.getWigs(key=dgkey):
                for wig in wigs:
                    wigers.append(Siger(qb64b=bytes(wig)).qb64)

            result = await remoting.sign_multisig_witnesses(
                app=self.app,
                multisig_id=self.identifier.get('id'),
                rot=rot,
                sig=sigers[0].qb64,
                witness_receipts=wigers,
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Failed to sign witness rotation: {error_msg}")
                self.show_error(f"Failed to sign: {error_msg}")
                return

            logger.info(f"Successfully signed witness rotation for {self.aid}")
            self.show_success("Successfully signed witness rotation!")

            # Update identifier state
            self.identifier.update(result.get('data', {}))
            self.state = identifying.get_multisig_state(self.app, self.identifier)
            self.identifier["_state"] = self.state
