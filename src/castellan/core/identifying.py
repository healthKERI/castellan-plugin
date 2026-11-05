# -*- encoding: utf-8 -*-
"""
Utilities for working with multisig identifiers

"""
from math import ceil

from keri import kering
from keri.core import coring, eventing


def get_multisig_state(app, identifier) -> str:
    """Determine multisig state: 'pending', 'ready', or 'active'."""
    aid = identifier.get('aid', '')
    current_event = identifier.get("current_event", None)
    key_state = identifier.get("key_state", None)
    rotation_request = identifier.get("rotation_request", None)
    witness_rotate = identifier.get("witness_rotate", None)
    tel_event = identifier.get("current_tel_event", None)
    my_member = get_my_member(app, identifier)

    if identifier.get('aid') is None:
        if all([member.get("member_aid", None) for member in identifier.get("members")]):
            return "inception_ready"
        if my_member.get("member_aid", None) is not None:
            return "inception_joined"
        else:
            return "inception"

    if rotation_request:
        return "rotation_joined" if has_joined(app, identifier) else "rotation"

    if witness_rotate:
        if current_event:
            return "witness_rotate_signed" if has_signed(app, identifier) else "witness_rotate_created"

        return "witness_rotate_joined" if has_joined(app, identifier) else "witness_rotate"

    if tel_event and tel_event.get("t") == "vcp":
        # Registry creation in progress - behaves like inception states
        return "registry_signed" if has_signed(app, identifier) else "registry_created"

    # Check for credential issuance states
    credential = identifier.get("credential")
    if credential:
        return "credential_signed" if has_signed_credential(app, identifier) else "credential_created"

    elif current_event:
        ilk = current_event.get('t')
        if ilk in (kering.Ilks.icp, kering.Ilks.dip):
            return "inception_signed" if has_joined(app, identifier) else "inception_created"
        elif ilk in (kering.Ilks.rot, kering.Ilks.drt):
            return "rotation_signed" if has_joined(app, identifier) else "rotation_created"
        else:
            return "interact_signed" if has_joined(app, identifier) else "interact"

    elif key_state:
        if aid in app.hby.kevers:
            kever = app.hby.kevers[aid]
            return "live_behind" if kever.sner.num < int(key_state.get('s', '0'), 16) else "live"
        else:
            return "live_behind"
    else:
        return "single"


def get_my_member(app, identifier) -> dict | None:
    """Find current user's member object in the multisig, if present."""
    my_account_aid = get_current_account_aid(app)
    if not my_account_aid:
        return None

    members = identifier.get('members', [])
    for member in members:
        if member.get('account_aid') == my_account_aid:
            return member

    return None


def get_current_account_aid(app) -> str:
    """Get the current user's Castellan account AID."""
    if not app or not app.vault:
        return ""

    account = app.vault.plugin_state.get("castellan", {}).get("account", {})
    return account.get("aid", "")


def is_member(app, identifier) -> bool:
    """Check if current user is a member of this multisig."""
    return get_my_member(app, identifier) is not None


def has_approved(app, identifier) -> bool:
    """Check if current user has joined the multisig."""
    my_member = get_my_member(app, identifier)
    return my_member is not None and my_member.get('member_aid') is not None


def has_joined(app, identifier) -> bool:
    """Check if current user has joined the multisig."""
    my_member = get_my_member(app, identifier)
    return has_approved(app, identifier) and my_member.get('public_key', None)


def has_signed(app, identifier) -> bool:
    """Check if current user has signed the multisig."""
    my_member = get_my_member(app, identifier)
    return my_member.get('current_signature', None) is not None


def has_signed_credential(app, identifier) -> bool:
    """Check if current user has signed both IXN and grant for credential issuance."""
    my_member = get_my_member(app, identifier)
    if not my_member:
        return False
    # Credential issuance requires both signatures
    has_ixn_sig = my_member.get('current_signature') is not None
    has_grant_sig = my_member.get('grant_signature') is not None
    return has_ixn_sig and has_grant_sig


def create_multisig_rotation(hab, isith, nsith, verfers, digers:list, toad, cuts, adds, data):
    kever = hab.kever
    if isith is None:
        isith = kever.ntholder.sith  # use prior next sith as default
    if nsith is None:
        nsith = isith  # use new current as default

    if isith is None:  # compute default from newly rotated verfers above
        isith = f"{max(1, ceil(len(verfers) / 2)):x}"
    if nsith is None:  # compute default from newly rotated digers above
        nsith = f"{max(0, ceil((len(digers) if digers is not None else 0) / 2)):x}"

    cst = coring.Tholder(sith=isith).sith  # current signing threshold
    nst = coring.Tholder(sith=nsith).sith  # next signing threshold

    keys = [verfer.qb64 for verfer in verfers]

    indices = []
    for idx, diger in enumerate(kever.ndigers):
        pdigs = [coring.Diger(ser=verfer.qb64b, code=diger.code).qb64 for verfer in verfers]
        if diger.qb64 in pdigs:
            indices.append(idx)

    if not kever.ntholder.satisfy(indices):
        raise kering.ValidationError("invalid rotation, new key set unable to satisfy prior next signing threshold")

    if kever.delpre is not None:  # delegator only shows up in delcept
        serder = eventing.deltate(pre=kever.prefixer.qb64,
                                  keys=keys,
                                  dig=kever.serder.said,
                                  sn=kever.sner.num + 1,
                                  isith=cst,
                                  nsith=nst,
                                  ndigs=[diger.qb64 for diger in digers],
                                  toad=toad,
                                  wits=kever.wits,
                                  cuts=cuts,
                                  adds=adds,
                                  data=data)
    else:
        serder = eventing.rotate(pre=kever.prefixer.qb64,
                                 keys=keys,
                                 dig=kever.serder.said,
                                 sn=kever.sner.num + 1,
                                 isith=cst,
                                 nsith=nst,
                                 ndigs=[diger.qb64 for diger in digers],
                                 toad=toad,
                                 wits=kever.wits,
                                 cuts=cuts,
                                 adds=adds,
                                 data=data)

    # Must rotate local Hab before signing
    hab.mhab.rotate()

    # sign handles group hab with .mhab case
    my_idx = hab.smids.index(hab.mhab.pre)
    sigers = hab.mhab.sign(ser=serder.raw, indexed=True, indices=[my_idx])

    return serder, sigers
