# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.revoke module

Dialog for confirming and revoking an issued credential, and automatically
syncing the revocation (and any resulting key state change) to the Castellan
server once the local TEL revocation completes.

For multisig issuers, after confirmation this dialog initiates the revocation
on the server and opens the ViewCredentialRevocationDialog for signature collection.
"""
import asyncio
from collections.abc import Callable

from keri import help, core, kering
from keri.core import eventing, coring, serdering
from keri.db.dbing import dgKey, snKey
from keri.vdr import eventing as veventing
from locksmith.core.credentialing import RevokeCredentialDoer
from locksmith.ui.toolkit.widgets.dialogs import LocksmithResourceDeletionDialog
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog
from PySide6.QtWidgets import QLabel

from ...core import remoting, identifying

logger = help.ogler.getLogger(__name__)


class RevokeIssuedCredentialDialog(LocksmithResourceDeletionDialog):
    """Dialog for confirming and revoking an issued credential.

    Once the local TEL revocation completes, the revocation status (and any
    resulting key state advancement) is automatically pushed to the
    Castellan server - the user is not routed through a separate
    confirmation dialog for that step.
    """

    def __init__(
        self,
        app,
        schema_name: str,
        said: str,
        on_success: Callable[[str], None] | None = None,
        parent = None,
    ):
        """Initialize the RevokeIssuedCredentialDialog.

        Args:
            app: The LocksmithApplication instance
            schema_name: Name/title of the credential schema (for confirmation)
            said: SAID of the credential to revoke
            on_success: Callback to invoke once the revocation has been synced
                to (or the sync has failed against) the Castellan server
            parent: Parent widget (VaultPage container)
        """
        self.app = app
        self.schema_name = schema_name
        self.said = said
        self.on_success = on_success
        self._awaiting_auth = False  # Guard: only handle auth_codes_entered when we initiated auth
        self.issuer_pre = None
        self.issuer_name = None

        super().__init__(
            parent=parent,
            resource_type="issued credential",
            resource_name=schema_name if schema_name else said,
            title_icon=":/assets/material-icons/remove_moderator.svg",
            action_verb="Revoke",
        )

        note = QLabel(
            "Revoking this credential will automatically update its status "
            "on the Castellan server."
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px; color: #6b7280;")
        self.content_layout.addWidget(note)

        # Override the revoke button click to handle credential revocation
        self.delete_button.clicked.disconnect(self.accept)
        self.delete_button.clicked.connect(self._on_revoke)

        # Connect to vault signal bridge for doer events
        if hasattr(self.app.vault, 'signals'):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)
            self.app.vault.signals.auth_codes_entered.connect(self._on_auth_codes_entered)

        logger.info(f"RevokeIssuedCredentialDialog initialized for '{schema_name}' ({said})")

    def _on_revoke(self):
        """Handle the revoke button click, launching witness auth first if needed."""
        self.clear_error()
        self.delete_button.setEnabled(False)
        self.delete_button.setText("Revoking...")

        try:
            creder = self.app.vault.rgy.reger.creds.get(keys=(self.said,))
            if not creder:
                raise Exception(f"Credential {self.said} not found")

            registry = self.app.vault.rgy.regs[creder.regi]
            hab = registry.hab
            self.issuer_pre = hab.pre
            self.issuer_name = hab.name

            # Check if issuer is a multisig identifier
            if self._is_multisig_issuer(hab):
                # Launch multisig revocation flow
                asyncio.ensure_future(self._launch_multisig_revocation())
                return

            # Single-sig revocation flow
            if hab.kever.wits:
                self._awaiting_auth = True
                auth_dialog = WitnessAuthenticationDialog(
                    app=self.app,
                    hab=hab,
                    witness_ids=hab.kever.wits,
                    auth_only=True,
                    signals=self.app.vault.signals,
                    parent=self.parent(),
                )
                auth_dialog.open()
            else:
                self._complete_revocation(codes=None)

        except Exception as e:
            error_msg = f"Failed to revoke credential: {str(e)}"
            logger.exception(error_msg)
            self._reset_revoke_button()
            self.show_error(error_msg)

    def _is_multisig_issuer(self, hab) -> bool:
        """Check if issuer is a multisig identifier (group hab)."""
        return hasattr(hab, 'mhab') and hab.mhab is not None

    async def _launch_multisig_revocation(self):
        """Initiate multisig revocation on server and show signature dialog."""
        try:
            # Fetch the multisig identifier data from server
            result = await remoting.fetch_multisig_identifier_by_aid(
                app=self.app,
                aid=self.issuer_pre,
            )

            if not result.get('success'):
                self._reset_revoke_button()
                self.show_error(f"Could not fetch issuer data: {result.get('error')}")
                return

            identifier = result.get('identifier', {})

            # Check if there's already a pending revocation on this issuer
            state = identifying.get_multisig_state(self.app, identifier)
            if state in ("revocation_created", "revocation_signed"):
                # Revocation already in progress - show the dialog
                self._show_revocation_dialog(identifier, state)
            else:
                # Need to initiate revocation - call server to create revocation events
                creder = self.app.vault.rgy.reger.creds.get(keys=(self.said,))
                registry_pre = creder.regi
                registry = self.app.vault.rgy.regs[registry_pre] if registry_pre in self.app.vault.rgy.regs else None
                if not registry:
                    self._reset_revoke_button()
                    self.show_error(f"Registry not found for credential {self.said}")
                    return
                registry = self.app.vault.rgy.regs[creder.regi]
                hab = registry.hab

                vcser = self.app.vault.rgy.reger.getTel(snKey(pre=self.said, sn=0))
                if vcser is None:
                    raise kering.ValidationError(f"Invalid revoke of {self.said} that has not been issued.")
                ievt = self.app.vault.rgy.reger.getTvt(dgKey(pre=self.said, dig=vcser))
                iserder = serdering.SerderKERI(raw=bytes(ievt))  # Serder(raw=bytes(ievt))
                rev = veventing.revoke(creder.said, registry.regk, dig=iserder.said,)

                # Create registry seal
                regd = rev.said
                rseal = {"i": rev.pre, "s": "1", "d": regd}

                # Create and sign IXN to anchor the VCP
                kever = hab.kever
                serder = eventing.interact(pre=kever.prefixer.qb64,
                                           dig=kever.serder.said,
                                           sn=kever.sner.num + 1,
                                           data=[rseal])

                ixn_sigers = hab.sign(ser=serder.raw)

                # Build ISS attachment (Counter + seal source couple)
                seqner = coring.Seqner(sn=kever.sner.num + 1)
                couple = seqner.qb64b + serder.saidb
                rev_attachment = (
                        core.Counter(core.Codens.SealSourceCouples, count=1, gvrsn=kering.Vrsn_1_0).qb64 +
                        couple.decode('utf-8')
                )

                result = await remoting.initiate_multisig_revocation(
                    app=self.app,
                    rev=rev.sad,
                    rev_attachment=rev_attachment,
                    ixn=serder.sad,
                    ixn_siger=ixn_sigers[0],
                    multisig_id=identifier.get('id'),
                    credential_said=self.said,
                )

                if not result.get('success'):
                    self._reset_revoke_button()
                    self.show_error(f"Could not initiate revocation: {result.get('error')}")
                    return

                # Fetch updated identifier and show dialog
                result = await remoting.fetch_multisig_identifier_by_aid(app=self.app, aid=self.issuer_pre)
                if not result.get('success'):
                    self._reset_revoke_button()
                    self.show_error(f"Could not fetch updated issuer data: {result.get('error')}")
                    return

                identifier = result.get('identifier', {})
                state = identifying.get_multisig_state(self.app, identifier)
                self._show_revocation_dialog(identifier, state)

        except Exception as e:
            logger.exception(f"Error launching multisig revocation: {e}")
            self._reset_revoke_button()
            self.show_error(f"Failed to initiate revocation: {str(e)}")

    def _show_revocation_dialog(self, identifier: dict, state: str):
        """Show the ViewCredentialRevocationDialog and close this dialog."""
        from ...issuers.view_credential_revocation import ViewCredentialRevocationDialog

        identifier['_state'] = state
        dialog = ViewCredentialRevocationDialog(
            app=self.app,
            identifier=identifier,
            credential_said=self.said,
            schema_title=self.schema_name,
            parent=self.parent(),
        )
        dialog.closed.connect(self._on_multisig_revocation_closed)
        dialog.open()

        # Close this confirmation dialog
        self.close()

    def _on_multisig_revocation_closed(self):
        """Handle multisig revocation dialog closed."""
        if self.on_success:
            self.on_success(self.said)

    def _on_auth_codes_entered(self, data: dict):
        """
        Handle auth codes entered from WitnessAuthenticationDialog.

        Args:
            data: Dictionary containing 'codes' key with list of "witness_id:passcode" strings
        """
        if not self._awaiting_auth:
            return
        self._awaiting_auth = False

        codes = data.get('codes', [])
        logger.info(f"Received {len(codes)} auth codes from WitnessAuthenticationDialog")

        self._complete_revocation(codes=codes)

    def _complete_revocation(self, codes=None):
        """Start the RevokeCredentialDoer to perform the actual revocation."""
        logger.info(f"Revoking issued credential '{self.schema_name}' ({self.said})")

        try:
            doer = RevokeCredentialDoer(
                app=self.app,
                credential_said=self.said,
                codes=codes,
                signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
            )
            self.app.vault.extend([doer])

            logger.info(f"RevokeCredentialDoer started for credential {self.said}")

        except Exception as e:
            logger.exception(f"Error creating RevokeCredentialDoer: {e}")
            self._reset_revoke_button()
            self.show_error(f"Failed to start credential revocation: {str(e)}")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        if doer_name != "RevokeCredentialDoer" or data.get('credential_said') != self.said:
            return

        logger.debug(f"RevokeIssuedCredentialDialog received doer_event: {doer_name} - {event_type}")

        if event_type == "credential_revoked":
            logger.info(f"Credential revoked successfully: {self.said}")
            self.delete_button.setText("Syncing with server...")
            asyncio.ensure_future(self._sync_to_castellan())

        elif event_type == "credential_revocation_failed":
            error_msg = data.get('error', 'Unknown error')
            logger.error(f"Credential revocation failed: {error_msg}")
            self._reset_revoke_button()
            self.show_error(f"Failed to revoke credential: {error_msg}")

    async def _sync_to_castellan(self):
        """
        Push the revoked status (and any key state change) to the Castellan server.

        `on_success` is fired exactly once, after this sync attempt finishes
        (successfully or not) - not as soon as the local revocation lands -
        so that a caller refreshing a list row sees the post-sync state
        instead of having to refresh again manually.
        """
        try:
            result = await remoting.update_issued_credential_status(
                app=self.app,
                credential_said=self.said,
                status="revoked",
            )
            if not result.get('success'):
                self._set_revoke_button_final("Revoked locally")
                self.show_error(
                    f"Credential revoked locally, but failed to update the Castellan "
                    f"server: {result.get('error', 'Unknown error')}. It will be "
                    f"flagged as out of sync until retried."
                )
                return

            hab = self.app.vault.hby.habs.get(self.issuer_pre) if self.issuer_pre else None
            if hab:
                local_sn = int(hab.kever.state().s, 16)
                keystate_result = await remoting.fetch_identifier_keystate(
                    app=self.app,
                    identifier_prefix=self.issuer_pre,
                )
                remote_data = keystate_result.get('data') if keystate_result.get('success') else None
                remote_sn = int(remote_data.get('key_state', {}).get('s', 0), 16) if remote_data else -1

                if remote_sn < local_sn:
                    result = await remoting.upload_account_identifier(
                        app=self.app,
                        aid=self.issuer_pre,
                        alias=self.issuer_name,
                    )
                    if not result.get('success'):
                        self._set_revoke_button_final("Revoked locally")
                        self.show_error(
                            f"Credential status synced, but failed to update key "
                            f"state: {result.get('error', 'Unknown error')}"
                        )
                        return

            self._set_revoke_button_final("Revoked")
            self.show_success(f"'{self.schema_name}' revoked and synced to the Castellan server!")

        except Exception as e:
            logger.exception(f"Error syncing revocation to Castellan server: {e}")
            self._set_revoke_button_final("Revoked locally")
            self.show_error(f"Credential revoked locally, but server sync failed: {e}")

        finally:
            if self.on_success:
                self.on_success(self.said)

    def _reset_revoke_button(self):
        """Re-enable the revoke button and restore its label (revocation was not performed)."""
        self.delete_button.setEnabled(True)
        self.delete_button.setText("Revoke")

    def _set_revoke_button_final(self, text: str):
        """Set the revoke button's final label once local revocation has completed.

        The button stays disabled, since the credential has already been revoked
        and re-triggering RevokeCredentialDoer against it would fail.
        """
        self.delete_button.setEnabled(False)
        self.delete_button.setText(text)
