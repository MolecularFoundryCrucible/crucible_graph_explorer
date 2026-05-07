from flask import Blueprint, abort, current_app, render_template

INSTRUMENT_TYPES = ['team05']
URL_PREFIX = '/instrument-view/team05'

VIEWS = [
    {'label': 'Overview',          'url': '/overview',         'icon': 'bi-bar-chart'},
]



def create_blueprint(auth, helpers):
    bp = Blueprint('ncem_team', __name__)

    @bp.route('/overview')
    @auth.oidc_auth('orcid')
    def overview():
        instrument = current_app.crucible_client.instruments.get(instrument_name='team05')
        if not instrument:
           abort(404)
        #instrument_name = instrument.get('instrument_name', '')

        # TODO see if user has access to this instrument
        datasets = current_app.crucible_client.datasets.list(
            instrument_name='team05', limit=500
        )
        datasets.sort(key=lambda d: d.get('timestamp') or '', reverse=True)
        return render_template(
            'instrument_views/team05_overview.html',
            instrument=instrument,
            datasets=datasets,
        )

    return bp
