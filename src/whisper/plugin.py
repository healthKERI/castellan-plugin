# -*- encoding: utf-8 -*-
"""
whisper.plugin module

WhisperPlugin — the reference Locksmith plugin implementation.
Registers Whisper page(s), menus, and lifecycle hooks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget
from keri import help

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
            (":/assets/material-icons/passport.svg", "Initialization", "whisper_setup"),
            (":/assets/material-icons/settings.svg", "Settings", "whisper_settings"),
            (":/assets/material-icons/out-badge.svg", "Issued Credentials", "whisper_issued_credentials"),
            (":/assets/material-icons/in-badge.svg", "Received Credentials", "whisper_received_credentials"),
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
        from .init.doers import WeirwoodMessagePoller
        self._identifier_poller = UploadedIdentifierPoller(self._app)
        self._message_poller = WeirwoodMessagePoller(
            self._app,
            exc=vault.plugin_state["whisper"]["exc"],
        )
        vault.extend([self._identifier_poller, self._message_poller])

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
                from .init.accept_group import AcceptGroupProposalDialog
                dialog = AcceptGroupProposalDialog(
                    app=self._app,
                    parent=vault_page,
                    proposal_said=said,
                )
                dialog.open()
            elif "/multisig/vcp" in route:
                from .init.accept_registry import AcceptRegistryProposalDialog
                dialog = AcceptRegistryProposalDialog(
                    app=self._app,
                    parent=vault_page,
                    proposal_said=said,
                )
                dialog.open()
        except Exception:
            logger.exception("Error handling new notification in WhisperPlugin")

    def _on_vault_doer_event(self, doer_name: str, event_type: str, data: dict) -> None:
        """Handle vault-level doer events relevant to the whisper plugin."""
        if doer_name == "TeamCreationPage" and event_type == "hk_team_created":
            logger.info("WhisperPlugin: healthKERI account created — syncing to whisper state")
            sync_account_to_whisper(self._app)
            self.resetEssr(self._app.vault)

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
