from conftest import save_test_diagnosis
"""Live adapter fault paths with local responses, never a paid provider."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from app import core, models


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA', str(tmp_path))
    monkeypatch.setenv('SCRIPTED_MODEL', '1')
    for key in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'REVIEW_MODEL', 'GRADER_MODEL',
                'ANALYST_MODEL', 'SCRIPTED_VARIANT', 'WORKSPACE_ROOT'):
        monkeypatch.delenv(key, raising=False)


def evaluation(evidence='L1: saved fact', names=models.CRITERIA):
    return models.Evaluation(criteria=[
        models.Criterion(name=n, passed=True, evidence=evidence) for n in names])


def test_reordered_criteria_are_normalized(monkeypatch):
    monkeypatch.setattr(models, 'structured', lambda *a: evaluation(names=models.CRITERIA[::-1]))
    result = models.evaluate('saved fact', 'requirement', 'rubric')
    assert [c['name'] for c in result['criteria']] == list(models.CRITERIA)


def test_multiple_exact_evidence_lines_are_accepted(monkeypatch):
    evidence = 'L1: saved fact\nL2: another fact'
    monkeypatch.setattr(models, 'structured', lambda *a: evaluation(evidence))
    result = models.evaluate('saved fact\nanother fact', 'requirement', 'rubric')
    assert result['result'] == 'satisfied'
    assert all(c['evidence'] == evidence for c in result['criteria'])


def test_line_ids_resolve_to_exact_saved_text(monkeypatch):
    text = '## Confirmed Facts\n- “Securely” is not defined.\n- A 2 MB limit is stated.'
    calls = []
    def reply(role, schema, system, payload):
        calls.append((system, payload))
        return evaluation('L1\nL2\nL3')
    monkeypatch.setattr(models, 'structured', reply)
    result = models.evaluate(text, 'requirement', 'fixed rubric')
    expected = '\n'.join(f'L{i}: {line}' for i, line in enumerate(text.splitlines(), 1))
    assert all(c['evidence'] == expected for c in result['criteria'])
    assert calls[0][1]['rubric'] == 'fixed rubric'
    assert 'Do not copy or paraphrase' in calls[0][0]


@pytest.mark.parametrize('reference', ['L0', 'L9', 'L-1', 'L1: invented fact'])
def test_invalid_line_ids_and_fabricated_quotes_still_fail(monkeypatch, reference):
    monkeypatch.setattr(models, 'structured', lambda *a: evaluation(reference))
    with pytest.raises(ValueError, match='one correction'):
        models.evaluate('saved fact', 'requirement', 'rubric')


def test_line_ids_do_not_turn_failed_criteria_into_passes(monkeypatch):
    response = evaluation('L1')
    response.criteria[2] = models.Criterion(name='depth', passed=False, gap='No concrete scenario.')
    monkeypatch.setattr(models, 'structured', lambda *a: response)
    result = models.evaluate('saved fact', 'requirement', 'fixed rubric')
    assert result['result'] == 'needs_revision'
    assert result['criteria'][2]['passed'] is False
    assert result['criteria'][2]['gap'] == 'No concrete scenario.'


def test_blank_lines_are_not_pass_evidence(monkeypatch):
    monkeypatch.setattr(models, 'structured', lambda *a: evaluation('L2'))
    with pytest.raises(ValueError, match='one correction'):
        models.evaluate('saved fact\n\n', 'requirement', 'rubric')


@pytest.mark.parametrize('evidence', ['', 'L1: saved fact\nL2: invented',
    'L1: saved fact\nL9: another fact', 'L1: saved fact\nnot a citation'])
def test_every_evidence_line_must_match(monkeypatch, evidence):
    monkeypatch.setattr(models, 'structured', lambda *a: evaluation(evidence))
    with pytest.raises(ValueError, match='does not match'):
        models.evaluate('saved fact\nanother fact', 'requirement', 'rubric')


def test_invalid_evidence_gets_one_correction(monkeypatch):
    calls = []
    def reply(role, schema, system, payload):
        calls.append(payload)
        return evaluation('L1: wrong' if len(calls) == 1 else 'L1: saved fact')
    monkeypatch.setattr(models, 'structured', reply)
    assert models.evaluate('saved fact', 'requirement', 'rubric')['result'] == 'satisfied'
    assert len(calls) == 2
    assert 'does not match' in calls[1]['validation_feedback']
    assert calls[1]['saved_analysis'] == calls[0]['saved_analysis']


@pytest.mark.parametrize('reply', [
    evaluation('L1: fabricated fact'),
    evaluation(names=('clarity', 'clarity', 'depth')),
])
def test_invalid_output_never_passes(monkeypatch, reply):
    calls = []
    monkeypatch.setattr(models, 'structured', lambda *a: calls.append(a) or reply)
    with pytest.raises(ValueError, match='one correction'):
        models.evaluate('saved fact', 'requirement', 'rubric')
    assert len(calls) == 2


def test_provider_failure_is_not_retried(monkeypatch):
    calls = []
    def unavailable(*args):
        calls.append(1)
        raise models.ProviderFailure('Provider quota reached')
    monkeypatch.setattr(models, 'structured', unavailable)
    with pytest.raises(models.ProviderFailure):
        models.evaluate('fact', 'req', 'rubric')
    assert len(calls) == 1


def analyst_evidence():
    return [{'id': f'{i}:{criterion}', 'run_id': str(i), 'criterion': criterion,
             'quote': f'doc{i} ({i}): original {criterion} gap'}
            for criterion, count in [('clarity', 4), ('depth', 5)] for i in range(count)]


def proposal(criterion='depth', ids=None, section_id='section-1'):
    return models.Proposal(target='prompt', issue=criterion, section_id=section_id,
                           change='Add guidance.', criterion=criterion,
                           evidence_ids=ids if ids is not None else [f'{i}:{criterion}' for i in range(3)])






def seed_mixed_batch():
    folder = core.batch_folder('v1')
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'AGENTS.md').write_text(core.ensure_instructions())
    documents = [f'doc{i}.md' for i in range(5)]
    core.write_json(folder/'summary.json', {
        'graded': 5, 'runs': 5, 'grader_errors': 0, 'documents': documents,
        'first_attempt': {'completeness': {}, 'clarity': {}, 'depth': {}}})
    for i, doc in enumerate(documents):
        core.write_json(folder/f'run_{i}.json', {
            'id': str(i), 'doc_name': doc, 'trace': [],
            'grading': [{'result': 'needs_revision', 'criteria': [
                {'name': 'depth', 'passed': False, 'gap': 'Missing edge case.'},
                {'name': 'completeness', 'passed': True, 'gap': ''},
                {'name': 'clarity', 'passed': i == 4, 'gap': 'Missing resolution.'}]}]})
    return folder






def test_model_choice_persists_without_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY', 'private-test-key')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://private.example')
    monkeypatch.setattr(models, 'check_live_model', lambda name: {'status': 'ok'})
    client = core.create_app().test_client()
    before = (tmp_path/'tickets.json').read_bytes()
    response = client.post('/api/model-config', json={'mode': 'live', 'model': models.LUNA})
    assert response.status_code == 200
    assert set(response.json.values()) == {'live', models.LUNA}
    assert json.loads((tmp_path/'model-config.json').read_text()) == {'mode': 'live', 'model': models.LUNA}
    monkeypatch.setenv('SCRIPTED_MODEL', '1')  # old environment must not undo a saved UI choice
    restarted = core.create_app().test_client()
    assert restarted.get('/api/health').json['mode'] == 'live'
    assert 'Learning Loop · GPT-5.6 Luna' in restarted.get('/').text
    assert (tmp_path/'tickets.json').read_bytes() == before
    assert restarted.post('/api/model-config', json={'mode': 'live', 'model': 'arbitrary'}).status_code == 400


def test_failed_live_check_keeps_previous_mode(tmp_path):
    client = core.create_app().test_client()
    response = client.post('/api/model-config', json={'mode': 'live', 'model': models.LUNA})
    assert response.status_code == 502 and 'Missing OPENAI_API_KEY' in response.json['error']
    assert client.get('/api/health').json['mode'] == 'scripted'
    assert not (tmp_path/'model-config.json').exists()


def test_luna_wire_setting_and_safe_json_provider_error(monkeypatch):
    requests = []
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': {'message':
                'Unsupported tool setting; key private-test-key; https://private.example'}}).encode())
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv('OPENAI_API_KEY', 'private-test-key')
        monkeypatch.setenv('OPENAI_BASE_URL', f'http://127.0.0.1:{server.server_port}/v1')
        monkeypatch.setenv('SCRIPTED_MODEL', '0')
        client = core.create_app().test_client()
        response = client.post('/api/tickets', json={'title': 'Review', 'linked_page_id': 'page-req-avatar-upload'})
        assert response.status_code == 502
        assert 'provider HTTP 400' in response.json['error']
        assert 'Unsupported tool setting' in response.json['error']
        assert 'private-test-key' not in response.json['error']
        assert 'https://' not in response.json['error']
        assert requests[0]['reasoning_effort'] == 'none'
        assert requests[0]['tools']
        assert len(requests) == 1
        assert len(client.get('/api/tickets').json) == 1
        for role in ('review', 'grader', 'analyst'):
            assert models.model_for(role).reasoning_effort == 'none'
        assert models.model_for('review', 'another-model').reasoning_effort is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_no_change_approval_and_comparison_use_saved_evidence(reviewer):
    store=core.Store();reviewer('keep');before=core.batch_run(store,'v1')
    with pytest.raises(ValueError):core.approve_batch('v1','keep')
    save_test_diagnosis();assert core.analyze_batch()['target'] is None
    kept=core.approve_batch('v1','keep');assert not kept['applied'] and not kept['diff']
    after=core.batch_run(store,'v2');core.batch_run(store,'new')
    assert before['first_attempt']==after['first_attempt']
    assert core.learning_comparison(store)['decision']['decision']=='keep'


def test_keep_is_blocked_when_recurring_gaps_exist(reviewer):
    core.batch_run(core.Store(),'v1');save_test_diagnosis();core.analyze_batch()
    with pytest.raises(ValueError,match='Reject'):core.approve_batch('v1','keep')
    rejected=core.approve_batch('v1','reject','The proposal does not address the actual content issue well enough.')
    assert not rejected['applied'] and rejected['instructions']==rejected['original_instructions']


def test_review_response_metadata_is_allowlisted(monkeypatch, tmp_path):
    from app import engine
    from langchain_core.messages import AIMessage
    class Agent:
        def invoke(self, *args, **kwargs):
            (tmp_path/'analysis.md').write_text('Saved draft')
            return {'messages': [AIMessage(content='Done', response_metadata={
                'model_name': models.LUNA, 'request_id': 'req-test',
                'headers': {'authorization':'secret'}, 'api_key':'secret'},
                usage_metadata={'input_tokens':10,'output_tokens':4,'total_tokens':14})]}
    monkeypatch.setattr(engine, 'build_review_agent', lambda *args: Agent())
    _, _, _, _, trace, messages = engine.execute_review(tmp_path, 'Requirement', 0, 40, 0)
    assert trace[0]['actor'] == 'Agent action'
    assert messages[0]['model_metadata'] == {'model_name':models.LUNA,'request_id':'req-test'}
    assert messages[0]['token_usage']['total_tokens'] == 14
    assert 'secret' not in json.dumps(messages)








