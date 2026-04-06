# -*- encoding: utf-8 -*-
"""
whisper.issuer.doers module

Async helper for KERI credential registry creation.

create_registry() handles the full single-sig registry creation flow using
keripy's Regery/Registrar APIs.  For multisig group habs, the counselor
coordination path is noted as a TODO
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from keri.app import grouping as keri_grouping
from keri.app.habbing import GroupHab
from keri.core import coring, serdering
from keri.vdr import credentialing as vdr_credentialing

from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

logger = logging.getLogger(__name__)

_REGISTRY_POLL_INTERVAL = 0.1   # seconds between completion checks
_REGISTRY_POLL_TIMEOUT = 30.0   # seconds before giving up


async def create_registry(
    app: "LocksmithApplication",
    hab_alias: str,
    registry_name: str,
    weirwood_aid: str,
) -> dict:
    """
    Create a KERI credential registry backed by weirwood.

    Steps:
      1. Validate the identifier and registry name.
      2. Call rgy.makeRegistry() with noBackers=False, weirwood as sole backer.
      3. Anchor the vcp to the issuer's KEL via hab.interact().
      4. Call registrar.incept() to process locally.
      5. Poll registrar.complete() until the registry is live.
      6. POST the vcp TEL event to weirwood /registrar/tel-events.

    For GroupHab (multisig): sends /multisig/vcp EXN via keripy Poster to group
    members.  Full counselor escrow coordination requires hio event-loop
    integration and is tracked as a follow-on task.

    Args:
        app:           LocksmithApplication instance.
        hab_alias:     Alias of the identifier to use as issuer.
        registry_name: Human-readable registry name (stored locally).
        weirwood_aid:  AID of the weirwood registrar backer.

    Returns:
        dict with keys: regk, name, vcp_said, vcp_raw (bytes)

    Raises:
        ValueError: Invalid arguments.
        RuntimeError: Registry creation or weirwood posting failed.
    """
    hby = app.vault.hby
    rgy = app.vault.rgy

    if not hab_alias:
        raise ValueError("Identifier alias is required")
    if not registry_name:
        raise ValueError("Registry name is required")
    if not weirwood_aid:
        raise ValueError("Weirwood AID is required (check plugin config)")

    hab = hby.habs.get(hab_alias)
    if hab is None:
        raise ValueError(f"Identifier '{hab_alias}' not found in vault")

    if rgy.registryByName(registry_name) is not None:
        raise ValueError(f"A registry named '{registry_name}' already exists")

    logger.info(f"Creating registry '{registry_name}' for {hab_alias} ({hab.pre}), "
                f"backer={weirwood_aid}")

    # -- 1. Create registry object (backed by weirwood) --
    registry = rgy.makeRegistry(
        name=registry_name,
        prefix=hab.pre,
        noBackers=False,
        baks=[weirwood_aid],
        toad=1,
        nonce=coring.randomNonce(),
    )

    # -- 2. Anchor vcp to the issuer's KEL via an ixn --
    regd = getattr(registry, "regd", registry.regk)
    rseal = {"i": registry.regk, "s": "0", "d": regd}
    anc = hab.interact(data=[rseal])
    aserder = serdering.SerderKERI(raw=bytes(anc))

    # -- 3. Incept the registry (triggers local escrow processing) --
    if isinstance(hab, GroupHab):
        counselor = keri_grouping.Counselor(hby=hby)
    else:
        counselor = None

    registrar = vdr_credentialing.Registrar(hby=hby, rgy=rgy, counselor=counselor)
    registrar.incept(iserder=registry.vcp, anc=aserder)

    # -- 4. For multisig: broadcast /multisig/vcp EXN to other group members --
    if isinstance(hab, GroupHab):
        try:
            from keri.app import forwarding as keri_forwarding
            postman = keri_forwarding.Poster(hby=hby)
            smids = hab.db.signingMembers(pre=hab.pre)
            smids.remove(hab.mhab.pre)
            for recp in smids:
                exn, atc = keri_grouping.multisigRegistryInceptExn(
                    ghab=hab,
                    vcp=registry.vcp.raw,
                    anc=anc,
                    usage=f"Registry: {registry_name}",
                )
                postman.send(
                    src=hab.mhab.pre,
                    dest=recp,
                    topic="multisig",
                    serder=exn,
                    attachment=atc,
                )
            logger.info(f"Sent /multisig/vcp EXN to {len(smids)} group member(s)")
            # TODO: Add postman to hio event loop for delivery; for now it queues
            # internally.  Full counselor escrow coordination (threshold waiting)
            # requires integrating CreateRegistryDoer as a hio DoDoer.
        except Exception as e:
            logger.warning(f"Multisig EXN sending incomplete: {e}")

    # -- 5. Poll for local completion --
    deadline = asyncio.get_event_loop().time() + _REGISTRY_POLL_TIMEOUT
    while True:
        rgy.processEscrows()
        if registrar.complete(pre=registry.regk, sn=0):
            break
        if asyncio.get_event_loop().time() > deadline:
            raise RuntimeError(
                f"Registry creation timed out after {_REGISTRY_POLL_TIMEOUT}s. "
                "The registry may still be processing — check KERI escrows."
            )
        await asyncio.sleep(_REGISTRY_POLL_INTERVAL)

    logger.info(f"Registry '{registry_name}' created: regk={registry.regk}")

    # -- 6. POST vcp to weirwood (registers weirwood as active backer) --
    post_result = await remoting.post_tel_event(app, bytes(registry.vcp.raw))
    if not post_result.get("success"):
        logger.warning(
            f"Registry created locally but weirwood POST failed: "
            f"{post_result.get('error')}. "
            "The vcp can be re-posted manually."
        )

    return {
        "regk": registry.regk,
        "name": registry_name,
        "vcp_said": registry.vcp.said,
        "vcp_raw": bytes(registry.vcp.raw),
        "weirwood_receipt": post_result.get("data", {}).get("receipt", ""),
    }