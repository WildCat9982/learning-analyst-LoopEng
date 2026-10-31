import json
from pathlib import Path
import pytest
from app import core, bounded
from app.evidence import inspect

REAL_RUN=bounded.run


@pytest.fixture
def source(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATA',str(tmp_path/'activity'));monkeypatch.setenv('SCRIPTED_MODEL','1')
    monkeypatch.delenv('SCRIPTED_VARIANT',raising=False)
    core.instructions_path().parent.mkdir(parents=True,exist_ok=True)
    core.instructions_path().write_text(core.ensure_instructions()+'\nResolved by: require a concrete resolution.\n')
    store=core.Store();run=core.run_analysis(store,'REV-100',ticket=store.ticket('REV-100'))
    assert run['grading'][0]['result']=='satisfied' and len(run['grading'])==1
    return store,run


def test_first_pass_original_is_preserved_and_real_exercise_revises(source,monkeypatch):
    store,original=source
    monkeypatch.setattr(bounded,'run',REAL_RUN)
    saved=json.dumps(original,sort_keys=True);pages=json.dumps(store.pages,sort_keys=True)
    result=core.verification_exercise(store,original['id'])['exercise']
    assert result['exercise'] and result['supplied_draft']
    assert result['grading'][0]['result']=='needs_revision'
    assert result['grading'][-1]['result']=='satisfied'
    assert result['grading'][0]['analysis_markdown']!=result['grading'][-1]['analysis_markdown']
    assert any(m.get('type')=='tool' for m in result['messages'])
    assert json.dumps(original,sort_keys=True)==saved and json.dumps(store.pages,sort_keys=True)==pages
    assert inspect(core.data_root())['minimum']['p1']
    assert core.verification_exercise(store,original['id'])['exercise']==result
    assert len(store.runs)==2
    assert not inspect(core.data_root())['minimum']['p2']


def test_opening_exercise_control_does_not_create_credit(source):
    store,original=source;client=core.create_app().test_client()
    assert 'Practice verification — supplied flawed report' in client.get('/run/'+original['id']).text
    assert not inspect(core.data_root())['minimum']['p1']
    assert not (core.data_root()/'verification-exercises').exists()


def test_missing_source_returns_useful_error(source):
    store,_=source
    with pytest.raises(ValueError,match='saved Tracker'):core.verification_exercise(store,'missing')
