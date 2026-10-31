import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Step 4 uses controlled review responses in local checks. The learner reviewer
# itself still executes in its real subprocess unless a test explicitly mocks it.
import shutil
import pytest


@pytest.fixture(autouse=True)
def controlled_reviews(tmp_path, monkeypatch):
    from app import core, bounded, engine
    actual = bounded.run
    original_root = core.ROOT
    student = tmp_path/'student-source'
    (student/'app').mkdir(parents=True)
    (student/'app/learning_agent.py').write_text('def review(instructions, saved_runs, model):\n    raise NotImplementedError("Build review() in app/learning_agent.py in Coding chat, then retry.")\n')
    shutil.copyfile(original_root/'spec.coding-agent-lab.md', student/'spec.coding-agent-lab.md')
    monkeypatch.setattr(core, 'ROOT', student)
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    def controlled(payload, **kwargs):
        if payload['action'] == 'review':
            arguments = dict(payload['arguments'])
            arguments['mode_override'] = 'scripted'
            if __import__('os').environ.get('SCRIPTED_VARIANT') == 'grader_error_doc02' and 'Password Reset' in arguments['requirement']:
                return ('unfinished', [{'result':'grader_error','criteria':[],'analysis_markdown':'unfinished'}], 'grader_error', 1, [], [])
            return engine.execute_review(**arguments)
        return actual(payload, **kwargs)
    monkeypatch.setattr(bounded, 'run', controlled)


@pytest.fixture
def reviewer(monkeypatch):
    from app import core
    def build(decision='propose'):
        text = '''def review(instructions, saved_runs, model):
    entries = [e for r in saved_runs for e in r['allowed_evidence'] if e['criterion'] == 'clarity']
    return {'decision': DECISION, 'explanation': 'The saved first evaluations show repeated unclear questions; keep or refine the guidance based on those examples.',
            'section': '### Clarification Questions',
            'change': 'Ask which measurable limit or concrete choice settles each clause. Label unknown details as assumptions, not confirmed facts. Add Resolved by: and Edge case: with document-specific content.',
            'evidence_ids': [e['id'] for e in entries]}
'''.replace('DECISION', repr(decision))
        (core.ROOT/'app/learning_agent.py').write_text(text)
    build()
    return build


def save_test_diagnosis():
    """Explicit setup for existing reviewer/recovery tests, using saved drafts."""
    from app import core
    from app.diagnosis import examples, validate
    if not core.completed_batch('v1') or (core.batch_folder('v1')/'diagnosis.json').exists():
        return
    options = examples(core.data_root())
    chosen = []
    for option in options:
        if option['failed'] and option['run_id'] not in [item['run_id'] for item in chosen]:
            chosen.append({'run_id': option['run_id'], 'draft': option['draft']})
    mode = 'recurring'
    if len(chosen) < 2:
        mode = 'no_recurring'
        chosen = [{'run_id': option['run_id'], 'draft': 1} for option in options if option['draft'] == 1]
    data = validate(core.data_root(), {'problem': 'questions are too vague',
        'reviewer_focus': 'whether each question asks for a concrete choice',
        'examples': chosen[:2], 'mode': mode})
    core.write_json(core.batch_folder('v1')/'diagnosis.json', {**data, 'saved_at': core.now()})
