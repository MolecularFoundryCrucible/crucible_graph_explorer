"""Open-in-Hyperspec integration.

Hands a Crucible dataset file to the Hyperspec app (Cloud Run, same GCP
project) without any browser download/upload.

Trust chain
-----------
1. The user is ORCiD-authenticated here; authorization for the file is
   delegated to the Crucible API by using the *user's own* API key
   (get_user_client) — the admin key is never used for file access.
2. The file is copied server-side from mf-storage-prod into Hyperspec's
   bucket under incoming/<uuid>/ — this service account only needs
   write-only (objectCreator) access there. If the copy is denied, we fall
   back to passing the 1-hour signed download URL instead.
3. The browser is redirected to {HYPERSPEC_URL}/import?token=... where the
   token is a short-lived (Hyperspec enforces max_age) itsdangerous
   signature over {orcid, name, object|signed_url, filename, crucible_dsid}
   using the shared secret HYPERSPEC_SSO_SECRET. Hyperspec derives the
   user's identity and storage namespace exclusively from this token.
"""

import logging
import os
import uuid

import flask
import fsspec
from flask import Blueprint, abort, jsonify
from flask_pyoidc.user_session import UserSession
from itsdangerous import URLSafeTimedSerializer

from utils.auth import get_user_client

logger = logging.getLogger(__name__)

HYPERSPEC_URL = os.getenv('HYPERSPEC_URL', '').rstrip('/')
HYPERSPEC_SSO_SECRET = os.getenv('HYPERSPEC_SSO_SECRET', '')
HYPERSPEC_BUCKET = os.getenv('HYPERSPEC_BUCKET', 'app-hyperspec')

# File types Hyperspec can process (see hyperspec's precompute.process_h5)
HYPERSPEC_EXTENSIONS = ('.h5', '.mat')


def is_enabled() -> bool:
    return bool(HYPERSPEC_URL and HYPERSPEC_SSO_SECRET)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(HYPERSPEC_SSO_SECRET, salt='hyperspec-sso')


def _current_user():
    """Return (orcid, display_name) for the logged-in session."""
    userinfo = UserSession(flask.session).userinfo
    orcid = userinfo['sub']
    name = (userinfo.get('name')
            or (userinfo.get('given_name', '') + ' ' + userinfo.get('family_name', '')).strip()
            or orcid)
    return orcid, name


def create_blueprint(auth):
    bp = Blueprint('hyperspec', __name__)

    @bp.app_context_processor
    def inject_hyperspec_enabled():
        return {'hyperspec_enabled': is_enabled(),
                'hyperspec_extensions': HYPERSPEC_EXTENSIONS}

    @bp.route("/<project_id>/datasets/<dsid>/files/<mfid>/open-in-hyperspec",
              methods=['POST'])
    @auth.oidc_auth('orcid')
    def open_in_hyperspec(project_id, dsid, mfid):
        if not is_enabled():
            return jsonify({'error': 'Hyperspec integration is not configured'}), 503

        client = get_user_client()
        orcid, name = _current_user()

        # Authorization gate: the file record is fetched with the user's own
        # API key, so the Crucible API enforces project membership here.
        files = client.datasets.get_associated_files(dsid)
        frec = next((f for f in files if f.get('mfid') == mfid), None)
        if frec is None:
            abort(404)
        storage_path = frec.get('storage_path')
        if not storage_path:
            return jsonify({'error': 'File has not been ingested yet'}), 409
        basename = os.path.basename(frec.get('filename') or storage_path)
        if not basename.lower().endswith(HYPERSPEC_EXTENSIONS):
            return jsonify({'error': 'Only .h5 / .mat files can be opened in Hyperspec'}), 400

        payload = {
            'orcid': orcid,
            'name': name,
            'filename': basename,
            'crucible_dsid': dsid,
        }

        # Preferred path: server-side GCS copy into Hyperspec's bucket.
        try:
            object_name = f'incoming/{uuid.uuid4()}/{basename}'
            fsspec.filesystem('gcs').copy(storage_path,
                                          f'{HYPERSPEC_BUCKET}/{object_name}')
            payload['object'] = object_name
        except Exception as err:
            logger.warning("GCS copy to hyperspec bucket failed (%s); "
                           "falling back to signed URL", err)
            try:
                payload['signed_url'] = client.files.get_download_link(mfid)
            except Exception as err2:
                logger.error("signed URL fallback also failed for %s: %s", mfid, err2)
                return jsonify({'error': 'Could not make the file available to Hyperspec'}), 502

        token = _serializer().dumps(payload)
        return jsonify({'url': f'{HYPERSPEC_URL}/import?token={token}'})

    @bp.route('/hyperspec/sso')
    @auth.oidc_auth('orcid')
    def hyperspec_sso():
        """Login-only bounce: lets Hyperspec re-establish a session for a user
        who is logged in here, without transferring any file."""
        if not is_enabled():
            abort(404)
        orcid, name = _current_user()
        token = _serializer().dumps({'orcid': orcid, 'name': name})
        return flask.redirect(f'{HYPERSPEC_URL}/import?token={token}')

    return bp
