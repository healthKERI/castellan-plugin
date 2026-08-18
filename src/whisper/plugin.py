# -*- encoding: utf-8 -*-
"""
whisper.plugin module

WhisperPlugin — the reference Locksmith plugin implementation.
Registers Whisper page(s), menus, and lifecycle hooks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget
from keri import help
from keri.app.grouping import MultisigNotificationHandler

from locksmith.core.essring import APIClient
from locksmith.plugins.base import (
    PluginBase,
    AccountProviderPlugin,
)
from locksmith.ui.vault.menu import MenuButton
from locksmith.ui.toolkit.widgets.buttons import BackButton, LocksmithButton

from keri.peer import exchanging as keri_exchanging
from keri.app import grouping as keri_grouping

from .db.basing import WhisperBaser, sync_account_to_whisper

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.core.vaulting import Vault
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class WhisperPlugin(
    PluginBase,
    AccountProviderPlugin,
):
    """Reference Locksmith plugin for whisper platform integration."""

    @property
    def plugin_id(self) -> str:
        return "whisper"

    def initialize(self, app: "LocksmithApplication", parent) -> None:
        self._app = app
        self.parent = parent
        self._db: WhisperBaser | None = None
        self._pages: dict[str, QWidget] = {}
        self._build_pages(app)
        self._build_menu()
        self._open_group_dialog_gid: str | None = None
        self._open_registry_dialog_gid: str | None = None

    def _build_pages(self, app: "LocksmithApplication") -> None:
        """Instantiate all Whisper page widgets."""
        from .credentials.issued.list import IssuedCredentialsListPage
        from .credentials.received.list import ReceivedCredentialsListPage
        from .init.setup import WhisperSetupPage
        from .settings import WhisperSettingsPage

        self._pages = {
            "whisper_issued_credentials": IssuedCredentialsListPage(app, self.parent),
            "whisper_received_credentials": ReceivedCredentialsListPage(app, self.parent),
            "whisper_placeholder": WhisperPlaceholderPage("Whisper", self.parent),
            "whisper_setup": WhisperSetupPage(app, self.parent),
            "whisper_settings": WhisperSettingsPage(app, self.parent),
        }

    def _navigate(self, page_key: str) -> None:
        vault_page = self._get_vault_page()
        if vault_page:
            vault_page._show_page(page_key)

    def _get_vault_page(self):
        if hasattr(self._app, '_vault_page'):
            return self._app._vault_page
        return None

    # -------------------------------------------------------------------------
    # Menu
    # -------------------------------------------------------------------------

    def _build_menu(self) -> None:
        self._account_button = MenuButton(
            QIcon(":/assets/custom/logos/full-color-owl-only.png"),
            "Whisper Credentials"
        )
        self._account_button.is_account_btn = True
        self._whisper_submenu_items = self._create_submenu_items()

    def _create_submenu_items(self) -> list[QWidget]:
        items = []

        back_button = BackButton(dark_mode=False)
        items.append(back_button)

        publish_all_btn = self._create_publish_all_button()
        items.append(publish_all_btn)

        from locksmith.ui.vault.menu import MenuSpacer
        items.append(MenuSpacer(15))

        nav_buttons_config = [
            (":/assets/material-icons/out-badge.svg", "Issued Credentials", "whisper_issued_credentials"),
            (":/assets/material-icons/in-badge.svg", "Received Credentials", "whisper_received_credentials"),
            (":/assets/material-icons/passport.svg", "Initialization", "whisper_setup"),
            (":/assets/material-icons/settings-hover.svg", "Settings", "whisper_settings"),
        ]

        self._nav_buttons_by_page = {}
        for icon_path, label, page_key in nav_buttons_config:
            btn = MenuButton(QIcon(icon_path), label)
            btn.clicked.connect(self._make_nav_handler(page_key, btn))
            items.append(btn)
            self._nav_buttons_by_page[page_key] = btn

        return items

    def _create_publish_all_button(self) -> LocksmithButton:
        btn = LocksmithButton("Publish All")
        btn.clicked.connect(self._on_publish_all_clicked)
        return btn

    def _on_publish_all_clicked(self):
        from .credentials.publish_all import PublishAllConfirmationDialog
        dialog = PublishAllConfirmationDialog(
            app=self._app,
            on_refresh=self._refresh_credential_pages,
            parent=self._get_vault_page(),
        )
        dialog.open()

    def _refresh_credential_pages(self):
        for key in ("whisper_issued_credentials", "whisper_received_credentials"):
            page = self._pages.get(key)
            if page and hasattr(page, "_refresh_table"):
                page._refresh_table()

    def _make_nav_handler(self, page_key: str, button: MenuButton):
        def handler():
            for item in self._whisper_submenu_items:
                if isinstance(item, MenuButton):
                    item.set_active(False)
            button.set_active(True)
            self._navigate(page_key)
            page = self._pages.get(page_key)
            if page and hasattr(page, "on_show"):
                page.on_show()
        return handler

    # -------------------------------------------------------------------------
    # PluginBase lifecycle
    # -------------------------------------------------------------------------

    def on_vault_opened(self, vault: "Vault") -> None:
        self._db = WhisperBaser(name=vault.hby.name, reopen=True)

        _, account = next(self._db.whisperAccounts.getItemIter(), (None, None))
        _, team = next(self._db.whisperTeams.getItemIter(), (None, None))

        whisper_cfg = self._app.config.plugin_configs.get("whisper", {})
        weirwood_aid = whisper_cfg.get("weirwood_aid", "")
        weirwood_oobi = whisper_cfg.get("weirwood_oobi", "")
        weirwood_url = whisper_cfg.get("weirwood_url", "http://localhost:5922")

        # Resolve weirwood0 OOBI so the vault habery has its keystate for ESSR encryption.
        if weirwood_aid and weirwood_oobi:
            if not vault.hby.db.roobi.get(keys=(weirwood_oobi,)):
                from locksmith.core.remoting import resolve_oobi_sync
                resolve_oobi_sync(
                    app=self._app,
                    pre=weirwood_aid,
                    oobi=weirwood_oobi,
                    alias="weirwood",
                )

        essr = None
        if account is not None:
            hab = vault.hby.habs.get(account.aid)
            if hab is not None:
                essr = APIClient(
                    url=weirwood_url,
                    root=weirwood_aid,
                    hby=vault.hby,
                    hab=hab
                )

        whisper_exc = keri_exchanging.Exchanger(hby=vault.hby, handlers=[])
        keri_grouping.loadHandlers(exc=whisper_exc, mux=vault.mux)

        vault.plugin_state["whisper"] = {
            "account": account,
            "team": team,
            "essr": essr,
            "db": self._db,
            "exc": whisper_exc,
        }

        if hasattr(vault, 'signals') and vault.signals:
            # Listen for healthKERI account creation so whisper state stays current.
            vault.signals.doer_event.connect(self._on_vault_doer_event)
            # Intercept multisig notifications delivered via WeirwoodMessagePoller.
            if hasattr(vault.signals, 'new_notification'):
                vault.signals.new_notification.connect(self._on_new_notification)

        # Register background doers for weirwood polling.
        from .init.poller import UploadedIdentifierPoller
        from .init.doers import WeirwoodMessagePoller, WeirwoodBackerFetchDoer
        self._identifier_poller = UploadedIdentifierPoller(self._app)
        self._message_poller = WeirwoodMessagePoller(
            self._app,
            exc=vault.plugin_state["whisper"]["exc"],
        )
        self._backer_fetch_doer = WeirwoodBackerFetchDoer(self._app)

        vault.extend([self._identifier_poller, self._message_poller, self._backer_fetch_doer])

        self._identifier_poller.signals.initial_load_complete.connect(
            self._message_poller.mark_kel_load_ready
        )

        _init_state = self._db.whisperInitState.get(keys=("init",))
        if (
                _init_state is not None
                and _init_state.init_step == 3
                and _init_state.group_identifier_alias
        ):
            from keri.app.habbing import GroupHab as _GroupHab
            from keri.core import coring as _kc
            from .init.doers import WhisperCounselingCompletionDoer

            for (pre,), (seqner, _saider) in vault.hby.db.gpse.getItemIter():
                _hab = vault.hby.habByPre(pre)
                if (
                        _hab is not None
                        and isinstance(_hab, _GroupHab)
                        and _hab.name == _init_state.group_identifier_alias
                ):
                    _completion_doer = WhisperCounselingCompletionDoer(
                        app=self._app,
                        prefixer=_kc.Prefixer(qb64=pre),
                        seqner=seqner,
                        ghab=_hab,
                        is_proposer=_init_state.is_proposer,
                    )
                    vault.extend([_completion_doer])
                    logger.info(
                        f"Whisper: resuming group counseling for '{_hab.name}' "
                        f"({'proposer' if _init_state.is_proposer else 'joiner'})"
                    )
                    break

        if (
                _init_state is not None
                and _init_state.init_step >= 4
                and not _init_state.init_complete
                and not _init_state.is_proposer
                and _init_state.group_identifier_alias
        ):
            _registry_name = f"{_init_state.group_identifier_alias}-registry"
            _registry = vault.rgy.registryByName(_registry_name)
            if _registry is not None:
                from keri.vdr import credentialing as _vdr
                _reg_check = _vdr.Registrar(hby=vault.hby, rgy=vault.rgy, counselor=vault.counselor)
                if not _reg_check.complete(pre=_registry.regk, sn=0):
                    from .init.doers import WhisperRegistryAcceptCompletionDoer
                    _reg_doer = WhisperRegistryAcceptCompletionDoer(
                        app=self._app,
                        registry=_registry,
                        signal_bridge=vault.signals,
                    )
                    vault.extend([_reg_doer])
                    logger.info(
                        f"Whisper: resuming registry acceptance for "
                        f"'{_init_state.group_identifier_alias}' (joiner)"
                    )

    def on_vault_closed(self, vault: "Vault") -> None:
        if hasattr(vault, 'signals') and vault.signals:
            try:
                vault.signals.doer_event.disconnect(self._on_vault_doer_event)
            except (RuntimeError, TypeError):
                pass
            if hasattr(vault.signals, 'new_notification'):
                try:
                    vault.signals.new_notification.disconnect(self._on_new_notification)
                except (RuntimeError, TypeError):
                    pass

        self._open_group_dialog_gid = None
        self._open_registry_dialog_gid = None
        vault.plugin_state.pop("whisper", None)

        if self._db:
            self._db.close()
            self._db = None

    def _on_new_notification(self, notification: dict) -> None:
        """Intercept vault notifications and open the appropriate whisper dialog."""
        try:
            route = notification.get("r", "")
            said = notification.get("d", "")
            if not said:
                return
            vault_page = self._get_vault_page()
            if vault_page is None:
                return
            if "/multisig/icp" in route:
                # Distinguish a new invitation (group hab doesn't exist yet) from a
                # co-signer response to our own proposal (group hab already exists).
                _is_response = False
                _exn = self._app.vault.hby.db.exns.get(keys=(said,))
                _gid = ""

                if _exn is not None:
                    _icp_sad = _exn.ked.get("e", {}).get("icp", {})
                    _gid = _icp_sad.get("i", "") if isinstance(_icp_sad, dict) else ""
                    if _gid and self._app.vault.hby.habs.get(_gid) is not None:
                        _is_response = True
                        _sender = _exn.ked.get("i", "")
                        if _sender:
                            self._app.vault.plugin_state.setdefault("whisper", {}).setdefault(
                                "group_join_tracker", set()
                            ).add(_sender)
                            # Persist signer to state
                            _db = self._app.vault.plugin_state.get("whisper", {}).get("db")
                            if _db is not None:
                                _ws = _db.whisperInitState.get(keys=("init",))
                                if _ws is not None and _sender not in _ws.group_signed_aids:
                                    _ws.group_signed_aids.append(_sender)
                                    _db.whisperInitState.pin(keys=("init",), val=_ws)
                            # Notify setup page
                            if self._app.vault.signals:
                                self._app.vault.signals.emit_doer_event(
                                    "WhisperGroupMultisigInceptDoer", "group_participant_signed",
                                    {"signer_aid": _sender}
                                )
                if not _is_response:
                    if not _gid or self._open_group_dialog_gid == _gid:
                        return
                    multisig_alias = notification.get("multisig_alias", "")
                    from .init.accept_group import AcceptGroupProposalDialog
                    dialog = AcceptGroupProposalDialog(
                        app=self._app, parent=vault_page, proposal_said=said,
                        multisig_alias=multisig_alias,
                    )
                    self._open_group_dialog_gid = _gid
                    def _clear_group_dialog():
                        self._open_group_dialog_gid = None
                    dialog.finished.connect(_clear_group_dialog)
                    dialog.open()
            elif "/multisig/vcp" in route:

                _is_response = False
                _exn = self._app.vault.hby.db.exns.get(keys=(said,))
                _gid = ""

                if _exn is not None:
                    _gid = _exn.ked.get("a", {}).get("gid", "")
                    if _gid:
                        _ghab = self._app.vault.hby.habs.get(_gid)
                        if _ghab is not None:
                            _reg_name = f"{_ghab.name}-registry"
                            if self._app.vault.rgy.registryByName(_reg_name) is not None:
                                _is_response = True
                                _sender = _exn.ked.get("i", "")
                                if _sender:
                                    self._app.vault.plugin_state.setdefault("whisper", {}).setdefault(
                                        "registry_sign_tracker", set()
                                    ).add(_sender)
                                    _db = self._app.vault.plugin_state.get("whisper", {}).get("db")
                                    if _db is not None:
                                        _ws = _db.whisperInitState.get(keys=("init",))
                                        if _ws is not None and _sender not in _ws.registry_signed_aids:
                                            _ws.registry_signed_aids.append(_sender)
                                            _db.whisperInitState.pin(keys=("init",), val=_ws)
                                    if self._app.vault.signals:
                                        self._app.vault.signals.emit_doer_event(
                                            "CreateRegistryDoer", "registry_participant_signed",
                                            {"signer_aid": _sender}
                                        )
                if not _is_response:
                    if not _gid or self._open_registry_dialog_gid == _gid:
                        return
                    from .init.accept_registry import AcceptRegistryProposalDialog
                    dialog = AcceptRegistryProposalDialog(
                        app=self._app, parent=vault_page, proposal_said=said,
                    )
                    self._open_registry_dialog_gid = _gid

                    def _clear_registry_dialog():
                        self._open_registry_dialog_gid = None

                    dialog.finished.connect(_clear_registry_dialog)
                    dialog.open()
        except Exception:
            logger.exception("Error handling new notification in WhisperPlugin")

    def _on_vault_doer_event(self, doer_name: str, event_type: str, data: dict) -> None:
        """Handle vault-level doer events relevant to the whisper plugin."""
        if doer_name == "TeamCreationPage" and event_type == "hk_team_created":
            logger.info("WhisperPlugin: healthKERI account created — syncing to whisper state")
            sync_account_to_whisper(self._app)
            self.resetEssr(self._app.vault)

    def get_multisig_dialog(self, app: Any, parent: Any, proposal_said: str, route: str) -> "QWidget | None":
        """Return a whisper-aware dialog for a multisig proposal notification.

        Only handles proposals where the local whisper chosen identifier is a
        signing member.  Returns None to fall through to base locksmith dialog.
        """
        try:
            db: "WhisperBaser | None" = app.vault.plugin_state.get("whisper", {}).get("db")
            if db is None:
                return None
            state = db.whisperInitState.get(keys=("init",))
            if state is None or not state.chosen_identifier_aid:
                return None

            hby = app.vault.hby
            chosen_hab = None
            for _, hab in hby.habs.items():
                if not hasattr(hab, "mhab") and hab.pre == state.chosen_identifier_aid:
                    chosen_hab = hab
                    break
            if chosen_hab is None:
                return None

            exn, pathed = keri_exchanging.cloneMessage(hby, proposal_said)
            if exn is None:
                return None

            if "/multisig/icp" in route:
                smids = exn.ked.get("a", {}).get("smids", [])
                if state.chosen_identifier_aid not in smids:
                    return None
                from .init.accept_group import AcceptGroupProposalDialog
                multisig_alias = app.vault.plugin_state.get("whisper", {}).get(
                    "proposed_group_alias", ""
                )
                return AcceptGroupProposalDialog(
                    app=app,
                    parent=parent,
                    proposal_said=proposal_said,
                    multisig_alias=multisig_alias,
                )
            elif "/multisig/vcp" in route:
                gid = exn.ked.get("a", {}).get("gid", "")
                smids = list(hby.db.signingMembers(pre=gid))
                if state.chosen_identifier_aid not in smids:
                    return None
                from .init.accept_registry import AcceptRegistryProposalDialog
                return AcceptRegistryProposalDialog(
                    app=app,
                    parent=parent,
                    proposal_said=proposal_said,
                )
            # TODO: add whisper-aware dialogs for /multisig/rot, /multisig/ixn, etc.
        except Exception:
            logger.exception("WhisperPlugin.get_multisig_dialog failed")
        return None

    def get_menu_entry(self) -> MenuButton:
        return self._account_button

    def get_menu_section(self) -> list[QWidget]:
        return self._whisper_submenu_items

    def get_pages(self) -> dict[str, QWidget]:
        return self._pages

    # -------------------------------------------------------------------------
    # AccountProviderPlugin
    # -------------------------------------------------------------------------

    def is_setup_complete(self, vault: "Vault") -> bool:
        db: WhisperBaser | None = vault.plugin_state.get("whisper", {}).get("db")
        if db is None or db.whisperInitState is None:
            return False
        init_state = db.whisperInitState.get(keys=("init",))
        return init_state is not None and init_state.init_complete

    def get_setup_page(self, vault: "Vault") -> tuple[str, bool]:
        if self.is_setup_complete(vault):
            return ("whisper_issued_credentials", True)
        else:
            return ("whisper_setup", False)


    # -------------------------------------------------------------------------
    # ESSR management
    # -------------------------------------------------------------------------

    def resetEssr(self, vault: "Vault") -> None:
        """Reset ESSR client with current account hab."""
        state = vault.plugin_state.get("whisper", {})
        account = state.get("account")
        if account is None:
            logger.warning("Cannot reset ESSR: no hkAccount configured")
            return
        hab = vault.hby.habs.get(account.aid)
        if hab is None:
            logger.warning(f"Cannot reset ESSR: hab not found for aid {account.aid}")
            return
        whisper_cfg = self._app.config.plugin_configs.get("whisper", {})
        state["essr"] = APIClient(
            url=whisper_cfg.get("weirwood_url", "http://localhost:5922"),
            root=whisper_cfg.get("weirwood_aid", ""),
            hby=vault.hby,
            hab=hab
        )


class WhisperPlaceholderPage(QWidget):
    """Placeholder page for Whisper sub-pages (to be implemented later)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.vault_name = None

        from PySide6.QtWidgets import QVBoxLayout, QLabel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        layout.addWidget(title_label)

        placeholder_label = QLabel("This plugin currently requires a healthKERI account.")
        placeholder_label.setStyleSheet("font-size: 14px; color: #666;")
        layout.addWidget(placeholder_label)

        layout.addStretch()

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name
