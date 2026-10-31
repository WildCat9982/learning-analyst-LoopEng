"""Capstone orchestration with controlled reports; no provider requests."""
import hashlib
import json
import threading
import time
from pathlib import Path
import pytest
from app import core,capstone
from app.capstone_evidence import inspect,batch

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATA',str(tmp_path/'activity'))
    monkeypatch.setenv('SCRIPTED_MODEL','1')
    for key in ('WORKSPACE_ROOT','SCRIPTED_VARIANT','FETCH_FAILURES'):monkeypatch.delenv(key,raising=False)
    app=core.create_app();app.testing=True
    return app.test_client()

def wait(client):
    for _ in range(800):
        state=client.get('/api/capstone').json
        job=state.get('job')
        if job and job['status'] not in ('queued','running'):return state
        time.sleep(.01)
    pytest.fail('Background job did not stop')

def analysis(client):
    response=client.post('/api/capstone/analyze',json={})
    assert response.status_code==202,response.json
    state=wait(client)
    assert state['job']['status']=='completed',state['job']
    assert state['baseline']['valid']==5
    assert state['proposal'].get('decision'),state
    return state

def decide(client,state,choice='apply'):
    response=client.post('/api/capstone/decisions',json={'candidate':state['candidate'],'decision':choice,'reason':'These examples support clearer, concrete questions; I checked the proposed addition.'})
    assert response.status_code==202,response.json
    return wait(client)

def test_empty_clean_starter_and_unfinished(client):
    state=client.get('/api/capstone').json
    assert not state['activity'] and not state['analyst_built']
    assert len(state['requirements'])==5
    response=client.post('/api/capstone/analyze',json={})
    assert response.status_code==400
    assert not (core.data_root()/'capstone').exists()
    assert client.get('/api/readiness').json['state']=='empty'
    html=client.get('/').text
    assert 'Tracker</a>' not in html and 'Wiki</a>' not in html
    assert 'diagnosis-form' not in html and 'reflection-examples' not in html
    assert html.count('id="build"')==1

def test_complete_apply_experiment(client,reviewer):
    state=analysis(client)
    baseline=capstone.location()/'baseline'
    original={p.relative_to(baseline):p.read_bytes() for p in baseline.rglob('*') if p.is_file()}
    state=decide(client,state)
    assert state['comparison']['complete'] and state['event']['status']=='completed'
    assert state['comparison']['passed'][0] < state['comparison']['passed'][1]
    assert state['comparison']['qualifies']
    assert not state['ready'] # Explanation is still the learner's work.
    note=client.post('/api/capstone/outcome',json={'candidate':state['candidate'],'explanation':'More first drafts passed after the addition; the small sample does not prove this always works.'})
    assert note.status_code==200,note.json
    assert client.get('/api/capstone').json['ready']
    assert client.get('/api/readiness').json['state']=='complete'
    assert all((baseline/p).read_bytes()==data for p,data in original.items())
    saved=client.get('/api/capstone').json
    assert saved['outcome']==note.json
    assert client.post('/api/capstone/outcome',json={'candidate':state['candidate'],'explanation':'Results improved on these five inputs, but other inputs remain uncertain.'}).status_code==200
    run=state['comparison']['rows'][0]['before_run']
    report=client.get('/api/capstone/reports/'+run).json
    assert report['phase']=='Before' and report['label']=='First draft'
    assert report['selected']['analysis_markdown']==batch(baseline)['records'][0]['grading'][0]['analysis_markdown']
    assert client.get('/api/capstone/reports/'+run+'?draft=999').status_code==400

def test_reject_is_completed_but_weak_original_does_not_qualify(client,reviewer):
    state=decide(client,analysis(client),'reject')
    assert state['comparison']['complete'] and not state['comparison']['qualifies']
    assert state['comparison']['status']=='Below passing target'
    assert state['decision']['instructions']==state['decision']['original_instructions']
    assert client.post('/api/capstone/outcome',json={'candidate':state['candidate'],'explanation':'The original performed the same, below the target.'}).status_code==200
    assert client.post('/api/capstone/resume',json={'candidate':state['candidate']}).json['status']=='completed'

def test_keep_path_has_no_diagnosis_or_manual_examples(client,reviewer):
    reviewer('keep')
    state=analysis(client)
    assert state['proposal']['decision']=='keep'
    state=decide(client,state,'keep')
    assert state['comparison']['complete']
    assert not state['comparison']['qualifies']
    assert state['event']['evaluation_job']

def test_duplicate_analysis_and_conflicting_writes(client,reviewer,monkeypatch):
    gate=threading.Event();real=capstone.run_batch
    def slow(*args,**kwargs):gate.wait(3);return real(*args,**kwargs)
    monkeypatch.setattr(capstone,'run_batch',slow)
    first=client.post('/api/capstone/analyze',json={})
    try:
        second=client.post('/api/capstone/analyze',json={})
        assert first.json['id']==second.json['id']
        assert client.post('/api/model-config',json={'mode':'scripted'}).status_code==409
        assert client.get('/api/capstone').status_code==200
    finally:gate.set()
    assert wait(client)['job']['status']=='completed'

def test_duplicate_decision_returns_existing_job(client,reviewer,monkeypatch):
    state=analysis(client);gate=threading.Event();real=capstone.run_batch
    def slow(*args,**kwargs):gate.wait(3);return real(*args,**kwargs)
    monkeypatch.setattr(capstone,'run_batch',slow)
    body={'candidate':state['candidate'],'decision':'apply','reason':'The examples support this addition.'}
    first=client.post('/api/capstone/decisions',json=body)
    try:
        second=client.post('/api/capstone/decisions',json=body)
        assert second.json['id']==first.json['id']
        assert client.post('/api/capstone/decisions',json={**body,'reason':None}).status_code==400
    finally:gate.set()
    assert wait(client)['comparison']['complete']

def test_syntax_and_invalid_evidence_recover(client,reviewer):
    (core.ROOT/'app/learning_agent.py').write_text('def review(:')
    assert client.post('/api/capstone/analyze',json={}).status_code==400
    (core.ROOT/'app/learning_agent.py').write_text("def review(instructions,saved_runs,model):\n return {'decision':'keep','explanation':'All okay','evidence_ids':['invented','absent']}\n")
    assert client.post('/api/capstone/analyze',json={}).status_code==202
    bad=wait(client);assert bad['job']['status']=='failed' and not bad['proposal']
    reviewer()
    good=analysis(client)
    assert good['candidate']==bad['candidate']
    assert len(list((capstone.candidate(good['candidate'])/'analyst-attempts').glob('*.result.json')))==2

def test_new_candidate_keeps_baseline_and_previous_results(client,reviewer):
    state=decide(client,analysis(client))
    old=capstone.candidate(state['candidate']);snap={p.relative_to(old):p.read_bytes() for p in old.rglob('*') if p.is_file()}
    assert client.post('/api/capstone/analyze',json={'new_candidate':True}).status_code==400
    source=core.ROOT/'app/learning_agent.py';source.write_text(source.read_text().replace('Ask which measurable','For each clause ask which measurable'))
    new=analysis_new=client.post('/api/capstone/analyze',json={'new_candidate':True})
    assert new.status_code==202,new.json
    new=wait(client)
    assert new['candidate']!=state['candidate']
    new=decide(client,new)
    assert new['comparison']['complete']
    assert all((old/p).read_bytes()==data for p,data in snap.items())
    assert client.get('/api/capstone?candidate='+state['candidate']).json['candidate']==state['candidate']
    assert client.post('/api/capstone/resume',json={'candidate':state['candidate']}).status_code==400

def test_changed_settings_are_rejected_without_erasing_baseline(client,reviewer):
    state=analysis(client)
    core.write_json(core.data_root()/'review-settings.json',{'revision_limit':1,'turn_limit':40})
    state=decide(client,state)
    assert state['job']['status']=='failed'
    assert not state['comparison']['complete']
    assert batch(capstone.location()/'baseline')['valid']==5
    core.write_json(core.data_root()/'review-settings.json',{'revision_limit':3,'turn_limit':40})
    assert client.post('/api/capstone/resume',json={'candidate':state['candidate']}).status_code==202
    assert wait(client)['comparison']['complete']

def test_crash_after_decision_before_dispatch_resumes_once(client,reviewer,monkeypatch):
    state=analysis(client);controller=client.application.extensions['capstone'];real=controller.jobs.start
    def crash(*args,**kwargs):raise RuntimeError('Simulated dispatch interruption')
    monkeypatch.setattr(controller.jobs,'start',crash)
    body={'candidate':state['candidate'],'decision':'apply','reason':'The evidence supports the addition.'}
    with pytest.raises(RuntimeError):client.post('/api/capstone/decisions',json=body)
    event=core.read_json(capstone.candidate(state['candidate'])/'event.json',{})
    assert event['status']=='pending'
    monkeypatch.setattr(controller.jobs,'start',real)
    assert client.post('/api/capstone/resume',json={'candidate':state['candidate']}).status_code==202
    state=wait(client)
    assert state['event']['id']==event['id'] and state['comparison']['complete']
    # Simulate crash after comparison commit but before the event commit.
    event=state['event'];event['status']='pending';core.write_json(capstone.candidate(state['candidate'])/'event.json',event)
    before=list((capstone.candidate(state['candidate'])/'evaluation').glob('run_*.json'))
    assert client.post('/api/capstone/resume',json={'candidate':state['candidate']}).json['status']=='completed'
    assert client.get('/api/capstone').json['event']['status']=='completed'
    assert list((capstone.candidate(state['candidate'])/'evaluation').glob('run_*.json'))==before

def test_restart_after_four_saved_reviews_resumes_without_replacing_them(client,reviewer,monkeypatch):
    real=core.run_analysis;calls=[]
    def fail_fifth(*args,**kwargs):
        calls.append(kwargs['doc_name'])
        if len(calls)==5:raise ValueError('Temporary request error')
        return real(*args,**kwargs)
    monkeypatch.setattr(core,'run_analysis',fail_fifth)
    assert client.post('/api/capstone/analyze',json={}).status_code==202
    failed=wait(client);assert failed['job']['status']=='failed' and failed['baseline']['valid']==4
    folder=capstone.location()/'baseline';saved={p:p.read_bytes() for p in folder.glob('run_*.json')}
    path=core.data_root()/'batch-jobs'/(failed['job']['id']+'.json')
    job=core.read_json(path,{});job['status']='running';core.write_json(path,job)
    monkeypatch.setattr(core,'run_analysis',real)
    restarted=core.create_app().test_client()
    assert restarted.get('/api/capstone').json['job']['status']=='interrupted'
    assert restarted.post('/api/capstone/resume',json={'candidate':failed['candidate']}).status_code==202
    done=wait(restarted)
    assert done['proposal'] and all(p.read_bytes()==value for p,value in saved.items())
    assert len(calls)==5

def test_timeout_stops_bad_analyst_and_repaired_code_can_resume(client,reviewer,monkeypatch):
    from app import bounded
    real=bounded.run
    def short(payload,**kwargs):
        if payload['action']=='reviewer':kwargs['timeout']=.2
        return real(payload,**kwargs)
    monkeypatch.setattr(bounded,'run',short)
    (core.ROOT/'app/learning_agent.py').write_text('def review(instructions,saved_runs,model):\n while True: pass\n')
    assert client.post('/api/capstone/analyze',json={}).status_code==202
    failed=wait(client)
    assert failed['job']['status']=='interrupted'
    assert failed['baseline']['valid']==5 and client.get('/api/health').status_code==200
    reviewer();monkeypatch.setattr(bounded,'run',real)
    assert client.post('/api/capstone/resume',json={'candidate':failed['candidate']}).status_code==202
    assert wait(client)['proposal']

def test_revised_source_cannot_reroll_an_already_tested_instruction_version(client,reviewer):
    state=decide(client,analysis(client))
    source=core.ROOT/'app/learning_agent.py';source.write_text(source.read_text()+'\n# Changed source, identical proposal.\n')
    assert client.post('/api/capstone/analyze',json={'new_candidate':True}).status_code==202
    failed=wait(client)
    assert failed['job']['status']=='failed' and not failed['proposal']
    assert 'already' in failed['job']['error']
    source.write_text(source.read_text().replace('Ask which measurable','For each requirement ask which measurable'))
    assert client.post('/api/capstone/resume',json={'candidate':failed['candidate']}).status_code==202
    assert wait(client)['proposal']

def test_event_job_link_recovers_without_dispatching_another_evaluation(client,reviewer):
    state=decide(client,analysis(client));folder=capstone.candidate(state['candidate'])
    runs={p:p.read_bytes() for p in (folder/'evaluation').glob('run_*.json')}
    event=core.read_json(folder/'event.json',{});event['evaluation_job']=None;core.write_json(folder/'event.json',event)
    assert not client.get('/api/capstone').json['gates']['decision_event']
    before=len(list((core.data_root()/'batch-jobs').glob('*.json')))
    assert client.post('/api/capstone/resume',json={'candidate':state['candidate']}).json['status']=='completed'
    assert client.get('/api/capstone').json['gates']['decision_event']
    assert len(list((core.data_root()/'batch-jobs').glob('*.json')))==before
    assert all(p.read_bytes()==value for p,value in runs.items())

def test_readiness_ids_preserve_existing_fields_and_evidence_checks(client,reviewer):
    def entries():
        result=client.get('/api/readiness').json
        assert [e['id'] for e in result['entries']]==['analyst','decision_event','comparison','explanations','result']
        assert all({'id','loop','status','message','href'} <= set(e) for e in result['entries'])
        return {e['id']:e for e in result['entries']}
    assert all(e['status']=='missing' for e in entries().values())
    before=analysis(client)
    assert entries()['analyst']['status']=='saved'
    state=decide(client,before)
    saved=entries()
    assert saved['explanations']['status']=='missing'
    assert saved['decision_event']['status']=='saved'
    assert saved['comparison']['status']=='saved'
    note=client.post('/api/capstone/outcome',json={'candidate':state['candidate'],'explanation':'These reports improved; other requirements may vary.'})
    assert note.status_code==200
    assert all(e['status']=='saved' for e in entries().values())

def test_displayed_criteria_keep_the_verifier_definitions(client):
    import html
    response=html.unescape(client.get('/').text)
    for rule in (core.FIXTURES/'learning/rubric.txt').read_text().splitlines():
        if rule.startswith('- '):assert rule[2:] in response
    assert 'First-draft quality' in Path(core.__file__).with_name('static').joinpath('app.js').read_text()
