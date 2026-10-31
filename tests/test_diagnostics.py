"""Safe failure classification without any provider requests."""
import json
import time

import httpx
import pytest
from openai import APIConnectionError, RateLimitError
from app import core, engine, models
from app.diagnostics import exception_details, failure_text, safe_message


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA', str(tmp_path))
    monkeypatch.setenv('SCRIPTED_MODEL', '0')
    monkeypatch.setenv('OPENAI_API_KEY', 'private-test-key')


def api_error():
    response = httpx.Response(429, request=httpx.Request('POST', 'https://private.example/v1'))
    return RateLimitError('Monthly quota exhausted; api_key=private-test-key https://private.example/v1',
                          response=response, body={'error': {'message': 'Monthly quota exhausted'}})


def test_api_status_type_and_safe_message():
    failure = models.provider_failure('review', api_error())
    assert isinstance(failure, models.ProviderFailure)
    detail = exception_details(failure)
    assert detail['kind'] == 'provider' and detail['exception_type'] == 'RateLimitError'
    assert detail['http_status'] == 429 and 'quota' in detail['message']
    assert 'HTTP 429' in failure_text(detail)
    assert 'private-test-key' not in json.dumps(detail)
    assert 'https://' not in json.dumps(detail)


def test_local_failure_preserves_cause_and_is_not_provider():
    try:
        try:
            raise FileNotFoundError('Missing workspace file; password="hidden-password"')
        except FileNotFoundError as cause:
            raise RuntimeError('Cannot read draft') from cause
    except RuntimeError as error:
        failure = models.provider_failure('review', error)
    assert isinstance(failure, models.ExecutionFailure)
    detail = exception_details(failure)
    assert detail['kind'] == 'local' and detail['exception_type'] == 'RuntimeError'
    assert detail['http_status'] is None
    assert detail['causes'][0]['exception_type'] == 'FileNotFoundError'
    assert 'hidden-password' not in json.dumps(detail)
    assert 'Local execution failure' in str(failure)


def test_connection_failure_without_http_status():
    error = APIConnectionError(request=httpx.Request('POST', 'https://private.example'))
    failure = models.provider_failure('review', error)
    detail = exception_details(failure)
    assert detail['kind'] == 'provider' and detail['exception_type'] == 'APIConnectionError'
    assert detail['http_status'] is None


@pytest.mark.parametrize('error', [RuntimeError('Local execution problem'), api_error()])
def test_review_invocation_classifies_actual_exception(monkeypatch, tmp_path, error):
    class Agent:
        def invoke(self, *args, **kwargs):
            raise error
    monkeypatch.setattr(engine, 'build_review_agent', lambda *a: Agent())
    expected = models.ProviderFailure if isinstance(error, RateLimitError) else models.ExecutionFailure
    with pytest.raises(expected) as caught:
        engine.execute_review(tmp_path, 'Requirement', 3, 40, 0)
    assert caught.value.diagnostics['exception_type'] == type(error).__name__


@pytest.mark.parametrize('error, kind', [(RuntimeError('Tool execution failed'), 'local'), (api_error(), 'provider')])
def test_job_persists_safe_details_and_read_status_survives_restart(monkeypatch, tmp_path, error, kind):
    def fail(store, label, progress=None, cancelled=None):
        progress(4, 5)
        raise models.provider_failure('review', error) from error
    monkeypatch.setattr(core, 'batch_run', fail)
    app = core.create_app()
    client = app.test_client()
    started = client.post('/api/batch-jobs', json={'label':'v1'})
    assert started.status_code == 202
    job_id = started.json['id']
    for _ in range(200):
        job = client.get('/api/batch-jobs/'+job_id).json
        if job['status'] == 'failed': break
        time.sleep(.01)
    assert job['status'] == 'failed' and job['completed'] == 4
    assert job['error_details']['kind'] == kind
    assert type(error).__name__ in job['error']
    assert 'private-test-key' not in json.dumps(job)
    assert 'https://' not in json.dumps(job)
    gate = app.extensions['batch_jobs'].gate
    assert gate.acquire(timeout=2)
    gate.release()
    saved = json.loads((tmp_path/'batch-jobs'/f'{job_id}.json').read_text())
    assert saved == job
    assert core.create_app().test_client().get('/api/batch-jobs/'+job_id).json == job


def test_sanitizer_redacts_credentials_and_bounds_message(monkeypatch):
    monkeypatch.setenv('CUSTOM_TOKEN', 'unusual credential with spaces')
    message = ('private-test-key unusual credential with spaces '
               'Bearer bearer-value sk-exampletoken https://private.example '
               '"api_key": "other-key" password=other-password ' + 'x'*600)
    safe = safe_message(message)
    for secret in ('private-test-key', 'unusual credential', 'bearer-value', 'sk-exampletoken',
                   'https://', 'other-key', 'other-password'):
        assert secret not in safe
    assert len(safe) <= 400
