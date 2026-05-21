import logging

import flask
from flask import Blueprint, abort, render_template, jsonify

from utils.auth import get_user_client

logger = logging.getLogger(__name__)


def create_blueprint(auth):
    bp = Blueprint('instruments_routes', __name__)

    @bp.route("/instruments/")
    @auth.oidc_auth('orcid')
    def instrument_list():
        instruments = get_user_client().instruments.list(limit=None)
        return render_template('instrument_list.html', instruments=instruments)

    @bp.route("/instrument/<instrument_id>")
    @auth.oidc_auth('orcid')
    def instrument_detail(instrument_id):
        import views.instruments as instrument_views
        client = get_user_client()
        instrument = client.instruments.get(instrument_id=instrument_id, include_metadata=True)
        if not instrument:
            abort(404)
        instrument_name = instrument.get('instrument_name', '')
        custom_views = instrument_views.get_views(instrument_name, instrument_id)
        recent_datasets = []
        if instrument_name:
            try:
                recent_datasets = client.datasets.list(instrument_name=instrument_name, limit=None)
                recent_datasets.sort(key=lambda d: d.get('timestamp') or '', reverse=True)
            except Exception:
                recent_datasets = []
        return render_template('instrument.html', instrument=instrument,
                               custom_views=custom_views, recent_datasets=recent_datasets)

    @bp.route("/api/instruments")
    @auth.oidc_auth('orcid')
    def api_instruments_json():
        instruments = get_user_client().instruments.list(limit=None)
        return jsonify([
            {'name': i.get('instrument_name', ''), 'id': i.get('unique_id', '')}
            for i in instruments
            if i.get('instrument_name')
        ])

    return bp
