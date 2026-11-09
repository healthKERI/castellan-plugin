# -*- encoding: utf-8 -*-
"""
castellan.issuers.view_credential_issuance module

Dialog for viewing a credential being issued by a multisig identifier.
Shows credential details, member signature status, and allows signing the credential issuance.
"""

import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
from keri import help
from keri.core import serdering, Siger, coring
from keri.core.scheming import Schemer
from keri.db import dbing
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton, LocksmithButton
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

from ..core import remoting
from ..credentials.issued.view import ViewIssuedCredentialDialog

logger = help.ogler.getLogger(__name__)


class ViewCredentialIssuanceDialog(LocksmithDialog):
    """Dialog for viewing a credential being issued by a multisig identifier."""

    closed = Signal()

    def __init__(self, app, identifier: dict, row_data: dict, parent=None):
        self.app = app
        self.identifier = identifier
        self.row_data = row_data
        self.state = identifier.get("_state")
        self.aid = identifier.get('aid')
        alias = identifier.get('alias', '')
        self.ixn_said = None
        self.ixn_siger = None
        self.grant_said = None
        self.grant_siger = None

        # Schema resolution tracking
        self._schema_load_btn = None
        self._schema_status_label = None
        self._schema_value_label = None
        self._schema_row_layout = None

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
        display_title = alias or (self.aid[:24] + "..." if self.aid else "Credential Issuance")
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)

        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self._finished)
        self.setFixedSize(825, 850)

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

        # Credential details
        self._add_credential_details()

        self.content_layout.addSpacing(16)

        # Members section
        self._add_members_section()

        self.content_layout.addSpacing(16)

        # Signing section
        if self.state == "credential_created":
            self._add_signing_section()
        elif self.state == "credential_signed":
            self._add_signed_message()

    def _add_aid_field(self):
        """Add AID field."""
        field_layout = QHBoxLayout()
        field_layout.setSpacing(8)

        label = QLabel("AID:")
        label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        field_layout.addWidget(label)

        value_label = QLabel(self.aid or "Unknown")
        value_label.setStyleSheet(f"color: {colors.TEXT_MENU};")
        value_label.setWordWrap(False)
        field_layout.addWidget(value_label)

        field_layout.addStretch()
        self.content_layout.addLayout(field_layout)
        self.content_layout.addSpacing(12)

    def _add_state_badge(self):
        """Add visual badge showing credential issuance state."""
        match self.state:
            case "credential_created":
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
            case "credential_signed":
                badge = QLabel("Pending other signatures")
                badge.setStyleSheet("""
                    QLabel {
                        background: #d1fae5;
                        color: #065f46;
                        padding: 2px 8px;
                        border-radius: 8px;
                        font-size: 10px;
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

    def _add_credential_details(self):
        """Display credential details."""
        # Section header with "View" link
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        section_label = QLabel("Credential Details")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
        header_row.addWidget(section_label)

        # "View" link button
        view_link = QPushButton("View")
        view_link.setCursor(Qt.CursorShape.PointingHandCursor)
        view_link.setFlat(True)
        view_link.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {colors.BLUE_ACCENT};
                text-decoration: underline;
                font-size: 13px;
                text-align: left;
                padding: 0;
                margin-top: 16px;
            }}
            QPushButton:hover {{
                color: {colors.BLUE_SELECTION};
            }}
        """)
        view_link.clicked.connect(self._on_view_credential_clicked)
        header_row.addWidget(view_link)

        header_row.addStretch()
        self.content_layout.addLayout(header_row)
        self.content_layout.addSpacing(8)

        # Get credential info
        credential = self.identifier.get('credential', {})
        current_metadata = self.identifier.get('current_metadata', {})

        # Schema SAID from credential
        self.schema_said = credential.get('s', '')

        # Schema name - try local database first, then metadata, then SAID
        self.schema_name = self.schema_said or 'Unknown'
        if self.schema_said:
            # Check if schema is loaded locally and get title from it
            schemer = self.app.vault.hby.db.schema.get(keys=(self.schema_said,))
            if schemer:
                self.schema_name = schemer.sed.get('title', self.schema_said)
            elif current_metadata.get('schema_title'):
                self.schema_name = current_metadata.get('schema_title')

        # Recipient AID
        attrib = credential.get('a', {})
        self.recipient_aid = attrib.get('i', 'Unknown')

        # Credential ID (SAID)
        self.credential_said = credential.get('d', 'Unknown')

        # Create details frame
        details_frame = QFrame()
        details_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                background: {colors.BACKGROUND_CONTENT};
                padding: 12px;
            }}
        """)

        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(12, 12, 12, 12)
        details_layout.setSpacing(12)

        # Schema row with load button or loaded status
        self._schema_row_layout = QHBoxLayout()
        schema_label = QLabel("Schema:")
        schema_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        schema_label.setFixedWidth(135)
        self._schema_row_layout.addWidget(schema_label)

        # Schema value label
        self._schema_value_label = QLabel(self.schema_name)
        self._schema_value_label.setStyleSheet(f"color: {colors.TEXT_MENU};")
        self._schema_value_label.setWordWrap(False)
        self._schema_row_layout.addWidget(self._schema_value_label, stretch=1)

        # Add load button or loaded status based on schema state
        if self._is_schema_loaded():
            # Show "Loaded" badge
            self._schema_status_label = QLabel("Loaded")
            self._schema_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._schema_status_label.setStyleSheet("""
                QLabel {
                    background: #d1fae5;
                    color: #065f46;
                    padding: 2px 8px;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
            """)
            self._schema_status_label.setFixedWidth(80)
            self._schema_row_layout.addWidget(self._schema_status_label)
        else:
            # Show "Load Schema" button
            self._schema_load_btn = LocksmithInvertedButton("Load Schema")
            self._schema_load_btn.setFixedWidth(160)
            self._schema_load_btn.setFixedHeight(36)
            self._schema_load_btn.clicked.connect(self._on_load_schema_clicked)
            self._schema_row_layout.addWidget(self._schema_load_btn)

        details_layout.addLayout(self._schema_row_layout)

        # Recipient AID (truncated)
        recipient_row = QHBoxLayout()
        recipient_label = QLabel("Recipient:")
        recipient_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        recipient_label.setFixedWidth(135)
        recipient_row.addWidget(recipient_label)
        recipient_display = self.recipient_aid[:24] + "..." if len(self.recipient_aid) > 24 else self.recipient_aid
        recipient_value = QLabel(recipient_display)
        recipient_value.setStyleSheet(f"color: {colors.TEXT_MENU};")
        recipient_value.setWordWrap(False)
        recipient_value.setToolTip(self.recipient_aid)
        recipient_row.addWidget(recipient_value, stretch=1)
        details_layout.addLayout(recipient_row)

        # Credential ID (truncated)
        id_row = QHBoxLayout()
        id_label = QLabel("Credential ID:")
        id_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        id_label.setFixedWidth(135)
        id_row.addWidget(id_label)
        id_display = self.credential_said[:24] + "..." if len(self.credential_said) > 24 else self.credential_said
        id_value = QLabel(id_display)
        id_value.setStyleSheet(f"color: {colors.TEXT_MENU};")
        id_value.setWordWrap(False)
        id_value.setToolTip(self.credential_said)
        id_row.addWidget(id_value, stretch=1)
        details_layout.addLayout(id_row)

        self.content_layout.addWidget(details_frame)

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

        # Status badge - check if member has signed BOTH current_signature AND grant_signature
        has_ixn_sig = member.get('current_signature', None) is not None
        has_grant_sig = member.get('grant_signature', None) is not None
        has_signed = has_ixn_sig and has_grant_sig

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
            "The credential is ready to sign. Click the button below to sign the credential "
            "issuance event and notify other members."
        )
        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;")
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Sign button
        sign_btn_layout = QHBoxLayout()
        self.sign_btn = LocksmithButton("Sign Credential Issuance")
        self.sign_btn.setFixedWidth(240)
        self.sign_btn.clicked.connect(self._on_sign_clicked)
        sign_btn_layout.addWidget(self.sign_btn)
        sign_btn_layout.addStretch()

        self.content_layout.addLayout(sign_btn_layout)

        # Update sign button state based on schema loaded status
        self._update_sign_button_state()

    def _add_signed_message(self):
        """Add message indicating user has already signed."""
        success = QLabel("You have signed this credential issuance.")
        success.setStyleSheet(f"font-size: 13px; color: #065f46; font-weight: 600;")
        self.content_layout.addWidget(success)

    def _on_view_credential_clicked(self):
        """Handle View link click - open the ViewIssuedCredentialDialog."""
        credential_sad = self.identifier.get('credential', {})
        credential_said = credential_sad.get('d', '')
        schema_said = credential_sad.get('s')
        issuer = credential_sad.get('i')
        recipient = credential_sad.get('a', {}).get('i', '')

        schemer = self.app.vault.hby.db.schema.get(keys=(schema_said,))
        if not schemer:
            raise Exception(f"Schema {schema_said} not found")

        schema_title = schemer.sed.get('title', 'Untitled')

        # Construct credential dict in format expected by ViewIssuedCredentialDialog
        credential_data = {
            'sad': credential_sad,
            'said': credential_said,
            'status': "proposed",
            'schema_said': schema_said,
            'schema_title': schema_title,
            'issuer': issuer,
            'recipient': recipient,
            'publised': False,
            'notes': None,
            'dynamic_fields': [],
        }

        dialog = ViewIssuedCredentialDialog(
            app=self.app,
            credential=credential_data,
            parent=self,
        )
        dialog.show()

    def _is_schema_loaded(self) -> bool:
        """Check if schema is loaded in local database."""
        if not self.schema_said:
            return False
        return self.app.vault.hby.db.schema.get(keys=(self.schema_said,)) is not None

    def _update_sign_button_state(self):
        """Enable/disable sign button based on schema loaded status."""
        if hasattr(self, 'sign_btn') and self.sign_btn:
            schema_loaded = self._is_schema_loaded()
            self.sign_btn.setEnabled(schema_loaded)
            if not schema_loaded:
                self.sign_btn.setToolTip("Schema must be loaded before signing")
            else:
                self.sign_btn.setToolTip("")

    @qasync.asyncSlot()
    async def _on_load_schema_clicked(self):
        """Handle Load Schema button click - fetch schema from server and load into local database."""
        if not self.schema_said:
            self.show_error("No schema SAID available")
            return

        if self._schema_load_btn:
            self._schema_load_btn.setEnabled(False)
            self._schema_load_btn.setText("Loading...")

        try:
            # Fetch schema from server
            result = await remoting.fetch_schema(
                app=self.app,
                schema_said=self.schema_said,
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Failed to fetch schema: {error_msg}")
                self.show_error(f"Failed to load schema: {error_msg}")
                return

            schema_data = result.get('schema', {})
            if not schema_data:
                self.show_error("Schema data not found on server")
                return

            # Create Schemer object and save to local database
            schemer = Schemer(sed=schema_data)
            self.app.vault.hby.db.schema.pin(keys=(schemer.said,), val=schemer)

            logger.info(f"Schema {schemer.said} loaded successfully into local database")

            # Update schema name from loaded schema
            schema_title = schema_data.get('title', self.schema_name)
            self.schema_name = schema_title
            if self._schema_value_label:
                self._schema_value_label.setText(schema_title)

            # Replace load button with "Loaded" badge
            if self._schema_load_btn and self._schema_row_layout:
                self._schema_load_btn.setParent(None)
                self._schema_load_btn.deleteLater()
                self._schema_load_btn = None

                # Create and add "Loaded" badge in same position
                self._schema_status_label = QLabel("Loaded")
                self._schema_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._schema_status_label.setStyleSheet("""
                    QLabel {
                        background: #d1fae5;
                        color: #065f46;
                        padding: 2px 8px;
                        border-radius: 8px;
                        font-size: 10px;
                        font-weight: 600;
                    }
                """)
                self._schema_status_label.setFixedWidth(80)

                # Add badge to the schema row layout
                self._schema_row_layout.addWidget(self._schema_status_label)

            # Update sign button state
            self._update_sign_button_state()

        except Exception as e:
            logger.exception(f"Error loading schema: {e}")
            self.show_error(f"Failed to load schema: {str(e)}")

        finally:
            if self._schema_load_btn:
                self._schema_load_btn.setEnabled(True)
                self._schema_load_btn.setText("Load Schema")

    def _get_current_account_aid(self) -> str:
        """Get the current user's Castellan account AID."""
        if not self.app or not self.app.vault:
            return ""

        account = self.app.vault.plugin_state.get("castellan", {}).get("account", {})
        return account.get("aid", "")

    @qasync.asyncSlot()
    async def _on_sign_clicked(self):
        """Handle Sign button click - sign the credential issuance IXN and grant events."""
        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Signing...")

        multisig_id = self.identifier.get('id')

        try:
            # Get the hab for this identifier
            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            registry_pre = self.identifier.get("registry").get("registry_pre")
            registry = self.app.vault.rgy.regs[registry_pre] if registry_pre in self.app.vault.rgy.regs else None
            if not registry:
                self.sign_btn.setEnabled(True)
                self.sign_btn.setText("Sign Credential Issuance")
                self.show_error(f"Registry not found for registry pre {registry_pre}")
                return

            # Get events from identifier
            current_event = self.identifier.get("current_event")  # IXN
            current_tel_event = self.identifier.get("current_tel_event")  # ISS
            credential = self.identifier.get("credential")
            grant = self.identifier.get("grant")

            if not current_event or not grant:
                self.show_error("Missing required events for credential signing")
                return

            # Sign both events
            ixn_serder = serdering.SerderKERI(sad=current_event)
            ixn_siger = hab.sign(ser=ixn_serder.raw, indexed=True).pop()

            iss_serder = serdering.SerderKERI(sad=current_tel_event)

            creder = serdering.SerderACDC(sad=credential)

            grant_serder = serdering.SerderKERI(sad=grant)
            grant_siger = hab.sign(ser=grant_serder.raw, indexed=True).pop()

            # Gather existing signatures from other members
            members = self.identifier.get("members", [])
            my_idx = hab.smids.index(hab.mhab.pre)
            member_idxs = [my_idx]
            ixn_sigers = [ixn_siger]
            grant_sigers = [grant_siger]

            for member in members:
                if member.get("current_signature") and member.get("grant_signature"):
                    ixn_sigers.append(Siger(qb64=member.get("current_signature")))
                    grant_sigers.append(Siger(qb64=member.get("grant_signature")))
                    member_idxs.append(hab.smids.index(member.get("member_aid")))

            tholder = hab.kever.tholder

            # If threshold is satisfied, process locally and authenticate with witnesses
            if tholder.satisfy(member_idxs):
                self._awaiting_auth = True

                # Process the IXN event locally
                try:
                    hab.kvy.processEvent(serder=ixn_serder, sigers=ixn_sigers)
                    prefixer = coring.Prefixer(qb64=ixn_serder.pre)
                    seqner = coring.Seqner(sn=ixn_serder.sn)
                    saider = coring.Saider(qb64=ixn_serder.said)
                    registry.anchorMsg(pre=creder.said,
                                       regd=iss_serder.said,
                                       seqner=seqner,
                                       saider=saider)
                    registry.tvy.processEvent(serder=iss_serder, seqner=seqner, saider=saider)
                    self.app.vault.verifier.processCredential(creder=creder, prefixer=prefixer, seqner=seqner,
                                                              saider=coring.Saider(qb64=ixn_serder.said))

                except Exception as ex:
                    logger.exception(f"Unable to process IXN event: {ex}")
                    self.show_error(f"Unable to process IXN event: {str(ex)}")
                    return

                self.ixn_said = ixn_serder.said
                self.ixn_siger = ixn_siger
                self.creder = creder
                self.grant_said = grant_serder.said
                self.grant_siger = grant_siger

                if hab.kever.wits:
                    self.app.vault.signals.doer_event.connect(self._on_doer_event)
                    auth_dialog = WitnessAuthenticationDialog(
                        app=self.app,
                        hab=hab,
                        witness_ids=hab.kever.wits,
                        auth_only=True,
                        parent=self,
                    )
                    auth_dialog.open()
                    return

            # Upload signature to server without witness receipts
            result = await remoting.add_multisig_credential_signature(
                app=self.app,
                multisig_id=multisig_id,
                ixn_said=ixn_serder.said,
                ixn_siger=ixn_siger,
                grant_said=grant_serder.said,
                grant_siger=grant_siger
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to sign credential issuance: {error_msg}")
                return

            self._finished()

        except Exception as e:
            logger.exception(f"Error signing credential issuance: {e}")
            self.show_error(f"Error signing credential issuance: {str(e)}")

        finally:
            # Restore button state
            self.sign_btn.setEnabled(True)
            self.sign_btn.setText("Sign Credential Issuance")

    @qasync.asyncSlot(str, str, dict)
    async def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """Handle doer events from witness authentication."""
        if doer_name == "AuthenticateWitnessesDoer":
            if data['pre'] != self.aid:
                return

            self.app.vault.signals.doer_event.disconnect(self._on_doer_event)

            if event_type == "witness_authentication_failed":
                error = data['error']
                logger.error(f"Failed to authenticate with witnesses: {error}")
                self.show_error(f"Failed to authenticate with witnesses: {error}")

                self.sign_btn.setEnabled(True)
                self.sign_btn.setText("Sign Credential Issuance")
                return

            try:
                hab = self.app.vault.hby.habs.get(self.aid)
                multisig_id = self.identifier.get('id')

                # Get witness receipts from local DB
                wigers = []
                dgkey = dbing.dgKey(hab.pre, self.ixn_said)
                if wigs := hab.db.getWigs(key=dgkey):
                    for wig in wigs:
                        wigers.append(Siger(qb64b=bytes(wig)).qb64)

                # Upload to server with witness receipts
                result = await remoting.add_multisig_credential_signature(
                    app=self.app,
                    multisig_id=multisig_id,
                    ixn_said=self.ixn_said,
                    ixn_siger=self.ixn_siger,
                    grant_said=self.grant_said,
                    grant_siger=self.grant_siger,
                    witness_receipts=wigers
                )

                if not result.get('success'):
                    error_msg = result.get('error', 'Unknown error')
                    self.show_error(f"Failed to sign credential issuance: {error_msg}")
                    return

                self._finished()

            except Exception as e:
                logger.exception(f"Error signing credential issuance: {e}")
                self.show_error(f"Error signing credential issuance: {str(e)}")

            finally:
                # Restore button state
                self.sign_btn.setEnabled(True)
                self.sign_btn.setText("Sign Credential Issuance")
