# -*- encoding: utf-8 -*-
"""
whisper.init.poller module

UploadedIdentifierPoller — hio Doer that periodically fetches the list of
identifiers uploaded to weirwood and emits a Qt signal when the list changes.

Used by WhisperSetupPage section 2 to detect when peers have joined so the
"Continue to Group Setup" button can be enabled.  Also fetches and parses the
KEL for newly-seen identifiers so they appear in vault.kvy.kevers by section 3.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import QObject, Signal
from hio.base import doing
from keri.help import helping

from ..core import remoting
from keri.core import parsing

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

from keri import help

logger = help.ogler.getLogger(__name__)

_POLLER_TOCK = 10.0   # seconds between polls


class _PollerSignals(QObject):
    """Qt signals carrier for UploadedIdentifierPoller."""
    identifiers_changed = Signal(list)   # emitted with list of {aid, alias, oobi} dicts


class UploadedIdentifierPoller(doing.Doer):
    """
    Background Doer that polls weirwood /identifiers every 10 seconds.

    Emits ``signals.identifiers_changed`` when the identifier list changes
    (new additions detected by comparing AIDs).  Fetches and parses the CESR
    KEL for newly-seen identifiers so they appear in vault.kvy.kevers before
    group creation (replacing OOBI resolution which fails in closed networks).

    Usage:
        poller = UploadedIdentifierPoller(app)
        app.vault.extend([poller])
        poller.signals.identifiers_changed.connect(my_slot)
    """

    def __init__(self, app: "LocksmithApplication"):
        self.app = app
        self.signals = _PollerSignals()
        self._known_aids: set[str] = set()
        super().__init__(tock=_POLLER_TOCK)
        logger.info(f"UploadedIdentifierPoller initialized with tock={_POLLER_TOCK}s")

    def recur(self, tyme):
        self._poll()
        return False   # keep running

    @qasync.asyncSlot()
    async def _poll(self):
        result = await remoting.fetch_identifiers(self.app)
        if not result.get("success"):
            logger.warning(f"UploadedIdentifierPoller: fetch_identifiers failed: {result.get('error', 'unknown error')}")
            return

        identifiers = result.get("identifiers", [])
        current_aids = {i["aid"] for i in identifiers}

        new_aids = current_aids - self._known_aids
        if new_aids:
            logger.info(f"UploadedIdentifierPoller: {len(new_aids)} new identifier(s) detected: {[a[:16] + '...' for a in new_aids]}")
            # Emit immediately so UI peer count updates without waiting for KEL fetch.
            self._known_aids = current_aids
            self.signals.identifiers_changed.emit(identifiers)
            logger.info("UploadedIdentifierPoller: identifiers_changed signal emitted")

            # Build aid -> alias lookup from the full identifier dicts.
            alias_by_aid = {i["aid"]: i.get("alias", i["aid"]) for i in identifiers}

            # Fetch and parse KEL for each newly-seen identifier in the background.
            for aid in new_aids:
                logger.info(f"UploadedIdentifierPoller: scheduling KEL fetch task for {aid[:16]}...")
                asyncio.get_event_loop().create_task(
                    self._fetch_and_parse_kel(aid, alias_by_aid.get(aid) or aid)
                )
        else:
            pass

    async def _fetch_and_parse_kel(self, aid: str, alias: str):
        """
        Fetch the CESR KEL for a peer from weirwood and parse it into the
        vault's Kevery so the peer appears in vault.kvy.kevers before group
        inception requires their keystate.
        """
        logger.info(f"_fetch_and_parse_kel: starting for {aid[:16]}... (alias={alias})")
        if not self.app.vault:
            logger.warning(f"_fetch_and_parse_kel: vault is not available, skipping {aid[:16]}...")
            return
        if aid in self.app.vault.kvy.kevers:
            logger.info(f"_fetch_and_parse_kel: {aid[:16]}... already in kevers, skipping")
            return  # already known

        try:
            result = await remoting.fetch_identifier_kel(self.app, aid)
            if not result.get("success"):
                logger.warning(f"KEL fetch failed for {aid[:16]}...: {result.get('error')}")
                return

            kel_bytes = result.get("kel_bytes", b"")
            if not kel_bytes:
                logger.warning(f"Empty KEL returned for {aid[:16]}...")
                return

            logger.info(f"_fetch_and_parse_kel: received {len(kel_bytes)} bytes of KEL for {aid[:16]}...")
            ims = bytearray(kel_bytes)
            parsing.Parser(kvy=self.app.vault.hby.kvy, rvy=self.app.vault.hby.rvy, local=False).parse(ims)
            self.app.vault.hby.kvy.processEscrows()
            logger.info(f"_fetch_and_parse_kel: KEL parsed and escrows processed for {aid[:16]}...")

            remoteId = {
                'alias': alias,
                'last-refresh': helping.nowIso8601()
            }

            self.app.vault.org.update(aid, remoteId)
            if self.app.vault.signals:
                self.app.vault.signals.emit_doer_event(
                    doer_name="ImportDoer",
                    event_type="remote_identifier_imported",
                    data={
                        'alias': alias,
                        'pre': aid,
                        'success': True
                    }
                )
                logger.info(f"_fetch_and_parse_kel: remote_identifier_imported signal emitted for {aid[:16]}...")
            else:
                logger.warning(f"_fetch_and_parse_kel: vault.signals is not available, could not emit event for {aid[:16]}...")
            logger.info(f"KEL parsed for peer {aid[:16]}…")
        except Exception as e:
            logger.warning(f"KEL parse failed for {aid[:16]}...: {e}")
