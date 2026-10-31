"""The learner's hypothesis, saved before the Step 4 coding handoff."""
import json
from pathlib import Path

from .evidence import reflection_examples


def examples(root):
    options = reflection_examples(root)
    runs = {run['id']: run for path in (Path(root)/'batches/v1').glob('run_*.json')
            for run in [json.loads(path.read_text())]}
    for option in options:
        grade = runs[option['run_id']]['grading'][option['draft']-1]
        option['failed'] = grade.get('result') == 'needs_revision'
        option['result'] = grade.get('result', 'not_verified')
        option['criteria'] = grade.get('criteria', [])
        option['explanation'] = grade.get('explanation', '')
    return options


def validate(root, payload):
    if not isinstance(payload, dict):
        raise ValueError('Save your diagnosis using the two sentence fields and report checkboxes.')
    mode = payload.get('mode', 'recurring')
    if mode not in ('recurring', 'no_recurring'):
        raise ValueError('Choose a recurring problem or explain why no recurring problem was found.')
    fields = {name: payload.get(name) for name in ('problem', 'reviewer_focus')}
    if any(not isinstance(value, str) or not value.strip() or len(value) > 3000 for value in fields.values()):
        raise ValueError('Complete both diagnosis fields, using fewer than 3000 characters each.')
    selected = payload.get('examples')
    options = {(item['run_id'], item['draft']): item for item in examples(root)}
    if not isinstance(selected, list) or len(selected) != 2:
        raise ValueError('Select two saved examples from different practice requirements.')
    refs = []
    for item in selected:
        if (not isinstance(item, dict) or not isinstance(item.get('run_id'), str)
            or type(item.get('draft')) is not int or (item['run_id'], item['draft']) not in options):
            raise ValueError('A selected draft is unavailable. Reload and choose its report checkbox again.')
        option = options[item['run_id'], item['draft']]
        refs.append({'run_id': item['run_id'], 'draft': item['draft']})
    if len({item['run_id'] for item in refs}) != 2:
        raise ValueError('Choose examples from two different practice requirements.')
    failed = [options[item['run_id'], item['draft']] for item in refs if options[item['run_id'], item['draft']]['failed']]
    if mode == 'recurring' and not failed:
        raise ValueError('Neither selected draft failed. Choose the no-recurring-problem path and explain what the examples show.')
    result = {name: value.strip() for name, value in fields.items()}
    result.update(mode=mode, examples=refs, evidence_scope='no_recurring' if mode == 'no_recurring' else 'observed_issue' if len(failed) < 2 else 'possible_pattern')
    prefix = 'The issue these examples suggest is ' if mode == 'recurring' else 'I found no recurring problem because '
    result['statement'] = prefix + result['problem'] + '; I think the reviewer should look for ' + result['reviewer_focus'] + '.'
    return result
