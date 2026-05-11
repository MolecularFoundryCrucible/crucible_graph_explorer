"""
Pluggable project-specific views.

Each module in this package provides views for one project.  To add views for
a new project, drop a file named <project_id>.py into this directory.  It must
expose:

    PROJECT_ID : str
        The project identifier (used as the url_prefix /<PROJECT_ID>/view).

    create_blueprint(auth, helpers) -> flask.Blueprint
        Factory that receives the OIDC auth object and a dict of shared helper
        functions, and returns a configured Blueprint.

Available helpers
-----------------
    get_project(project_id, include_metadata=False)
    is_user_in_project(project_id)
    get_project_graph(project_id)
    get_entity_graph_nx(entity_id)
"""

import importlib
import pkgutil
from pathlib import Path

# Maps project_id -> list of {label, url, icon} with absolute URLs
_registry: dict = {}


def register_all(app, auth, helpers):
    """Auto-discover and register every project view blueprint."""
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        module = importlib.import_module(f'views.projects.{name}')
        if hasattr(module, 'create_blueprint') and hasattr(module, 'PROJECT_ID'):
            bp = module.create_blueprint(auth, helpers)
            prefix = f'/{module.PROJECT_ID}/view'
            app.register_blueprint(bp, url_prefix=prefix)
            app.logger.info(f'Registered project views: {module.PROJECT_ID}')
            if hasattr(module, 'VIEWS'):
                _registry[module.PROJECT_ID] = [
                    {**v, 'url': prefix + v['url']} for v in module.VIEWS
                ]


def get_views(project_id: str) -> list:
    """Return the list of custom view dicts for a project, or [] if none."""
    return _registry.get(project_id, [])
