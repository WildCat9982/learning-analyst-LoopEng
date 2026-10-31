"""Bounded exception diagnostics; never persist request objects or tracebacks."""
import os
import re


def safe_message(value):
    text = str(value)
    secrets = [value for key, value in os.environ.items() if value and
               any(s in key.upper() for s in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET', 'BASE_URL', 'API_BASE'))]
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, '[redacted]')
    text = re.sub(r'https?://\S+|Bearer\s+\S+|sk-[\w-]+', '[redacted]', text, flags=re.I)
    text = re.sub(r'''(?i)(["']?(?:api[_-]?key|authorization|access[_-]?token|password|secret)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''',
                  r'\1[redacted]', text)
    return re.sub(r'\s+', ' ', text).strip()[:400]


def exception_details(error, kind='local'):
    saved = getattr(error, 'diagnostics', None)
    if isinstance(saved, dict):
        return saved
    chain, seen = [], set()
    current = error
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        status = getattr(current, 'status_code', None)
        chain.append({'exception_type': type(current).__name__, 'message': safe_message(current),
                      'http_status': status if isinstance(status, int) and 100 <= status <= 599 else None})
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return {'kind': kind, **chain[0], 'causes': chain[1:]}


def is_provider_error(error):
    # A local tool/runtime exception is not evidence of an API failure.
    from openai import APIError
    from httpx import HTTPError
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (APIError, HTTPError)):
            return True
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return False


def failure_text(details):
    label = 'Model API failure' if details['kind'] == 'provider' else 'Local execution failure'
    status = next((item['http_status'] for item in [details, *details['causes']] if item['http_status']), None)
    prefix = f"{label} ({details['exception_type']}" + (f', HTTP {status}' if status else '') + ')'
    text = prefix + ': ' + details['message']
    if details['causes']:
        cause = details['causes'][0]
        text += f" Cause: {cause['exception_type']}: {cause['message']}"
    return text
