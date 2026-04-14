# -*- encoding: utf-8 -*-
"""
whisper.init.doers module

Background Doers for whisper initialization.  All outbound multisig coordination
uses weirwood /messages instead of the standard KERI Poster/mailbox transport.

Classes:
    WeirwoodMessagePoller       — polls /messages?topic=multisig, pipes into vault parser
    WhisperGroupMultisigInceptDoer — initiates group icp, sends EXN via weirwood
    WhisperMultisigJoinDoer     — participant joins group icp, sends response via weirwood
    CreateRegistryDoer          — creates registry (vcp + group ixn), sends EXN via weirwood
    WhisperRegistryAcceptDoer   — participant co-signs registry ixn, sends response via weirwood
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import qasync
from hio.base import doing
from keri.app import grouping as keri_grouping
from keri.app.habbing import GroupHab
from keri.core import coring, serdering, parsing
from keri.peer import exchanging
from keri.vdr import credentialing as vdr_credentialing

from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

from keri import help

logger = help.ogler.getLogger(__name__)

_TOPIC_MULTISIG = "multisig"
_REGISTRY_POLL_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# WeirwoodMessagePoller
# ---------------------------------------------------------------------------

class WeirwoodMessagePoller(doing.Doer):
    """
    Polls weirwood /messages?topic=multisig and pipes raw CESR bytes into
    the vault parser so the Multiplexor can route them and create notifications.

    Must be registered as a vault doer via app.vault.extend([poller]).
    """

    def __init__(self, app: "LocksmithApplication", exc, tock: float = 10.0):
        self.app = app
        self.exc = exc
        super().__init__(tock=tock)
        logger.info("WeirwoodMessagePoller initialized")

    def recur(self, tyme):
        asyncio.get_event_loop().create_task(self._poll())
        return False

    async def _poll(self):
        db = self.app.vault.plugin_state.get("whisper", {}).get("db")
        state = db.whisperInitState.get(keys=("init",)) if db else None
        whisper_aid = state.chosen_identifier_aid if state else None
        result = await remoting.fetch_messages(
            self.app, aid=whisper_aid, topic=_TOPIC_MULTISIG, unread_only=True
        )
        if not result.get("success"):
            logger.info(f"Failed to fetch messages: {result.get('error', 'Unknown error')}")
            return

        messages = result.get("messages", [])
        if not messages:
            return

        logger.info(f"Successfully fetched {len(messages)} messages")

        self.exc.processEscrow()

        parser = parsing.Parser(
            kvy=self.app.vault.hby.kvy,
            rvy=self.app.vault.hby.rvy,
            exc=self.exc,
            local=False,
        )

        for msg in messages:
            raw_str = msg.get("raw", "")
            if not raw_str:
                continue
            try:
                raw = raw_str.encode("utf-8") if isinstance(raw_str, str) else raw_str
                parser.parse(ims=bytearray(raw), local=False)
                await remoting.mark_message_read(self.app, msg["id"])
            except Exception as e:
                logger.warning(f"Failed to process message {msg.get('id')}: {e}")

        # Drain the dedicated exchanger's cues and emit Qt signals
        # so the plugin UI can react (e.g. open the join dialog).
        self._drain_cues()

    def _drain_cues(self):
        """Convert exchanger cues into new_notification Qt signals."""
        while self.exc.cues:
            cue = self.exc.cues.popleft()
            kin = cue.get("kin")

            if kin == "saved":
                said = cue.get("said", "")
                if not said:
                    continue

                exn = self.app.vault.hby.db.exns.get(keys=(said,))
                if exn is None:
                    logger.warning(f"Cue references exn said={said} but not found in db")
                    continue

                route = exn.ked.get("r", "")
                logger.info(f"Whisper exchanger saved exn: route={route} said={said}")

                signals = getattr(self.app.vault, "signals", None)
                if signals and hasattr(signals, "new_notification"):
                    signals.new_notification.emit({"r": route, "d": said})

            elif kin == "query":
                # The exchanger couldn't find the sender's key state.
                # Log it; a future poll cycle will retry after escrow processing.
                q = cue.get("q", {})
                logger.info(f"Whisper exchanger needs key state query: {q}")

            else:
                logger.debug(f"Whisper exchanger cue ignored: kin={kin}")
# ---------------------------------------------------------------------------
# WhisperGroupMultisigInceptDoer
# ---------------------------------------------------------------------------

class WhisperGroupMultisigInceptDoer(doing.DoDoer):
    """
    Initiates a group multisig inception and distributes the EXN via weirwood
    messages instead of the standard KERI Poster/mailbox transport.

    Mirrors locksmith's GroupMultisigInceptDoer but replaces postman.send()
    with remoting.post_message().
    """

    def __init__(self, app: "LocksmithApplication", alias: str, mhab,
                 smids: list[str], rmids: list[str] | None = None,
                 isith: str | int | None = None, nsith: str | int | None = None,
                 wits: list[str] | None = None, toad: int = 0,
                 delpre: str | None = None, signal_bridge=None, **kwargs):
        self.app = app
        self.hby = app.vault.hby
        self.alias = alias
        self.mhab = mhab
        self.smids = smids
        self.rmids = rmids if rmids is not None else smids
        self.isith = isith if isith is not None else str(len(smids))
        self.nsith = nsith if nsith is not None else self.isith
        self.wits = wits or []
        self.toad = toad
        self.delpre = delpre
        self.signal_bridge = signal_bridge
        self.kwargs = kwargs
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.incept_do)])

    def incept_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperGroupMultisigInceptDoer", "group_inception_started",
                    {"alias": self.alias, "smids": self.smids},
                )

            ghab = self.hby.makeGroupHab(
                group=self.alias,
                mhab=self.mhab,
                smids=self.smids,
                rmids=self.rmids,
                isith=self.isith,
                nsith=self.nsith,
                wits=self.wits,
                toad=self.toad,
                delpre=self.delpre,
                **self.kwargs,
            )
            icp = ghab.makeOwnInception(allowPartiallySigned=True)
            icp_serder = serdering.SerderKERI(raw=icp)

            exn, atc = keri_grouping.multisigInceptExn(
                hab=self.mhab,
                smids=self.smids,
                rmids=self.rmids,
                icp=icp,
                delegator=self.delpre,
            )
            raw = bytes(exn.raw) + bytes(atc)

            others = [pre for pre in self.smids if pre != self.mhab.pre]
            for recpt in others:
                asyncio.get_event_loop().create_task(
                    remoting.post_message(self.app, recpt, _TOPIC_MULTISIG, raw, sender_aid=self.mhab.pre)
                )
                logger.info(f"Queued weirwood icp EXN for {recpt[:16]}...")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperGroupMultisigInceptDoer", "group_inception_exn_sent",
                    {"alias": self.alias, "pre": ghab.pre, "recipients": others},
                )

            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Seqner(sn=0)
            saider = coring.Saider(qb64=icp_serder.said)
            self.counselor.start(ghab=ghab, prefixer=prefixer, seqner=seqner, saider=saider)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperGroupMultisigInceptDoer", "group_inception_waiting",
                    {"alias": self.alias, "pre": ghab.pre},
                )

            while not self.counselor.complete(prefixer, seqner):
                yield self.tock

            logger.info(f"Group '{self.alias}' ({ghab.pre}) created successfully")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperGroupMultisigInceptDoer", "group_identifier_created",
                    {"alias": self.alias, "pre": ghab.pre, "success": True},
                )

        except Exception as e:
            logger.exception(f"WhisperGroupMultisigInceptDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperGroupMultisigInceptDoer", "group_inception_failed",
                    {"alias": self.alias, "error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# WhisperMultisigJoinDoer
# ---------------------------------------------------------------------------

class WhisperMultisigJoinDoer(doing.DoDoer):
    """
    Participant-side: joins a group icp proposal and sends the signed response
    via weirwood messages instead of KERI Poster/mailbox transport.

    Mirrors locksmith's MultisigJoinDoer but replaces postman.send() with
    remoting.post_message().
    """

    def __init__(self, app: "LocksmithApplication", alias: str, proposal_said: str,
                 mhab, signal_bridge=None):
        self.app = app
        self.hby = app.vault.hby
        self.alias = alias
        self.proposal_said = proposal_said
        self.mhab = mhab
        self.signal_bridge = signal_bridge
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.join_do)])

    def join_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            exn, pathed = exchanging.cloneMessage(self.hby, said=self.proposal_said)
            if exn is None:
                raise ValueError(f"Proposal EXN not found: {self.proposal_said}")

            payload = exn.ked.get("a", {})
            embeds = exn.ked.get("e", {})
            smids = payload.get("smids", [])
            rmids = payload.get("rmids", smids)
            delegator = payload.get("delegator")

            icp_sad = embeds.get("icp")
            if icp_sad is None:
                raise ValueError("No icp found in proposal embeds")
            oicp = serdering.SerderKERI(sad=icp_sad)

            from keri import kering
            inits = {
                "isith": oicp.ked["kt"],
                "nsith": oicp.ked["nt"],
                "estOnly": kering.TraitCodex.EstOnly in oicp.ked.get("c", []),
                "DnD": kering.TraitCodex.DoNotDelegate in oicp.ked.get("c", []),
                "toad": oicp.ked["bt"],
                "wits": oicp.ked["b"],
                "delpre": oicp.ked.get("di"),
            }

            ghab = self.hby.makeGroupHab(
                group=self.alias, mhab=self.mhab,
                smids=smids, rmids=rmids, **inits,
            )
            own_icp = ghab.makeOwnInception(allowPartiallySigned=True)
            own_serder = serdering.SerderKERI(raw=own_icp)

            resp_exn, resp_atc = keri_grouping.multisigInceptExn(
                hab=self.mhab, smids=smids, rmids=rmids,
                icp=own_icp, delegator=delegator,
            )
            raw = bytes(resp_exn.raw) + bytes(resp_atc)

            others = [pre for pre in smids if pre != self.mhab.pre]
            for recpt in others:
                asyncio.get_event_loop().create_task(
                    remoting.post_message(self.app, recpt, _TOPIC_MULTISIG, raw, sender_aid=self.mhab.pre)
                )

            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Seqner(sn=0)
            saider = coring.Saider(qb64=own_serder.said)
            self.counselor.start(ghab=ghab, prefixer=prefixer, seqner=seqner, saider=saider)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperMultisigJoinDoer", "group_join_waiting",
                    {"alias": self.alias, "pre": ghab.pre},
                )

            while not self.counselor.complete(prefixer, seqner):
                yield self.tock

            logger.info(f"Joined group '{self.alias}' ({ghab.pre})")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperMultisigJoinDoer", "group_identifier_joined",
                    {"alias": self.alias, "pre": ghab.pre, "success": True},
                )

        except Exception as e:
            logger.exception(f"WhisperMultisigJoinDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperMultisigJoinDoer", "group_join_failed",
                    {"alias": self.alias, "error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# CreateRegistryDoer
# ---------------------------------------------------------------------------

class CreateRegistryDoer(doing.DoDoer):
    """
    Initiates multisig registry creation (vcp + group ixn) and distributes
    the /multisig/vcp EXN to group members via weirwood messages.

    Reuses the vault's counselor (app.vault.counselor) rather than creating
    a new one.  Signals completion so the progress screen can advance.
    """

    def __init__(self, app: "LocksmithApplication", hab_alias: str,
                 registry_name: str, weirwood_aid: str, signal_bridge=None):
        self.app = app
        self.hby = app.vault.hby
        self.rgy = app.vault.rgy
        self.hab_alias = hab_alias
        self.registry_name = registry_name
        self.weirwood_aid = weirwood_aid
        self.signal_bridge = signal_bridge
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.create_do)])

    def create_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            hab = self.hby.habByName(self.hab_alias)
            if hab is None:
                raise ValueError(f"Identifier '{self.hab_alias}' not found")
            if self.rgy.registryByName(self.registry_name) is not None:
                raise ValueError(f"Registry '{self.registry_name}' already exists")

            registry = self.rgy.makeRegistry(
                name=self.registry_name,
                prefix=hab.pre,
                noBackers=False,
                baks=[self.weirwood_aid],
                toad=1,
                nonce=coring.randomNonce(),
            )

            regd = getattr(registry, "regd", registry.regk)
            rseal = {"i": registry.regk, "s": "0", "d": regd}
            anc = hab.interact(data=[rseal])
            aserder = serdering.SerderKERI(raw=bytes(anc))

            registrar = vdr_credentialing.Registrar(
                hby=self.hby, rgy=self.rgy, counselor=self.counselor
            )
            registrar.incept(iserder=registry.vcp, anc=aserder)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CreateRegistryDoer", "registry_inception_started",
                    {"name": self.registry_name, "regk": registry.regk},
                )

            # For GroupHab: broadcast /multisig/vcp EXN via weirwood
            if isinstance(hab, GroupHab):
                try:
                    exn, atc = keri_grouping.multisigRegistryInceptExn(
                        ghab=hab,
                        vcp=registry.vcp.raw,
                        anc=anc,
                        usage=f"Registry: {self.registry_name}",
                    )
                    raw = bytes(exn.raw) + bytes(atc)
                    smids = self.hby.db.signingMembers(pre=hab.pre)
                    others = [pre for pre in smids if pre != hab.mhab.pre]
                    for recpt in others:
                        asyncio.get_event_loop().create_task(
                            remoting.post_message(self.app, recpt, _TOPIC_MULTISIG, raw, sender_aid=hab.mhab.pre)
                        )
                        logger.info(f"Queued weirwood vcp EXN for {recpt[:16]}...")
                except Exception as e:
                    logger.warning(f"Failed to send /multisig/vcp EXN: {e}")

            # Poll for completion (counselor coordinates group ixn signatures)
            deadline = self.app.vault.tymth() + _REGISTRY_POLL_TIMEOUT
            while True:
                self.rgy.processEscrows()
                if registrar.complete(pre=registry.regk, sn=0):
                    break
                if self.app.vault.tymth() > deadline:
                    raise RuntimeError(
                        f"Registry '{self.registry_name}' timed out after {_REGISTRY_POLL_TIMEOUT}s"
                    )
                yield self.tock

            # POST vcp to weirwood registrar
            asyncio.get_event_loop().create_task(
                remoting.post_tel_event(self.app, bytes(registry.vcp.raw))
            )

            logger.info(f"Registry '{self.registry_name}' created: {registry.regk}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CreateRegistryDoer", "registry_created",
                    {
                        "name": self.registry_name,
                        "regk": registry.regk,
                        "success": True,
                    },
                )

        except Exception as e:
            logger.exception(f"CreateRegistryDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CreateRegistryDoer", "registry_creation_failed",
                    {"name": self.registry_name, "error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# WhisperRegistryAcceptDoer
# ---------------------------------------------------------------------------

class WhisperRegistryAcceptDoer(doing.DoDoer):
    """
    Participant-side: accepts a /multisig/vcp registry proposal by co-signing
    the group interaction event and sending the response via weirwood messages.
    """

    def __init__(self, app: "LocksmithApplication", proposal_said: str,
                 mhab, signal_bridge=None):
        self.app = app
        self.hby = app.vault.hby
        self.rgy = app.vault.rgy
        self.proposal_said = proposal_said
        self.mhab = mhab
        self.signal_bridge = signal_bridge
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.accept_do)])

    def accept_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            exn, pathed = exchanging.cloneMessage(self.hby, said=self.proposal_said)
            if exn is None:
                raise ValueError(f"VCP proposal EXN not found: {self.proposal_said}")

            embeds = exn.ked.get("e", {})
            vcp_sad = embeds.get("vcp")
            anc_sad = embeds.get("anc")
            if vcp_sad is None or anc_sad is None:
                raise ValueError("Missing vcp or anc in /multisig/vcp embeds")

            vcp_serder = serdering.SerderKERI(sad=vcp_sad)
            anc_serder = serdering.SerderKERI(sad=anc_sad)

            payload = exn.ked.get("a", {})
            gid = payload.get("gid", "")

            # Locate the group hab
            ghab = self.hby.habs.get(gid) or self.hby.habByName(gid)
            if ghab is None:
                raise ValueError(f"Group hab not found for gid {gid[:16]}...")

            # Create registry locally with same parameters
            registry = self.rgy.makeRegistry(
                name=vcp_serder.ked.get("i", self.proposal_said[:16]),
                prefix=ghab.pre,
                noBackers=False,
                baks=vcp_serder.ked.get("b", []),
                toad=int(vcp_serder.ked.get("bt", 1)),
                nonce=vcp_serder.ked.get("n", coring.randomNonce()),
            )

            # Co-sign the group ixn
            regd = getattr(registry, "regd", registry.regk)
            rseal = {"i": registry.regk, "s": "0", "d": regd}
            own_anc = ghab.interact(data=[rseal])
            own_anc_serder = serdering.SerderKERI(raw=bytes(own_anc))

            registrar = vdr_credentialing.Registrar(
                hby=self.hby, rgy=self.rgy, counselor=self.counselor
            )
            registrar.incept(iserder=registry.vcp, anc=own_anc_serder)

            # Send our signed response via weirwood
            resp_exn, resp_atc = keri_grouping.multisigRegistryInceptExn(
                ghab=ghab,
                vcp=registry.vcp.raw,
                anc=own_anc,
                usage=f"Registry: {registry.regk[:16]}",
            )
            raw = bytes(resp_exn.raw) + bytes(resp_atc)
            smids = self.hby.db.signingMembers(pre=ghab.pre)
            others = [pre for pre in smids if pre != self.mhab.pre]
            for recpt in others:
                asyncio.get_event_loop().create_task(
                    remoting.post_message(self.app, recpt, _TOPIC_MULTISIG, raw, sender_aid=self.mhab.pre)
                )

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperRegistryAcceptDoer", "registry_accept_waiting",
                    {"regk": registry.regk},
                )

            # Poll for completion
            deadline = self.app.vault.tymth() + _REGISTRY_POLL_TIMEOUT
            while True:
                self.rgy.processEscrows()
                if registrar.complete(pre=registry.regk, sn=0):
                    break
                if self.app.vault.tymth() > deadline:
                    raise RuntimeError("Registry acceptance timed out")
                yield self.tock

            asyncio.get_event_loop().create_task(
                remoting.post_tel_event(self.app, bytes(registry.vcp.raw))
            )

            logger.info(f"Accepted and completed registry {registry.regk}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperRegistryAcceptDoer", "registry_accepted",
                    {"regk": registry.regk, "success": True},
                )

        except Exception as e:
            logger.exception(f"WhisperRegistryAcceptDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "WhisperRegistryAcceptDoer", "registry_accept_failed",
                    {"error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return
