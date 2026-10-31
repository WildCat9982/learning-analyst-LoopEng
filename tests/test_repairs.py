from conftest import save_test_diagnosis
from pathlib import Path
import json
import pytest
from app import core

@pytest.fixture(autouse=True)
def isolate(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATA',str(tmp_path))
    monkeypatch.setenv('SCRIPTED_MODEL','1')
    monkeypatch.delenv('SCRIPTED_VARIANT',raising=False)
    monkeypatch.delenv('RUN_BUDGET',raising=False)
    monkeypatch.delenv('RUN_TURN_CAP',raising=False)
    monkeypatch.delenv('FETCH_FAILURES',raising=False)

def test_executed_tools_change_real_file():
    s=core.Store(core.data_root());r=core.run_analysis(s,'UPL-310')
    assert Path(r['workspace'],'analysis.md').read_text()==r['analysis_markdown']
    calls=[c for m in r['messages'] for c in m.get('tool_calls',[])]
    assert calls[0]['name']=='fetch_requirement'
    first=next(c for c in calls if c['name']=='write_file')['args']['content']
    assert 'Reason:' not in first
    assert len([c for c in calls if c['name']=='edit_file'])==5
    assert len([m for m in r['messages'] if m['type']=='tool'])==7
    assert 'Resolved by:' not in r['grading'][0]['analysis_markdown']
    assert 'Resolved by:' in Path(r['workspace'],'analysis.md').read_text()
    assert r['turns']==9

def test_live_mode_requires_credentials(monkeypatch, tmp_path):
    from app.engine import execute_review
    monkeypatch.setenv('SCRIPTED_MODEL', '0')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    core.Workspace(tmp_path, core.baseline_instructions())
    with pytest.raises(ValueError, match='Missing OPENAI_API_KEY'):
        execute_review(tmp_path, 'Requirement', 1, 12, 0)

@pytest.mark.parametrize('budget,variant,status,passes',[(0,'','ungraded',0),(1,'','satisfied',2),(3,'never_fixes','max_iterations_reached',4)])
def test_revision_budget(budget,variant,status,passes,monkeypatch):
    monkeypatch.setenv('SCRIPTED_VARIANT',variant)
    r=core.run_analysis(core.Store(core.data_root()),'UPL-310',budget=budget)
    assert r['status']==status and len(r['grading'])==passes

def test_cap_is_real(monkeypatch):
    monkeypatch.setenv('SCRIPTED_VARIANT','loop_forever')
    r=core.run_analysis(core.Store(core.data_root()),'UPL-310',budget=0)
    assert r['turns']==12 and not r['analysis_markdown']
    assert r['trace'][-1]['action']=='Stops: turn limit of 12 reached'

def test_actual_instruction_write_denied(monkeypatch):
    monkeypatch.setenv('SCRIPTED_VARIANT','self_edit')
    r=core.run_analysis(core.Store(core.data_root()),'UPL-310')
    assert Path(r['workspace'],'memories/AGENTS.md').read_text()==r['instructions']
    assert r['status']=='satisfied'

def test_each_ambiguity_needs_evidence():
    title,clauses=core.fixture_requirements()['UPL-310'];doc=core.requirement_text(title,clauses)
    text=core.analysis_markdown(title,clauses,True)
    first=text.index('  Resolved by:');end=text.index('\n',first)
    text=text[:end]+ '\n'+text[first:end]+text[end:]
    last=text.rfind('  Resolved by:');end=text.index('\n',last)
    text=text[:last]+text[end:]
    assert core.grader(text,doc)['criteria'][1]['passed'] is False

def test_stage_order_and_empty_section():
    text='## Ambiguities\n- x\n## Confirmed Facts\n- y\n## Assumptions\n\n## Clarification Questions\n- q\n## Summary\nDone.'
    assert not core.stage_order(text)['in_order']
    assert 'Assumptions' in core.stage_order(text)['missing']

def test_isolated_batch_and_instruction_snapshot(reviewer):
    store=core.Store(); tracker=core.ensure_instructions(); baseline=core.learning_instructions()
    before=core.batch_run(store,'v1'); path=core.batch_folder('v1')/'summary.json'; saved=path.read_bytes()
    assert before['runs']==5 and before['revisions_needed']==5
    save_test_diagnosis();proposal=core.analyze_batch(); assert len(proposal['evidence'])==5
    approved=core.approve_batch(); assert approved==core.approve_batch()
    after=core.batch_run(store,'v2'); core.batch_run(store,'new')
    comparison=core.learning_comparison(store)
    assert comparison['criteria']=={'completeness':[5,5],'clarity':[0,5],'depth':[0,5]}
    assert path.read_bytes()==saved and core.ensure_instructions()==tracker
    assert (core.batch_folder('v1')/'AGENTS.md').read_text()==baseline
    assert (core.batch_folder('v2')/'AGENTS.md').read_text()==approved['instructions']
    with pytest.raises(FileExistsError):core.batch_run(store,'v1')

def test_restart_keeps_records():
    s=core.Store(core.data_root());r=core.run_analysis(s,'REV-100',ticket=s.ticket('REV-100'))
    reloaded=core.Store(core.data_root())
    assert reloaded.runs==s.runs and reloaded.pages==s.pages and reloaded.tickets==s.tickets
    assert Path(r['workspace'], 'analysis.md').read_text()==r['analysis_markdown']

@pytest.mark.parametrize('counts,revision,expected',[( (5,5,5),0,'success'),((4,3,1),4,'partial'),((3,5,5),2,'regression'),((4,1,1),4,'no effect')])
def test_comparison(counts,revision,expected):
    def summary(values,rev): return {'runs':5,'revisions_needed':rev,'first_attempt':{n:{'passed':v} for n,v in zip(('completeness','clarity','depth'),values)}}
    c=core.compare_summaries(summary((4,1,1),4),summary(counts,revision))
    assert c['verdict']==expected and c['keep']==(expected!='regression')
