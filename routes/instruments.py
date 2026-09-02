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

    @bp.route("/instrument/<instrument_mfid>")
    @auth.oidc_auth('orcid')
    def instrument_detail(instrument_mfid):
        import views.instruments as instrument_views
        client = get_user_client()
        instrument = client.instruments.get(
            instrument_mfid=instrument_mfid,
            include_metadata=True,
        )
        if not instrument:
            abort(404)
        instrument_name = instrument.get('instrument_name', '')
        custom_views = instrument_views.get_views(instrument_name, instrument_mfid)
        recent_datasets = []
        dataset_total = 0
        try:
            recent_datasets = client.datasets.list(
                instrument_mfid=instrument_mfid,
                limit=50,
            )
        except Exception as exc:
            logger.warning(
                "Could not load datasets for instrument %s: %s",
                instrument_mfid,
                exc,
            )
        try:
            dataset_total = client.datasets.count(instrument_mfid=instrument_mfid)
        except Exception as exc:
            logger.warning(
                "Could not count datasets for instrument %s: %s",
                instrument_mfid,
                exc,
            )
            dataset_total = len(recent_datasets)
        return render_template('instrument.html', instrument=instrument,
                               custom_views=custom_views,
                               recent_datasets=recent_datasets,
                               dataset_total=dataset_total)

    @bp.route("/api/instruments")
    @auth.oidc_auth('orcid')
    def api_instruments_json():
        instruments = get_user_client().instruments.list(limit=None)
        return jsonify([
            {
                'mfid': i.get('unique_id', ''),
                'instrument_id': i.get('instrument_id', ''),
                'name': i.get('instrument_name', ''),
            }
            for i in instruments
            if i.get('instrument_name') and i.get('instrument_id')
        ])

    return bp
