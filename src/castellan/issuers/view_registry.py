# -*- encoding: utf-8 -*-
"""
castellan.issuers.view_registry module

Dialog for viewing a registry that is being created for a multisig identifier.
Shows registry details, member signature status, and allows signing the IXN event.
"""

import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from keri import help, core, kering
from keri.core import serdering, Siger, coring
from keri.core.coring import Seqner, Saider
from keri.core.eventing import SealEvent, messagize
from keri.db import dbing
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton, LocksmithButton
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

from ..core import remoting

logger = help.ogler.getLogger(__name__)


class ViewRegistryCreationDialog(LocksmithDialog):
    """Dialog for viewing a registry being created for a multisig identifier."""

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
        self.mailbox_said = None
        self.mailbox_siger = None
        self.registrar_said = None
        self.registrar_siger = None

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
        display_title = alias or (self.aid[:24] + "…" if self.aid else "Registry Creation")
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)

        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/shield_lock.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self._finished)
        self.setFixedSize(675, 850)

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

        # Registry details
        self._add_registry_details()

        self.content_layout.addSpacing(16)

        # Members section
        self._add_members_section()

        self.content_layout.addSpacing(16)

        # Signing section
        if self.state == "registry_created":
            self._add_signing_section()
        elif self.state == "registry_signed":
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
        """Add visual badge showing registry creation state."""
        match self.state:
            case "registry_created":
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
            case "registry_signed":
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

    def _add_registry_details(self):
        """Display registry details."""
        section_label = QLabel("Registry Details")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
        self.content_layout.addWidget(section_label)
        self.content_layout.addSpacing(8)

        # Get registry info from vcp field
        current_metadata = self.identifier.get('current_metadata', {})
        self.registry_name = current_metadata.get('registry_name', 'Unknown')
        self.registry_id = current_metadata.get('registry_said', 'Unknown')

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

        # Registry name
        name_row = QHBoxLayout()
        name_label = QLabel("Registry Name:")
        name_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        name_label.setFixedWidth(135)
        name_row.addWidget(name_label)
        name_value = QLabel(self.registry_name)
        name_value.setStyleSheet(f"color: {colors.TEXT_MENU};")
        name_value.setWordWrap(False)
        name_row.addWidget(name_value, stretch=1)
        details_layout.addLayout(name_row)

        # Registry ID
        id_row = QHBoxLayout()
        id_label = QLabel("Registry ID:")
        id_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        id_label.setFixedWidth(135)
        id_row.addWidget(id_label)
        id_value = QLabel(self.registry_id)
        id_value.setStyleSheet(f"color: {colors.TEXT_MENU};")
        id_value.setWordWrap(False)
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

        # Status badge - check if member has signed the registry
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
            "The registry is ready to sign. Click the button below to sign the registry "
            "creation event and notify other members."
        )
        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;")
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Sign button
        sign_btn_layout = QHBoxLayout()
        self.sign_btn = LocksmithButton("Sign Registry")
        self.sign_btn.setFixedWidth(200)
        self.sign_btn.clicked.connect(self._on_sign_clicked)
        sign_btn_layout.addWidget(self.sign_btn)
        sign_btn_layout.addStretch()

        self.content_layout.addLayout(sign_btn_layout)

    def _add_signed_message(self):
        """Add message indicating user has already signed."""
        success = QLabel("✓ You have signed this registry.")
        success.setStyleSheet(f"font-size: 13px; color: #065f46; font-weight: 600;")
        self.content_layout.addWidget(success)

    def _get_current_account_aid(self) -> str:
        """Get the current user's Castellan account AID."""
        if not self.app or not self.app.vault:
            return ""

        account = self.app.vault.plugin_state.get("castellan", {}).get("account", {})
        return account.get("aid", "")

    @qasync.asyncSlot()
    async def _on_sign_clicked(self):
        """Handle Sign button click - sign the registry IXN event."""
        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Signing...")

        multisig_id = self.identifier.get('id')

        try:
            # Get the hab for this identifier
            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            current_event = self.identifier.get("current_event")
            current_tel_event = self.identifier.get("current_tel_event")
            current_metadata = self.identifier.get('current_metadata', {})
            registry_name = current_metadata.get('registry_name', 'Unknown')

            # Sign all the events required
            vcp_serder = serdering.SerderKERI(sad=current_tel_event)
            anc = serdering.SerderKERI(sad=current_event)
            siger = hab.sign(ser=anc.raw, indexed=True).pop()
            mbx = serdering.SerderKERI(sad=self.identifier.get("mbx"))
            mbx_siger = hab.sign(ser=mbx.raw, indexed=True).pop()
            rgr = serdering.SerderKERI(sad=self.identifier.get("rgr"))
            rgr_siger = hab.sign(ser=rgr.raw, indexed=True).pop()

            members = self.identifier.get("members")
            my_idx = hab.smids.index(hab.mhab.pre)
            member_idxs = [my_idx]
            sigers = [siger]
            mbx_sigers = [mbx_siger]
            rgr_sigers = [rgr_siger]

            for member in members:
                if member.get("current_signature"):
                    sigers.append(Siger(qb64=member.get("current_signature")))
                    mbx_sigers.append(Siger(qb64=member.get("mbx_signature")))
                    rgr_sigers.append(Siger(qb64=member.get("rgr_signature")))
                    member_idxs.append(hab.smids.index(member.get("member_aid")))

            tholder = hab.kever.tholder

            # If all participants are enough to create the rotation event, do so, otherwise create without parsing
            if tholder.satisfy(member_idxs):
                self._awaiting_auth = True

                couple = Seqner(sn=anc.sn).qb64b + Saider(qb64=anc.said).qb64b

                vcp = bytearray(vcp_serder.raw)
                vcp.extend(
                    core.Counter(
                        core.Codens.SealSourceCouples, count=1, gvrsn=kering.Vrsn_1_0
                    ).qb64b
                )
                vcp.extend(couple)

                seal = SealEvent(
                    i=anc.pre, s="{:x}".format(anc.sn), d=anc.said
                )

                mailbox = messagize(
                    mbx,
                    sigers=mbx_sigers,
                    seal=seal,
                )
                registrar = messagize(
                    rgr,
                    sigers=rgr_sigers,
                    seal=seal,
                )

                try:
                    hab.kvy.processEvent(serder=anc, sigers=sigers)
                    reg = self.app.vault.rgy.makeRegistry(name=registry_name, prefix=hab.pre, vcp=vcp_serder)
                    seqner = coring.Seqner(sn=hab.kever.sn)
                    reg.anchorMsg(pre=reg.regk,
                                     regd=reg.regd,
                                     seqner=seqner,
                                     saider=coring.Saider(qb64=hab.kever.serder.said))
                    reg.tvy.processEscrows()

                    hab.psr.parse(ims=bytearray(mailbox), local=True)
                    hab.psr.parse(ims=bytearray(registrar), local=True)

                except Exception as ex:
                    logger.exception(f"Unable to complete registrar parsing: {ex}")
                    self.show_error(f"Unable to parse anchor, mailbox or registrar to valid event despite enough signatures")
                    return

                self.ixn_said = anc.said
                self.ixn_siger = siger
                self.mailbox_said = mbx.said
                self.mailbox_siger = mbx_siger
                self.registrar_said = rgr.said
                self.registrar_siger = rgr_siger

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

            # Upload to server
            result = await remoting.add_multisig_registry_signature(
                app=self.app,
                multisig_id=multisig_id,
                ixn_said=anc.said,
                ixn_siger=siger,
                mailbox_said=mbx.said,
                mailbox_siger=mbx_siger,
                registrar_said=rgr.said,
                registrar_siger=rgr_siger
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to create registry: {error_msg}")
                return

            self._finished()

        except Exception as e:
            logger.exception(f"Error signing registry: {e}")
            self.show_error(f"Error signing registry: {str(e)}")

        finally:
            # Restore button state
            self.sign_btn.setEnabled(True)
            self.sign_btn.setText("Sign Registry")

    @qasync.asyncSlot(str, str, dict)
    async def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """Handle doer events from role setting and ResolveOobiDoer."""
        # Handle OOBI resolution events

        if doer_name == "AuthenticateWitnessesDoer":
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

            try:
                hab = self.app.vault.hby.habs.get(self.aid)
                multisig_id = self.identifier.get('id')

                wigers = []
                dgkey = dbing.dgKey(hab.pre, self.ixn_said)  # get message
                if wigs := hab.db.getWigs(key=dgkey):
                    for wig in wigs:
                        wigers.append(Siger(qb64b=bytes(wig)).qb64)


                # Upload to server
                result = await remoting.add_multisig_registry_signature(
                    app=self.app,
                    multisig_id=multisig_id,
                    ixn_said=self.ixn_said,
                    ixn_siger=self.ixn_siger,
                    mailbox_said=self.mailbox_said,
                    mailbox_siger=self.mailbox_siger,
                    registrar_said=self.registrar_said,
                    registrar_siger=self.registrar_siger,
                    witness_receipts=wigers
                )

                if not result.get('success'):
                    error_msg = result.get('error', 'Unknown error')
                    self.show_error(f"Failed to create registry: {error_msg}")
                    return

            except Exception as e:
                logger.exception(f"Error signing registry: {e}")
                self.show_error(f"Error signing registry: {str(e)}")

            finally:
                # Restore button state
                self.sign_btn.setEnabled(True)
                self.sign_btn.setText("Sign Registry")
