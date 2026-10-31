"""Background batches use controlled responses and isolated saved data only."""
from conftest import save_test_diagnosis
import json
import threading
import time
from pathlib import Path

import pytest
from app import core
from app.batch_jobs import BatchJobs
from app.models import ProviderFailure


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA', str(tmp_path))
    monkeypatch.setenv('SCRIPTED_MODEL', '1')
    for name in ('RUN_BUDGET', 'RUN_TURN_CAP', 'FETCH_FAILURES', 'SCRIPTED_VARIANT'):
        monkeypatch.delenv(name, raising=False)
    return core.create_app().test_client()


def wait_finished(client, job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get('/api/batch-jobs/' + job_id)
        assert response.status_code == 200
        if response.json['status'] not in ('queued', 'running'):
            # Terminal status is written before the worker releases the gate.
            gate = client.application.extensions['batch_jobs'].gate
            assert gate.acquire(timeout=2)
            gate.release()
            return response.json
        time.sleep(.01)
    pytest.fail('Background batch did not finish')


def test_start_returns_before_work_finishes_and_guards_mutations(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def controlled(store, label, progress=None, cancelled=None):
        calls.append(label)
        progress(2, 5)
        entered.set()
        assert release.wait(5)
        return {'runs': 5, 'graded': 5, 'grader_errors': 0}
    monkeypatch.setattr(core, 'batch_run', controlled)
    try:
        response = client.post('/api/batch-jobs', json={'label': 'v1'})
        assert response.status_code == 202 and entered.wait(2)
        job_id = response.json['id']
        assert client.get('/api/batch-jobs/'+job_id).json['completed'] == 2
        duplicate = client.post('/api/batch-jobs', json={'label': 'v1'})
        assert duplicate.status_code == 202 and duplicate.json['id'] == job_id
        assert client.get('/api/batch-jobs/latest?label=v1').json['id'] == job_id
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/readiness').status_code == 200
        # Existing synchronous API, settings, tickets, instructions, and comparisons share the gate.
        for route in ('/api/batches', '/api/model-config', '/api/tickets',
                      '/api/tickets/REV-100/close', '/api/pages/page-req-avatar-upload/save',
                      '/api/learning/approve', '/api/learning/compare', '/api/batches/v1/analyze'):
            assert client.post(route, json={}).status_code == 409, route
        jobs = client.application.extensions['batch_jobs']
        with pytest.raises(FileExistsError):
            jobs.start('v2', 5, lambda progress: {})
        assert calls == ['v1']
    finally:
        release.set()
    assert wait_finished(client, job_id)['status'] == 'completed'
    assert client.post('/api/tickets/REV-100/close').status_code == 200


def test_validation_and_read_only_lookup(client, tmp_path):
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert client.get('/api/batch-jobs/latest?label=v1').json is None
    assert client.get('/api/batch-jobs/missing').status_code == 404
    assert client.post('/api/batch-jobs', json={'label': '../bad'}).status_code == 400
    assert client.post('/api/batch-jobs', json={'label': 'v2'}).status_code == 400
    assert before == {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_provider_failure_is_safe_and_retry_reuses_saved_reviews(client, monkeypatch, tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY', 'secret-api-key')
    original = core.run_analysis
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(kwargs['doc_name'])
        if len(calls) == 2:
            raise ProviderFailure('secret-api-key provider response')
        return original(*args, **kwargs)
    monkeypatch.setattr(core, 'run_analysis', fail_second)
    first = client.post('/api/batch-jobs', json={'label': 'v1'}).json
    failed = wait_finished(client, first['id'])
    assert failed['status'] == 'failed' and failed['completed'] == 1
    assert 'provider' in failed['error'] and 'secret' not in failed['error']
    saved = next((tmp_path/'batches/v1').glob('run_01*.json'))
    content = saved.read_bytes()
    monkeypatch.setattr(core, 'run_analysis', original)
    retry = client.post('/api/batch-jobs', json={'label': 'v1'})
    assert retry.status_code == 202 and retry.json['id'] != first['id']
    done = wait_finished(client, retry.json['id'])
    assert done['status'] == 'completed' and done['completed'] == 5
    assert saved.read_bytes() == content
    assert client.post('/api/batch-jobs', json={'label': 'v1'}).status_code == 409
    assert 'secret' not in ''.join(p.read_text() for p in (tmp_path/'batch-jobs').glob('*.json'))


def test_grader_errors_offer_retry(client, monkeypatch):
    def incomplete(store, label, progress=None, cancelled=None):
        progress(5, 5)
        return {'runs': 5, 'graded': 4, 'grader_errors': 1}
    monkeypatch.setattr(core, 'batch_run', incomplete)
    job = client.post('/api/batch-jobs', json={'label':'v1'}).json
    done = wait_finished(client, job['id'])
    assert done['status'] == 'failed' and 'Retry' in done['error']


def test_restart_marks_unfinished_jobs_and_keeps_evidence(client, tmp_path):
    folder = tmp_path/'batch-jobs'
    folder.mkdir()
    job = {'id':'old', 'label':'v1', 'status':'running', 'completed':2, 'total':5,
           'error':None, 'created_at':'2026-10-21T00:00:00+00:00'}
    (folder/'old.json').write_text(json.dumps(job))
    before = (tmp_path/'tickets.json').read_bytes()
    restarted = core.create_app().test_client()
    status = restarted.get('/api/batch-jobs/old').json
    assert status['status'] == 'interrupted' and status['completed'] == 2
    assert 'Retry' in status['error']
    assert (tmp_path/'tickets.json').read_bytes() == before
    assert restarted.get('/api/batch-jobs/latest?label=v1').json == status


def test_sync_endpoint_holds_the_same_guard(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def controlled(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {'runs':5, 'graded':5}
    monkeypatch.setattr(core, 'batch_run', controlled)
    responses=[]
    thread=threading.Thread(target=lambda: responses.append(client.application.test_client().post('/api/batches', json={'label':'v1'})))
    thread.start()
    try:
        assert entered.wait(2)
        assert client.post('/api/batch-jobs', json={'label':'v1'}).status_code == 409
    finally:
        release.set(); thread.join(5)
    assert responses[0].status_code == 201


def test_capstone_setup_starts_existing_app_without_customization():
    spec=(Path(core.ROOT)/'spec.coding-agent-lab.md').read_text()
    assert 'There are no customization questions' in spec
    assert 'Leave app/learning_agent.py unfinished' in spec
    assert 'Setup is complete. Open App Preview and build your analyst in Step 1.' in spec


def test_async_v1_approval_v2_and_saved_comparison(client, tmp_path, reviewer):
    first = client.post('/api/batch-jobs', json={'label':'v1'})
    assert first.status_code == 202
    assert wait_finished(client, first.json['id'])['status'] == 'completed'
    v1_before = (tmp_path/'batches/v1/summary.json').read_bytes()
    save_test_diagnosis()
    assert client.post('/api/batches/v1/analyze', json={}).status_code == 200
    assert client.post('/api/learning/approve', json={'label':'v1'}).status_code == 200
    second = client.post('/api/batch-jobs', json={'label':'v2'})
    assert second.status_code == 202
    done = wait_finished(client, second.json['id'])
    assert done['status'] == 'completed' and done['completed'] == done['total'] == 5
    comparison = client.post('/api/learning/compare', json={'before':'v1', 'after':'v2'})
    assert comparison.status_code == 200 and comparison.json['verdict'] == 'success'
    assert (tmp_path/'batches/v1/summary.json').read_bytes() == v1_before
    assert json.loads((tmp_path/'batches/v2/comparison.json').read_text()) == comparison.json
    restarted = core.create_app().test_client()
    assert restarted.get('/api/batch-jobs/'+done['id']).json['status'] == 'completed'
