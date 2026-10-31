"""Small feedback repairs and valid variations in learner-built analysts."""
from pathlib import Path
import pytest
from app import core,bounded

INSTRUCTIONS='## Procedure\nUse the tools.\n### Clarification Questions\nAsk useful questions.\n### Assumptions\nKeep guesses separate.\n'
ENTRIES=[{'id':'a:clarity','run_id':'a','criterion':'clarity','passed':False,'quote':'The question is vague.'},
         {'id':'b:clarity','run_id':'b','criterion':'clarity','passed':True,'quote':'This comparison names the decision.'}]

def proposal(**changes):
    return {'decision':'propose','explanation':'One observed vague question compared with a clearer report supports testing this change.',
            'section':'### Clarification Questions','change':'Tie each open question to the missing product decision without inventing its answer.',
            'evidence_ids':['a:clarity','b:clarity'],**changes}

@pytest.mark.parametrize('heading',['Clarification Questions','### clarification questions','  ## CLARIFICATION   QUESTIONS  ','`### Clarification Questions`','### Clarification Questions ###'])
def test_equivalent_heading_format_resolves_to_actual_target(heading):
    result=core.validate_learning_proposal(proposal(section=heading,decision=' Propose '),ENTRIES,INSTRUCTIONS)
    assert result['section']=='### Clarification Questions'
    assert result['decision']=='propose' and result['evidence_scope']=='observed_issue'

@pytest.mark.parametrize('addition',[
 'Ask the product owner which expiration period to use; do not invent a duration.',
 'Separate confirmed facts from assumptions. Ask which missing policy the team should decide.',
 'Give one relevant example of how two readers might interpret the requirement differently.'
])
def test_supported_content_changes_need_no_sample_labels_or_prompt(addition):
    result=core.validate_learning_proposal(proposal(change=addition),ENTRIES,INSTRUCTIONS)
    assert result['change']==addition

@pytest.mark.parametrize('bad',['Unknown section','### Security'])
def test_unknown_target_is_not_guessed(bad):
    with pytest.raises(ValueError,match='existing instruction heading'):
        core.validate_learning_proposal(proposal(section=bad),ENTRIES,INSTRUCTIONS)

def test_ambiguous_heading_and_invented_evidence_are_still_rejected():
    with pytest.raises(ValueError,match='existing instruction heading'):
        core.validate_learning_proposal(proposal(section='clarification questions'),ENTRIES,INSTRUCTIONS+'\n## CLARIFICATION QUESTIONS\nOther guidance.\n')
    with pytest.raises(ValueError,match='invented'):
        core.validate_learning_proposal(proposal(evidence_ids=['not-saved:clarity','b:clarity']),ENTRIES,INSTRUCTIONS)

def test_all_pass_and_no_recurring_problem_support_keep():
    entries=[{**item,'passed':True} for item in ENTRIES]
    result=core.validate_learning_proposal(proposal(decision=' KEEP ',explanation='Both selected first drafts passed; these examples do not justify changing the instructions.'),entries,INSTRUCTIONS)
    assert result['decision']=='keep'
    with pytest.raises(ValueError,match='actual first-attempt failure'):
        core.validate_learning_proposal(proposal(),entries,INSTRUCTIONS)

def test_pydantic_result_survives_actual_analyst_subprocess(tmp_path):
    source=tmp_path/'analyst.py'
    source.write_text('''from pydantic import BaseModel
class Proposal(BaseModel):
    decision: str
    explanation: str
    section: str
    change: str
    evidence_ids: list[str]
def review(instructions,saved_runs,model):
    return Proposal(decision='Propose',explanation='The first report has a vague question; the comparison is more specific.',section='clarification questions',change='Name the exact product decision being requested.',evidence_ids=[e['id'] for e in saved_runs])
''')
    result=bounded.run({'action':'reviewer','source':str(source),'instructions':INSTRUCTIONS,'saved_runs':ENTRIES})
    assert isinstance(result,dict)
    validated=core.validate_learning_proposal(result,ENTRIES,INSTRUCTIONS)
    assert validated['section']=='### Clarification Questions'

def test_learner_guidance_documents_limits_and_keep_exception():
    root=Path(__file__).resolve().parents[1]
    html=(root/'app/templates/index.html').read_text()
    js=(root/'app/static/app.js').read_text()
    assert '3 revisions and 40 model calls' in html
    assert 'Keeping the original qualifies only if the baseline already passed at least 12/15' in html
    assert 'Check what was fetched' in js and 'which write/edit produced this draft' in js
    assert 'The original baseline is below 12/15' in js
    assert 'First-draft quality' in js and 'First-draft quality' in (root.parent/'instructions.md').read_text()
