"""Actual review engine resumes verification of identical report bytes."""
from pathlib import Path
import json
import pytest
from langchain_core.messages import AIMessage,HumanMessage
from app import engine,core,models

@pytest.fixture
def checkpoint(tmp_path):
    workspace=tmp_path/'work';(workspace/'memories').mkdir(parents=True)
    (workspace/'memories/AGENTS.md').write_text('Use the actual requirement.')
    return workspace,workspace/'checkpoint.json'

def test_technical_verifier_error_does_not_regenerate_draft(checkpoint,monkeypatch):
    root,path=checkpoint;calls=[];checked=[]
    class Agent:
        def invoke(self,payload,config):
            calls.append('draft');(root/'analysis.md').write_text('Frozen report: unknown choices remain unknown.')
            return {'messages':payload['messages']+[AIMessage(content='Draft saved')]}
    monkeypatch.setattr(engine,'build_review_agent',lambda *args:Agent())
    def evaluate(text,*args):
        checked.append(text)
        if len(checked)==1:raise ValueError('Temporary provider failure')
        return {'result':'satisfied','explanation':'Checked','criteria':[{'name':n,'passed':True,'gap':'','evidence':'Saved text'} for n in ('completeness','clarity','depth')],'analysis_markdown':text}
    monkeypatch.setattr(models,'evaluate',evaluate)
    result=engine.execute_review(str(root),'Requirement',3,40,0,mode_override='live',rubric='fixed',checkpoint=str(path))
    assert result[2]=='grader_error' and len(calls)==1
    (root/'analysis.md').write_text('Stray file change must not replace the frozen draft.')
    result=engine.execute_review(str(root),'Requirement',3,40,0,mode_override='live',rubric='fixed',checkpoint=str(path))
    assert result[2]=='satisfied' and len(calls)==1
    assert checked[0]==checked[1]==result[1][0]['analysis_markdown']
    # A crash after checkpoint completion but before the outer run record was saved.
    again=engine.execute_review(str(root),'Requirement',3,40,0,mode_override='live',rubric='fixed',checkpoint=str(path))
    assert len(calls)==1 and len(checked)==2 and again[1]==result[1]

@pytest.mark.parametrize('passed',[True,False])
def test_crash_after_evaluation_commit_keeps_first_attempt(checkpoint,monkeypatch,passed):
    root,path=checkpoint;calls=[];count=[]
    class Agent:
        def invoke(self,payload,config):
            calls.append('revision');(root/'analysis.md').write_text('Revised report')
            return {'messages':payload['messages']+[AIMessage(content='Revision saved')]}
    monkeypatch.setattr(engine,'build_review_agent',lambda *args:Agent())
    def evaluate(text,*args):
        count.append(text);return {'result':'satisfied','explanation':'Pass','criteria':[],'analysis_markdown':text}
    monkeypatch.setattr(models,'evaluate',evaluate)
    from langchain_core.messages import messages_to_dict
    grade={'result':'satisfied' if passed else 'needs_revision','explanation':'Feedback','criteria':[],'analysis_markdown':'First frozen draft'}
    core.write_json(path,{'requirement':'Requirement','instructions':'Use the actual requirement.','messages':messages_to_dict([HumanMessage(content='Start'),AIMessage(content='Saved')]),'grading':[grade],'turns':1,'text':'First frozen draft','attempt':0,'pending':False,'status':'evaluated'})
    result=engine.execute_review(str(root),'Requirement',3,40,0,mode_override='live',rubric='fixed',checkpoint=str(path))
    assert result[1][0]==grade
    assert len(calls)==(0 if passed else 1)
    assert len(result[1])==(1 if passed else 2)
