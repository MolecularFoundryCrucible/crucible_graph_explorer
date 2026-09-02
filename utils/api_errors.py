from flask import jsonify
from requests import exceptions as requests_exceptions


def _format_detail(detail):
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        messages = []
        for item in detail:
            if not isinstance(item, dict):
                messages.append(str(item))
                continue
            location = '.'.join(str(part) for part in item.get('loc', []))
            message = item.get('msg') or item.get('message') or str(item)
            messages.append(f'{location}: {message}' if location else message)
        return '; '.join(messages)
    if isinstance(detail, dict):
        return detail.get('message') or detail.get('error') or str(detail)
    return str(detail) if detail is not None else None


def api_error_payload(exc):
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    detail = None

    if response is not None:
        try:
            body = response.json()
        except (ValueError, TypeError):
            body = None
        if isinstance(body, dict):
            detail = body.get('detail') or body.get('message') or body.get('error')

    if not isinstance(status, int) or status < 400 or status > 599:
        if isinstance(exc, requests_exceptions.Timeout):
            status = 504
        elif isinstance(exc, requests_exceptions.ConnectionError):
            status = 502
        else:
            status = 500

    message = _format_detail(detail) or str(exc) or 'API request failed'
    payload = {'error': message}
    if detail is not None:
        payload['detail'] = detail
    return payload, status


def api_error_response(exc):
    payload, status = api_error_payload(exc)
    return jsonify(payload), status


def validation_error_response(exc):
    detail = exc.errors(include_url=False, include_context=False)
    return jsonify({
        'error': _format_detail(detail),
        'detail': detail,
    }), 422
