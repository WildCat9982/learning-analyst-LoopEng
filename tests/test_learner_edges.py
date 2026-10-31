from conftest import save_test_diagnosis
from pathlib import Path
import json
import pytest
from app import core

@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA', str(tmp_path))
    monkeypatch.setenv('SCRIPTED_MODEL', '1')
    for key in ('SCRIPTED_VARIANT','RUN_BUDGET','RUN_TURN_CAP','FETCH_FAILURES'):
        monkeypatch.delenv(key, raising=False)

@pytest.fixture
def client(): return core.create_app().test_client()

def ticket(client, **changes):
    return client.post('/api/tickets', json=dict(title='Review avatar upload', linked_page_id='page-req-avatar-upload', assignee='Casey (QA Lead)', **changes))

@pytest.mark.parametrize('payload', [dict(title=' ',linked_page_id='page-req-avatar-upload'), dict(title='Review',linked_page_id='missing'), dict(linked_page_id='page-req-avatar-upload')])
def test_invalid_ticket_is_recoverable(client,payload):
    assert client.post('/api/tickets',json=payload).status_code == 400
    assert len(client.get('/api/tickets').json) == 1
    assert ticket(client).status_code == 201

def test_close_then_reopen_restores_event_eligibility(client):
    key=ticket(client).json['key']
    for k in (key,'REV-100'):
        assert client.post(f'/api/tickets/{k}/close').status_code==200
        assert client.post(f'/api/tickets/{k}/rerun').status_code==409
    page=client.get('/api/pages').json[0]
    body=page['versions'][-1]['body']+'\nAvatars must be smaller than 2 MB.'
    assert client.post('/api/pages/'+page['id']+'/save',json={'body':body}).json['retriggered']==[]
    for k in (key,'REV-100'): assert client.post(f'/api/tickets/{k}/reopen').status_code==200
    result=client.post('/api/pages/'+page['id']+'/save',json={'body':body}).json
    assert set(result['retriggered'])=={key,'REV-100'}
    assert result['page']['versions'][-1]['body'].count('Avatars must be smaller than 2 MB.')==1

def test_repeat_save_keeps_history_and_no_duplicate_clause(client):
    key=ticket(client).json['key'];page=client.get('/api/pages').json[0]
    body=page['versions'][-1]['body']+'\nAvatars must be smaller than 2 MB.'
    for _ in range(2): assert client.post('/api/pages/'+page['id']+'/save',json={'body':body}).status_code==200
    pages=client.get('/api/pages').json
    report=next(p for p in pages if p.get('linked_ticket')==key)
    assert len(report['versions'])==3
    assert all(v['body'].count('Avatars must be smaller than 2 MB.')==1 for v in pages[0]['versions'][1:])

@pytest.mark.parametrize('body',[None,'','   '])
def test_blank_requirement_does_not_destroy_work(client,body):
    before=client.get('/api/pages').json
    assert client.post('/api/pages/page-req-avatar-upload/save',json={'body':body}).status_code==400
    assert client.get('/api/pages').json==before

@pytest.mark.parametrize('a,b',[('0','1'),('1','99'),('x','1')])
def test_bad_compare_has_actionable_error(client,a,b):
    r=client.get('/api/pages/page-req-avatar-upload/compare',query_string={'a':a,'b':b})
    assert r.status_code==400 and r.json['error']

def test_learning_steps_out_of_order_guide_recovery(client):
    assert client.post('/api/batches',json={'label':'v2'}).status_code==400
    assert client.post('/api/learning/approve',json={'label':'v1'}).status_code==400
    assert client.post('/api/batches/v1/analyze',json={}).status_code==400
    r=client.post('/api/batches',json={'label':'v1'})
    assert r.status_code==201
    assert client.post('/api/batches',json={'label':'v1'}).status_code==409

def test_interrupted_batch_resumes_preserving_finished_records(monkeypatch):
    store=core.Store(core.data_root());real=core.run_analysis;calls=0
    def interrupt(*args,**kw):
        nonlocal calls
        calls+=1
        if calls==3: raise RuntimeError('Simulated interrupted process')
        return real(*args,**kw)
    monkeypatch.setattr(core,'run_analysis',interrupt)
    with pytest.raises(RuntimeError): core.batch_run(store,'v1')
    files=list((core.data_root()/'batches/v1').glob('run_*.json'))
    assert len(files)==2
    saved={p:p.read_bytes() for p in files}
    core.instructions_path().write_text(core.ensure_instructions()+'\nUnrelated later change.\n')
    monkeypatch.setattr(core,'run_analysis',real)
    result=core.batch_run(core.Store(core.data_root()),'v1')
    assert result['runs']==result['graded']==5
    assert all(p.read_bytes()==body for p,body in saved.items())
    assert all('Unrelated later change' not in json.loads(p.read_text())['instructions'] for p in (core.data_root()/'batches/v1').glob('run_*.json'))

def test_grader_error_is_not_learning_success_and_can_retry(monkeypatch,reviewer):
    store=core.Store();monkeypatch.setenv('SCRIPTED_VARIANT','grader_error_doc02')
    result=core.batch_run(store,'v1');assert result['grader_errors']==2 and result['graded']==3
    with pytest.raises(ValueError,match='Finish'):save_test_diagnosis();core.analyze_batch('v1')
    saved={p:p.read_bytes() for p in core.batch_folder('v1').glob('run_*.json') if '02_' not in p.name and '05_' not in p.name}
    monkeypatch.delenv('SCRIPTED_VARIANT');fixed=core.batch_run(store,'v1')
    assert fixed['graded']==5 and fixed['grader_errors']==0
    assert all(p.read_bytes()==body for p,body in saved.items())
    save_test_diagnosis();assert core.analyze_batch()['target']=='prompt'

def test_app_has_no_submission_controls_or_api(client):
    page=client.get('/').text
    assert 'Submit your work' not in page and 'grading.js' not in page and 'Grade lab' not in page
    assert client.post('/api/grading/submit').status_code==404


def test_run_provenance_drafts_triggers_and_legacy_display(client, tmp_path):
    from datetime import datetime
    key = ticket(client).json['key']
    runs = json.loads((tmp_path/'runs.json').read_text())
    run = runs[-1]
    assert run['trigger'] == 'ticket_created' and run['execution_mode'] == 'scripted'
    assert datetime.fromisoformat(run['started_at']) <= datetime.fromisoformat(run['finished_at'])
    assert run['duration_ms'] >= 0
    html = client.get('/run/'+run['id']).text
    assert 'First draft sent for verification' in html and 'not the first file skeleton' in html
    assert 'Recommended settings' in html and 'Model reasoning' not in html
    assert run['grading'][0]['analysis_markdown'] != run['analysis_markdown']
    assert client.post(f'/api/tickets/{key}/rerun').json['trigger'] == 'manual_rerun'
    page = client.get('/api/pages').json[0]
    client.post('/api/pages/'+page['id']+'/save', json={'body': page['versions'][-1]['body']+'\nAvatars must be smaller than 2 MB.'})
    runs = json.loads((tmp_path/'runs.json').read_text())
    assert [r['trigger'] for r in runs[-2:]] == ['page_saved', 'page_saved']
    for field in ('execution_mode', 'finished_at', 'duration_ms'):
        runs[0].pop(field)
    runs[0]['trace'][0]['actor'] = 'Model reasoning'
    (tmp_path/'runs.json').write_text(json.dumps(runs))
    before = (tmp_path/'runs.json').read_bytes()
    restarted = core.create_app().test_client()
    html = restarted.get('/run/'+runs[0]['id']).text
    assert 'Not recorded for this older run' in html and 'Model reasoning' not in html
    assert (tmp_path/'runs.json').read_bytes() == before


def test_ungraded_report_label(client, monkeypatch):
    monkeypatch.setenv('RUN_BUDGET','0')
    key = ticket(client).json['key']
    run_id = next(t for t in client.get('/api/tickets').json if t['key']==key)['last_run_id']
    html = client.get('/run/'+run_id).text
    assert 'Saved report — not verified' in html and 'First draft sent for verification' not in html


def test_recommended_labels_and_readiness_card(client):
    html = client.get('/').text
    assert '>Scripted' not in html and 'Tracker</a>' not in html
    assert 'Before you submit' in html and 'View the five requirements' in html
    assert 'LoopEng AI Coding Lab' in html
