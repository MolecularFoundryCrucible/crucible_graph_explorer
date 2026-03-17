"""
Pluggable instrument views, keyed by instrument name/type.

Each module in this package provides a custom view for one or more instruments.
To add a view for a new instrument, drop a file into this directory.  It must
expose:

    INSTRUMENT_TYPES : list[str]
        The instrument name strings this module handles (e.g. ['Pollux']).

    URL_PREFIX : str
        The blueprint URL prefix, e.g. '/instrument-view/pollux'.

    VIEWS : list[dict]
        List of view entries, each with 'label' and 'url' (relative to URL_PREFIX).
        e.g. [{'label': 'Dataset List', 'url': '/overview'}]

    create_blueprint(auth, helpers) -> flask.Blueprint
        Factory that returns a configured Blueprint.  Routes inside use fixed
        paths (no instrument_id parameter) since each module is instrument-specific.

Available helpers
-----------------
    is_user_in_project(project_id)
    get_project(project_id, include_metadata=False)
"""

import importlib
import pkgutil
from pathlib import Path

# Maps instrument_name -> list of {label, url, icon}
_registry: dict = {}


def register_all(app, auth, helpers):
    """Auto-discover and register every instrument view blueprint."""
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        try:
            module = importlib.import_module(f'instrument_views.{name}')
        except Exception as err:
            app.logger.error(f'instrument_views: failed to import {name}: {err}')
            continue
        if not (hasattr(module, 'create_blueprint') and hasattr(module, 'INSTRUMENT_TYPES')):
            continue
        try:
            bp = module.create_blueprint(auth, helpers)
            prefix = module.URL_PREFIX
            app.register_blueprint(bp, url_prefix=prefix)
            for inst_type in module.INSTRUMENT_TYPES:
                if hasattr(module, 'VIEWS'):
                    _registry[inst_type] = [
                        {**v, 'url': prefix + v['url']} for v in module.VIEWS
                    ]

            app.logger.info(
                f'instrument_views: registered {name!r} -> {module.INSTRUMENT_TYPES} at {prefix}'
            )
        except Exception as err:
            app.logger.error(f'instrument_views: failed to register {name}: {err}')

    app.logger.info(
        f'instrument_views registry: { {k: [e["label"] for e in v] for k, v in _registry.items()} }'
    )


def get_views(instrument_name: str, instrument_id: str) -> list:
    """Return all custom view dicts for an instrument, each with 'url' and 'label'."""
    print("inst get_views", _registry.get(instrument_name, []))
    # return [
    #     {'url': f"{entry['url_prefix']}/", 'label': entry['label']}
    #     for entry in _registry.get(instrument_name, [])
    # ]
    return _registry.get(instrument_name,[])

