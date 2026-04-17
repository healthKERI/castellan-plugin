# -*- encoding: utf-8 -*-
"""
whisper.core.remoting module

Functions for interacting with the Weirwood credential management server.
"""
import base64
import json
import urllib.parse
from typing import TYPE_CHECKING, Dict, Any, Optional

from locksmith.core.credentialing import outputCred, escape_keys

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

from keri import help

logger = help.ogler.getLogger(__name__)


def _get_essr(app: "LocksmithApplication"):
    """Get the ESSR client from plugin state."""
    if not app.vault:
        return None
    return app.vault.plugin_state.get("whisper", {}).get("essr")


# ---------------------------------------------------------------------------
# Uploaded identifiers
# ---------------------------------------------------------------------------

async def upload_identifier(
    app: "LocksmithApplication",
    aid: str,
    alias: str,
    kel_bytes: bytes,
    oobi: str = "",
) -> Dict[str, Any]:
    """
    Upload a whisper identifier to weirwood POST /identifiers.

    Sends a multipart/form-data request with:
      doc — JSON metadata {aid, alias, oobi}
      kel — raw CESR-encoded KEL bytes

    Returns dict with 'success' bool and, on success, the stored identifier doc.
    Returns 'conflict': True when weirwood returns 409 (alias already taken).
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        files = {
            'doc': ('doc.json', json.dumps({"aid": aid, "alias": alias, "oobi": oobi}), 'application/json'),
            'kel': ('kel.cesr', kel_bytes, 'application/octet-stream'),
        }
        response = await essr.request(
            path="/identifiers",
            method="POST",
            files=files,
            timeout=30,
        )
        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        elif response is not None and response.status_code == 409:
            return {'success': False, 'conflict': True, 'error': 'Alias already uploaded to weirwood'}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error uploading identifier: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_identifier_kel(app: "LocksmithApplication", aid: str) -> Dict[str, Any]:
    """
    GET /identifiers/{aid}/kel — fetch the CESR KEL stream for a peer identifier.

    Returns dict with 'success' bool and, on success, 'kel_bytes' (raw bytes).
    Returns empty kel_bytes if the identifier exists but KEL has not been captured yet.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/identifiers/{aid}/kel",
            method="GET",
        )
        if response is not None and response.status_code == 200:
            data = response.json()
            kel_b64 = data.get("kel", "")
            kel_bytes = base64.b64decode(kel_b64) if kel_b64 else b""
            return {'success': True, 'kel_bytes': kel_bytes}
        elif response is not None and response.status_code == 404:
            return {'success': False, 'error': 'Identifier not found on weirwood'}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching KEL for {aid}: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_identifiers(app: "LocksmithApplication") -> Dict[str, Any]:
    """
    GET all uploaded identifiers from weirwood /identifiers.

    Returns dict with 'success' bool and, on success, 'identifiers' list of
    {aid, alias, oobi, created_at} dicts.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(path="/identifiers", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching identifiers: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Issued credentials
# ---------------------------------------------------------------------------

async def fetch_issued_credentials(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
) -> Dict[str, Any]:
    """Fetch issued credentials from the Weirwood server (paginated)."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        params = [f"page={page}", f"page_size={page_size}"]
        if filter_term:
            params.append(f"filter={urllib.parse.quote(filter_term)}")
        if order:
            for o in order:
                params.append(f"order={urllib.parse.quote(o)}")

        path = f"/issued-credentials?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching issued credentials: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_all_weirwood_issued_saids(app: "LocksmithApplication") -> set:
    """Fetch all issued credential SAIDs currently stored on the Weirwood server."""
    essr = _get_essr(app)
    if not essr:
        return set()

    try:
        response = await essr.request(path="/issued-credentials?page_size=10000", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            return {cred['said'] for cred in data.get('credentials', [])}
        return set()
    except Exception as e:
        logger.error(f"Error fetching weirwood issued SAIDs: {e}")
        return set()


async def upload_issued_credential(
    app: "LocksmithApplication",
    credential_said: str,
    schema: dict,
    issuer: str,
    recipient: str,
) -> Dict[str, Any]:
    """Upload an issued credential to the Weirwood server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault or not app.vault.hby:
        return {'success': False, 'error': 'No local vault open'}

    try:
        hby = app.vault.hby
        rgy = app.vault.rgy

        doc = {
            'said': credential_said,
            'issuer': issuer,
            'recipient': recipient,
            'schema': escape_keys(schema),
        }

        acdc = outputCred(hby, rgy, credential_said)
        if not acdc:
            return {'success': False, 'error': f'No ACDC data for {credential_said}'}

        files = {
            'acdc': ('output.bin', bytes(acdc), 'application/octet-stream'),
            'doc': ('data.json', json.dumps(doc), 'application/json'),
        }

        response = await essr.request(
            path="/issued-credentials",
            method="POST",
            files=files,
            timeout=60,
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error uploading issued credential: {e}")
        return {'success': False, 'error': str(e)}


async def delete_issued_credential(
    app: "LocksmithApplication",
    said: str,
) -> Dict[str, Any]:
    """Delete an issued credential from the Weirwood server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/issued-credentials/{urllib.parse.quote(said, safe='')}",
            method="DELETE",
        )

        if response is not None and response.status_code == 204:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error deleting issued credential: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Received credentials
# ---------------------------------------------------------------------------

async def fetch_received_credentials(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
) -> Dict[str, Any]:
    """Fetch received credentials from the Weirwood server (paginated)."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        params = [f"page={page}", f"page_size={page_size}"]
        if filter_term:
            params.append(f"filter={urllib.parse.quote(filter_term)}")
        if order:
            for o in order:
                params.append(f"order={urllib.parse.quote(o)}")

        path = f"/received-credentials?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching received credentials: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_all_weirwood_received_saids(app: "LocksmithApplication") -> set:
    """Fetch all received credential SAIDs currently stored on the Weirwood server."""
    essr = _get_essr(app)
    if not essr:
        return set()

    try:
        response = await essr.request(path="/received-credentials?page_size=10000", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            return {cred['said'] for cred in data.get('credentials', [])}
        return set()
    except Exception as e:
        logger.error(f"Error fetching weirwood received SAIDs: {e}")
        return set()


async def upload_received_credential(
    app: "LocksmithApplication",
    credential_said: str,
    schema: dict,
    issuer: str,
    holder: str,
) -> Dict[str, Any]:
    """Upload a received credential to the Weirwood server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault or not app.vault.hby:
        return {'success': False, 'error': 'No local vault open'}

    try:
        hby = app.vault.hby
        rgy = app.vault.rgy

        doc = {
            'said': credential_said,
            'issuer': issuer,
            'holder': holder,
            'schema': escape_keys(schema),
        }

        acdc = outputCred(hby, rgy, credential_said)
        if not acdc:
            return {'success': False, 'error': f'No ACDC data for {credential_said}'}

        files = {
            'acdc': ('output.bin', bytes(acdc), 'application/octet-stream'),
            'doc': ('data.json', json.dumps(doc), 'application/json'),
        }

        response = await essr.request(
            path="/received-credentials",
            method="POST",
            files=files,
            timeout=60,
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error uploading received credential: {e}")
        return {'success': False, 'error': str(e)}


async def delete_received_credential(
    app: "LocksmithApplication",
    said: str,
) -> Dict[str, Any]:
    """Delete a received credential from the Weirwood server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/received-credentials/{urllib.parse.quote(said, safe='')}",
            method="DELETE",
        )

        if response is not None and response.status_code == 204:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error deleting received credential: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# TEL registrar
# ---------------------------------------------------------------------------

async def post_tel_event(
    app: "LocksmithApplication",
    raw_event: bytes,
) -> Dict[str, Any]:
    """
    POST a raw CESR-encoded TEL event to weirwood /registrar/tel-events.

    Returns dict with 'success' bool and, on success, 'data' containing the
    serialised TelEvent (including weirwood's 'receipt' cigar signature).
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path="/registrar/tel-events",
            method="POST",
            data=raw_event,
            headers={"Content-Type": "application/cesr"},
            timeout=30,
        )
        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error posting TEL event: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_tel_events(
    app: "LocksmithApplication",
    regk: str,
    vcid: Optional[str] = None,
) -> Dict[str, Any]:
    """
    GET TEL events for a registry prefix, optionally filtered to a credential SAID.

    Returns dict with 'success' bool and, on success, 'events' list.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        path = f"/registrar/tel-events/{urllib.parse.quote(regk, safe='')}"
        if vcid:
            path += f"/{urllib.parse.quote(vcid, safe='')}"
        response = await essr.request(path=path, method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching TEL events: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Intra-enterprise mailbox
# ---------------------------------------------------------------------------

async def post_message(
    app: "LocksmithApplication",
    recipient_aid: str,
    topic: str,
    raw: bytes,
    sender_aid: Optional[str] = None,
) -> Dict[str, Any]:
    """
    POST a CESR-encoded message to weirwood /messages.

    `sender_aid` is the whisper-uploaded identifier of the local participant.
    `recipient_aid` is the target group participant's whisper-uploaded AID.
    One call per recipient is required.

    Returns dict with 'success' bool and, on success, the stored Message doc.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not sender_aid:
        return {'success': False, 'error': 'No sender AID provided for message post'}

    try:
        params = (
            f"recipient={urllib.parse.quote(recipient_aid, safe='')}"
            f"&sender={urllib.parse.quote(sender_aid, safe='')}"
            f"&topic={urllib.parse.quote(topic, safe='')}"
        )
        response = await essr.request(
            path=f"/messages?{params}",
            method="POST",
            data=raw,
            headers={"Content-Type": "application/cesr"},
            timeout=30,
        )
        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error posting message: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_messages(
    app: "LocksmithApplication",
    aid: Optional[str] = None,
    topic: Optional[str] = None,
    unread_only: bool = True,
    page: int = 0,
    page_size: int = 50,
) -> Dict[str, Any]:
    """
    GET messages from weirwood /messages for the given AID.

    `aid` must be the whisper-uploaded identifier prefix; it is passed as an
    explicit query param so weirwood does not need to derive it from ESSR context.

    Returns dict with 'success' bool and, on success, 'messages' list.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not aid:
        return {'success': False, 'error': 'No AID provided for message fetch'}

    try:
        params = [f"aid={urllib.parse.quote(aid, safe='')}", f"page={page}", f"page_size={page_size}"]
        if topic:
            params.append(f"topic={urllib.parse.quote(topic, safe='')}")
        if unread_only:
            params.append("unread=true")
        path = f"/messages?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return {'success': False, 'error': str(e)}


async def mark_message_read(
    app: "LocksmithApplication",
    message_id: str,
) -> Dict[str, Any]:
    """Mark a weirwood mailbox message as read."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/messages/{urllib.parse.quote(message_id, safe='')}",
            method="PUT",
            json={},
        )
        if response is not None and response.status_code == 200:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error marking message read: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_backer(app: "LocksmithApplication") -> Dict[str, Any]:
    """
    GET /registrar/backer — fetch weirwood's non-transferable backer identifier.

    Returns the backer AID and its base64-encoded CESR KEL so whisper can:
      1. Include the backer AID in registry ``baks`` lists.
      2. Parse the KEL into the local Kevery for signature verification.

    Returns dict with 'success' bool and, on success, 'aid' and 'kel_b64'.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(path="/registrar/backer", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            return {'success': True, 'aid': data['aid'], 'kel_b64': data['kel_b64']}
        return {
            'success': False,
            'error': f"API error: {response.status_code if response else 'No response'}",
        }
    except Exception as e:
        logger.error(f"Error fetching weirwood backer: {e}")
        return {'success': False, 'error': str(e)}
