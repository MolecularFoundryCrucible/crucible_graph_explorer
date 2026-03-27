from flask import Blueprint, current_app, render_template

INSTRUMENT_TYPES = ['Nirvana']
URL_PREFIX = '/instrument-view/nirvana'
VIEWS = [{'label': 'Dataset List', 'url': '/overview'}]


def create_blueprint(auth, helpers):
    bp = Blueprint('iview_nirvana', __name__)

    @bp.route('/overview')
    @auth.oidc_auth('orcid')
    def view():
        instrument = current_app.crucible_client.get_instrument(instrument_id='nirvana')
        #if not instrument:
        #    abort(404)
        #instrument_name = instrument.get('instrument_name', '')
        datasets = current_app.crucible_client.list_datasets(
            instrument_name='nirvana spectrometer', limit=500
        )
        datasets.sort(key=lambda d: d.get('timestamp') or '', reverse=True)
        return render_template(
            'instrument_views/nirvana.html',
            instrument=instrument,
            datasets=datasets,
        )

    return bp
