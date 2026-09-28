# -*- encoding: utf-8 -*-
"""
castellan.core.credentialing module

Utilities for credential-related operations including schema management and credential issuance.

"""
from typing import Optional, Any

from keri import help, core, kering
from keri.app import signing
from keri.core import coring, eventing, scheming
from keri.help import helping
from keri.kering import Kinds
from keri.vc import proving

logger = help.ogler.getLogger(__name__)


def create_multisig_credential(hby, hab, registry, verifier, schema_said, recipient_pre, attributes, edges, rules):
    """
    Generate and issue a credential based on the specified schema and data. The method uses the provided
    registry, schema, and attributes to compose a valid credential, before signing and issuing it according
    to the specified rules and edges. The issued credential includes all required system fields, as well as
    any additional attributes supplied by the user.

    Params:
        hby (Hby): Habitat used for creating and interacting with the credential
            issuance environment.
        hab (Hab): Habitat instance representing the entity issuing the credential.
        registry (Registry): Credential registry used for tracking and managing
            issued credentials.
        verifier (Verifier): Habitat instance representing the entity verifying the credential.
        schema_said (str): Self-addressing Identifier (SAID) of the ACDC schema to
            use for the credential.
        recipient_pre (str): Identifier prefix of the entity that will receive the
            credential.
        attributes (dict): Dictionary containing user-provided attributes to be
            included in the credential.
        edges (dict, optional): Dictionary defining edge credentials, their
            schemas, and other linkage information.
        rules (list, optional): List of rules governing the issuance and lifecycle
            of the credential.

    Returns:
        dict: Serialized representation of the issued credential.
    """
    # Get the schema
    creder = build_credential(attributes, edges, hab, hby, recipient_pre, registry, rules, schema_said, verifier)

    dt = creder.attrib["dt"] if "dt" in creder.attrib else helping.nowIso8601()
    iserder = registry.issue(said=creder.said, dt=dt)

    rseal = eventing.SealEvent(iserder.pre, iserder.snh, iserder.said)
    rseal = dict(i=rseal.i, s=rseal.s, d=rseal.d)

    anc = hab.interact(data=[rseal])

    issue(registry.rgy, verifier, creder, iserder)

    acdc = signing.serialize(creder, coring.Prefixer(qb64=iserder.pre),
                             core.Number(num=iserder.sn, code=core.NumDex.Huge),
                             coring.Saider(qb64=iserder.said))

    return acdc, iserder, anc


def build_credential(hby, hab, attributes, edges, recipient_pre, registry, rules, schema_said, verifier) -> Any:
    schemer = hby.db.schema.get(keys=(schema_said,))
    if not schemer:
        raise Exception(f"Schema {schema_said} not found")

    schema_title = schemer.sed.get('title', 'Untitled')

    if recipient_pre is not None and recipient_pre not in hby.kevers:
        raise kering.ConfigurationError("Unable to issue credential to {}.  A connection to that identifier must "
                                        "already be established".format(recipient_pre))

    logger.info(f"Issuing credential: {schema_title} from {hab.name} to {recipient_pre}")

    # Build the credential data structure
    # Add required system fields
    creder_data = {
        'i': recipient_pre,  # Issuee (recipient)
        'dt': coring.Dater().dts,  # Issuance datetime
    }

    schema = schemer.sed
    props = schema.get('properties', {})
    if 'a' not in props or 'oneOf' not in props['a']:
        raise Exception("Schema does not have a 'oneOf' array for attributes")

    one_of = props['a']['oneOf']

    # Find the object type (should be second element, index 1)
    attributes_obj = None
    for item in one_of:
        if isinstance(item, dict) and item.get('type') == 'object':
            attributes_obj = item
            break

    if not attributes_obj:
        raise Exception("Schema does not have a 'oneOf' object for attributes")

    # Get properties and required list
    properties = attributes_obj.get('properties', {})
    private = 'u' in properties

    # Add user-provided attributes
    creder_data.update(attributes)

    # Build edges block if edge credentials are specified
    edges_block = None
    if edges:
        edges_block = dict()
        edges_block['d'] = ""
        for edge_name, edge_def in edges.items():
            edges_block[edge_name] = {
                'n': edge_def['cred_said'],
                's': edge_def['schema_said']
            }
            if "operator" in edge_def and edge_def["operator"]:
                edges_block[edge_name]['o'] = edge_def["operator"]

        _, edges_block = coring.Saider.saidify(sad=edges_block, kind=Kinds.json, label=coring.Saids.d)

    creder = create(registry=registry,
                    verifier=verifier,
                    recp=recipient_pre,
                    schema=schema_said,
                    source=edges_block,
                    rules=rules,
                    data=attributes,
                    private=private)
    return creder


def create(registry, verifier, recp: Optional[str], schema, source, rules, data, private: bool = False,
           private_credential_nonce: Optional[str] = None, private_subject_nonce: Optional[str] = None):
    """  Create and validate a credential returning the fully populated Creder

    Param:


    Returns:
        Creder: Creder class for the issued credential

    """
    creder = proving.credential(issuer=registry.hab.pre,
                                schema=schema,
                                recipient=recp,
                                data=data,
                                source=source,
                                private=private,
                                private_credential_nonce=private_credential_nonce,
                                private_subject_nonce=private_subject_nonce,
                                rules=rules,
                                status=registry.regk)
    validate(verifier, creder)
    return creder


def validate(verifier, creder):
    """

    Params:
        verifier (Verifier): verifier object to validate the credential
        creder (Creder): creder object representing the credential to validate

    Returns:
        bool: true if credential is valid against a known schema

    """
    schema = creder.sad['s']
    scraw = verifier.resolver.resolve(schema)
    if not scraw:
        raise kering.ConfigurationError("Credential schema {} not found.  It must be loaded with data oobi before "
                                        "issuing credentials".format(schema))

    schemer = scheming.Schemer(raw=scraw)
    try:
        schemer.verify(creder.raw)
    except kering.ValidationError as ex:
        raise kering.ConfigurationError(f"Credential schema validation failed for {schema}: {ex}")

    return True


def issue(rgy, verifier, creder, serder):
    """ Issue the credential creder and handle witness propagation and communication

    Params:
        rgy (Registry): Registry object to store the credential
        verifier (Verifier): Verifier object to validate the credential
        creder (Creder): Credential object to issue
        serder (Serder): KEL or TEL anchoring event
            need to contribute digest of next rotating key
    """
    # escrow waiting for other signatures
    prefixer = coring.Prefixer(qb64=serder.pre)
    seqner = coring.Seqner(sn=serder.sn)

    rgy.reger.cmse.put(keys=(creder.said, seqner.qb64), val=creder)

    try:
        verifier.processCredential(creder=creder, prefixer=prefixer, seqner=seqner,
                                        saider=coring.Saider(qb64=serder.said))
    except kering.MissingRegistryError:
        pass
