# -*- encoding: utf-8 -*-
"""
whisper.init.poller module

UploadedIdentifierPoller — hio Doer that periodically fetches the list of
identifiers uploaded to weirwood and emits a Qt signal when the list changes.

Used by WhisperSetupPage section 2 to detect when peers have joined so the
"Continue to Group Setup" button can be enabled.  Also triggers automatic OOBI
resolution for newly-seen identifiers so they are in hby.kevers by section 3.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import QObject, Signal
from hio.base import doing

from ..core import remoting

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
    (new additions detected by comparing AIDs).  Automatically resolves OOBIs
    for newly-seen identifiers so hby.kevers is populated before group creation.

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

    def recur(self, tyme):
        self._poll()
        return False   # keep running

    @qasync.asyncSlot()
    async def _poll(self):
        result = await remoting.fetch_identifiers(self.app)
        if not result.get("success"):
            return

        identifiers = result.get("identifiers", [])
        current_aids = {i["aid"] for i in identifiers}

        new_aids = current_aids - self._known_aids
        if new_aids:
            # Resolve OOBIs for newly-seen identifiers
            for identifier in identifiers:
                logger.info("HER")
                logger.info(identifier)
                if identifier["aid"] in new_aids and identifier.get("oobi"):
                    asyncio.get_event_loop().create_task(
                        self._resolve_oobi(identifier["aid"], identifier["oobi"])
                    )

            self._known_aids = current_aids
            self.signals.identifiers_changed.emit(identifiers)

    async def _resolve_oobi(self, aid: str, oobi: str):
        """Resolve an OOBI so the identifier appears in hby.kevers."""
        try:
            hby = self.app.vault.hby
            if aid not in hby.kevers:
                logger.info(f"Resolving OOBI for peer {aid[:16]}...")
                await hby.oobiery.resolve(oobi=oobi)
        except Exception as e:
            logger.warning(f"OOBI resolution failed for {aid[:16]}...: {e}")
