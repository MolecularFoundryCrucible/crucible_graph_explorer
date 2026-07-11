"""
Pluggable dataset views, keyed by measurement type.

Each module in this package provides a custom view for one or more dataset
measurement types.  To add a view for a new measurement type, drop a file
into this directory.  It must expose:

    MEASUREMENT_TYPES : list[str]
        The measurement type strings this module handles.

    URL_PREFIX : str
        The blueprint URL prefix, e.g. '/dataset-view/mdnote'.

    LABEL : str
        Short display label for the link shown on the dataset page.

    create_blueprint(auth, helpers) -> flask.Blueprint
        Factory that returns a configured Blueprint.  Routes inside should
        follow the pattern /<project_id>/<dsid>.

    DATA_TYPE_STEMS : list[str]  (optional)
        data_type stems this module handles, e.g.
        'ScopeFoundryH5.qspleem_sv_ramp'.  A dataset whose data_type is that
        stem plus a '.subform' suffix routes to this view.  Coexists with
        MEASUREMENT_TYPES for backward compatibility.

Available helpers
-----------------
    is_user_in_project(project_id)
    get_project(project_id, include_metadata=False)
"""

import importlib
import pkgutil
from pathlib import Path

# Maps measurement_type -> list of {url_prefix, label}
_registry: dict = {}

# Maps data_type stem (data_type minus its trailing .subform) -> list of {url_prefix, label}.
# Lets viewers route on the technical data_type (e.g. 'ScopeFoundryH5.qspleem_sv_ramp')
# in addition to the human-readable measurement.
_registry_by_dtype_stem: dict = {}


def register_all(app, auth, helpers):
    """Auto-discover and register every dataset view blueprint."""
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        try:
            module = importlib.import_module(f'views.datasets.{name}')
        except Exception as err:
            app.logger.error(f'dataset_views: failed to import {name}: {err}')
            continue
        if not (hasattr(module, 'create_blueprint') and hasattr(module, 'MEASUREMENT_TYPES')):
            continue
        try:
            bp = module.create_blueprint(auth, helpers)
            prefix = module.URL_PREFIX
            app.register_blueprint(bp, url_prefix=prefix)
            entry = {
                'url_prefix': prefix,
                'label': getattr(module, 'LABEL', module.MEASUREMENT_TYPES[0]),
            }
            for mtype in module.MEASUREMENT_TYPES:
                _registry.setdefault(mtype, []).append(entry)
            for stem in getattr(module, 'DATA_TYPE_STEMS', []):
                _registry_by_dtype_stem.setdefault(stem, []).append(entry)
            app.logger.info(f'dataset_views: registered {name!r} → {module.MEASUREMENT_TYPES} at {prefix}')
        except Exception as err:
            app.logger.error(f'dataset_views: failed to register {name}: {err}')

    app.logger.info(f'dataset_views registry: { {k: [e["label"] for e in v] for k, v in _registry.items()} }')


def get_views(measurement: str, data_type: str, project_id: str, dsid: str) -> list:
    """Return all custom view dicts for a dataset, each with 'url' and 'label'.

    Matches on both the human-readable ``measurement`` and, when present, the
    ``data_type`` stem (``data_type`` minus its trailing ``.subform``), so a
    dataset routes correctly under either the old measurement-keyed scheme or
    the new data_type scheme.  Deduplicated by url_prefix.
    """
    entries = list(_registry.get(measurement, []))
    if data_type:
        stem = data_type.rsplit('.', 1)[0]
        entries += _registry_by_dtype_stem.get(stem, [])
    seen, out = set(), []
    for entry in entries:
        if entry['url_prefix'] in seen:
            continue
        seen.add(entry['url_prefix'])
        out.append({'url': f"{entry['url_prefix']}/{project_id}/{dsid}", 'label': entry['label']})
    return out
