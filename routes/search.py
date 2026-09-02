import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import flask
from flask import Blueprint, abort, render_template, request
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import is_user_in_project

logger = logging.getLogger(__name__)


def _global_search_results(client, query):
    results = {
        'projects': [],
        'samples': [],
        'datasets': [],
        'instruments': [],
    }
    failures = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(client.projects.search, query, limit=20): 'projects',
            executor.submit(client.samples.search, query, limit=20): 'samples',
            executor.submit(client.datasets.search, query, limit=20): 'datasets',
            executor.submit(client.instruments.search, query, limit=20): 'instruments',
        }
        for future in as_completed(futures):
            resource_type = futures[future]
            try:
                records = future.result() or []
            except Exception as exc:
                logger.warning("global_search: %s search failed: %s", resource_type, exc)
                failures.append(resource_type)
                continue
            for record in records:
                if resource_type == 'projects':
                    project_id = record.get('project_id')
                    if not project_id:
                        continue
                    url = f'/{project_id}/'
                elif resource_type == 'instruments':
                    instrument_mfid = record.get('unique_id')
                    if not instrument_mfid:
                        continue
                    url = f'/instrument/{instrument_mfid}'
                else:
                    project_id = record.get('project_id')
                    resource_id = record.get('unique_id')
                    if not project_id or not resource_id:
                        continue
                    url = f'/{project_id}/{resource_type}/{resource_id}'
                results[resource_type].append({
                    **record,
                    '_url': url,
                })
    return results, sorted(failures)


def _project_search_results(client, query, project_id):
    results = {'samples': [], 'datasets': []}
    failures = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(
                client.samples.search,
                query,
                project_id=project_id,
                limit=20,
            ): 'samples',
            executor.submit(
                client.datasets.search,
                query,
                project_id=project_id,
                limit=20,
            ): 'datasets',
        }
        for future in as_completed(futures):
            resource_type = futures[future]
            try:
                results[resource_type] = future.result() or []
            except Exception as exc:
                logger.warning(
                    "project_search: %s search failed for %s: %s",
                    resource_type,
                    project_id,
                    exc,
                )
                failures.append(resource_type)
    return results, sorted(failures)


def create_blueprint(auth):
    bp = Blueprint('search', __name__)

    @bp.route("/search")
    @auth.oidc_auth('orcid')
    def global_search():
        client = get_user_client()
        q = request.args.get('q', '').strip()

        results = {
            'projects': [],
            'samples': [],
            'datasets': [],
            'instruments': [],
        }
        search_message = None
        if q and len(q) < 3:
            search_message = 'Enter at least 3 characters.'
        elif q:
            results, failures = _global_search_results(client, q)
            if failures:
                search_message = 'Some search results could not be loaded.'

        return render_template('global_search.html',
                               q=q,
                               project_results=results['projects'],
                               sample_results=results['samples'],
                               dataset_results=results['datasets'],
                               instrument_results=results['instruments'],
                               search_message=search_message)

    @bp.route("/<project_id>/search")
    @auth.oidc_auth('orcid')
    def project_search(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        if not is_user_in_project(project_id, orcid):
            abort(403)

        q = request.args.get('q', '').strip()
        results = {'samples': [], 'datasets': []}
        search_message = None
        if q and len(q) < 3:
            search_message = 'Enter at least 3 characters.'
        elif q:
            results, failures = _project_search_results(
                get_user_client(),
                q,
                project_id,
            )
            if failures:
                search_message = 'Some search results could not be loaded.'

        return render_template('search.html',
                               pc={'project_id': project_id},
                               q=q,
                               sample_results=results['samples'],
                               dataset_results=results['datasets'],
                               search_message=search_message)

    return bp
