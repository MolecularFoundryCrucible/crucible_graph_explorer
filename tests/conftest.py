import os

import flask_pyoidc

os.environ['CRUCIBLE_API_URL'] = 'https://crucible.lbl.gov/api/v3'
os.environ.setdefault('PYOIDC_SECRET', 'test-secret')


class StubOIDCAuthentication:
    def __init__(self, *args, **kwargs):
        pass

    def oidc_auth(self, *args, **kwargs):
        return lambda func: func

    def error_view(self, func):
        return func


def pytest_configure():
    flask_pyoidc.OIDCAuthentication = StubOIDCAuthentication
