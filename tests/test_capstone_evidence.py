import copy,json
from pathlib import Path
import pytest
from app.capstone_evidence import batch,comparison,inspect,first,DOCUMENTS
from capstone_testing import fixture,write

@pytest.mark.parametrize('before,after,choice,qualifies',[
 ((3,3,3),(4,4,4),'apply',True), # 12/15
 ((2,2,2),(3,3,3),'apply',True), # +3
 ((3,3,3),(4,3,3),'apply',False),
 ((5,3,3),(4,4,5),'apply',False), # total rises but completeness declines
 ((5,5,5),(5,5,5),'keep',True),
 ((4,4,4),(4,4,4),'reject',True),
 ((2,2,2),(5,5,5),'keep',False), # weak baseline cannot pass by random variation
 ((5,5,4),(5,5,4),'keep',True), # one failed requirement
 ((3,3,3),(3,3,3),'reject',False),
])
def test_exact_policy(tmp_path,before,after,choice,qualifies):
    folder=fixture(tmp_path,before,after,choice)
    result=comparison(tmp_path,folder)
    assert result['qualifies'] is qualifies
    assert result['passed']==[sum(before),sum(after)]
    assert result['outcome_points']==(50 if qualifies else round(50*sum(after)/15,4))

def test_later_revisions_never_replace_firsts(tmp_path):
    folder=fixture(tmp_path,(1,2,1),(2,2,2))
    result=comparison(tmp_path,folder)
    assert result['passed']==[4,6] and not result['qualifies']
    assert all(r['status']=='satisfied' for r in batch(folder/'evaluation')['records'])

@pytest.mark.parametrize('mutation',['missing','malformed','duplicate_criterion','boolean_string','empty_draft','error'])
def test_missing_or_invalid_first_is_not_quality_failure(tmp_path,mutation):
    folder=fixture(tmp_path);path=folder/'evaluation/run_01_avatar-upload.json'
    record=json.loads(path.read_text());grade=record['grading'][0]
    if mutation=='missing':path.unlink()
    elif mutation=='malformed':path.write_text('[')
    else:
        if mutation=='duplicate_criterion':grade['criteria'][0]['name']='clarity'
        if mutation=='boolean_string':grade['criteria'][0]['passed']='true'
        if mutation=='empty_draft':grade['analysis_markdown']=''
        if mutation=='error':grade['result']='grader_error'
        write(path,record)
        (folder/'evaluation/checkpoints/avatar-upload.md.json').unlink()
    saved=inspect(tmp_path)
    assert not saved['gates']['comparison'] and not saved['gates']['result']
    if mutation not in ('malformed',):
        assert saved['comparison']['rows'][0]['after'] is None
        assert saved['comparison']['valid_after']==4

@pytest.mark.parametrize('change',['settings','document','instructions','checkpoint','evidence','source','note','event'])
def test_tampered_or_mismatched_records_cannot_qualify(tmp_path,change):
    folder=fixture(tmp_path)
    if change=='settings':
        p=folder/'evaluation/settings.json';r=json.loads(p.read_text());r['cap']=100;write(p,r)
    elif change in ('document','instructions'):
        p=folder/'evaluation/run_01_avatar-upload.json';r=json.loads(p.read_text());r['requirement_doc' if change=='document' else 'instructions']='changed';write(p,r)
    elif change=='checkpoint':
        p=folder/'evaluation/checkpoints/avatar-upload.md.json';r=json.loads(p.read_text());r['grading'][0]['analysis_markdown']='different';write(p,r)
    elif change=='evidence':
        p=folder/'proposal.json';r=json.loads(p.read_text());r['evidence_ids']=['invented'];write(p,r)
    elif change=='source':(folder/'analyst-attempts/a.py').write_text('replaced')
    elif change=='note':
        p=folder/'outcome.json';r=json.loads(p.read_text());r['comparison_sha256']='wrong';write(p,r)
    elif change=='event':
        p=folder/'event.json';r=json.loads(p.read_text());r['evaluation_job']='absent';write(p,r)
    assert not inspect(tmp_path)['ready']

def test_grader_snapshot_renames_instruction_files(tmp_path):
    fixture(tmp_path)
    for p in tmp_path.rglob('AGENTS.md'):p.rename(p.with_name('instructions-snapshot.md'))
    assert inspect(tmp_path)['ready']

def test_source_and_evidence_symlinks_not_followed(tmp_path):
    folder=fixture(tmp_path);p=folder/'analyst-attempts/a.py';p.rename(p.with_name('elsewhere.py'));p.symlink_to('elsewhere.py')
    assert not inspect(tmp_path)['gates']['analyst']

def test_grading_context_is_compact_and_uses_first_evaluations(tmp_path):
    from app.capstone_evidence import grading_context
    folder=fixture(tmp_path)
    context=grading_context(tmp_path)
    assert len(context['baseline_records'])==len(context['evaluation_records'])==5
    assert 'before0' in context['executed_input']['run_ids']
    assert context['baseline_records'][0]['first_evaluation']['result']=='satisfied'
    assert context['baseline_records'][-1]['first_evaluation']['result']=='needs_revision'
    assert context['baseline_records'][-1]['final_status']=='satisfied'
    assert 'messages' not in context['baseline_records'][0]
    assert len(json.dumps(context))<1000000
