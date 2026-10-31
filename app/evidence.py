"""Read-only evidence checks shared by readiness and the course grader.

These checks establish a saved sequence, not the quality of the learner's work.
"""
import hashlib
import json
from pathlib import Path

CRITERIA = {'completeness', 'clarity', 'depth'}


def inspect(root):
    root = Path(root)
    errors = []

    def read(name, default):
        try:
            path = root/name
            return json.loads(path.read_text()) if path.exists() else default
        except (OSError, ValueError, TypeError):
            errors.append(name)
            return default

    def valid_run(run):
        return isinstance(run, dict) and isinstance(run.get('id'), str) and isinstance(run.get('analysis_markdown'), str) and isinstance(run.get('grading'), list)

    pages, tickets, runs = [read(name+'.json', []) for name in ('pages','tickets','runs')]
    if any(not isinstance(items, list) or any(not isinstance(item, dict) for item in items) for items in (pages,tickets,runs)):
        errors.append('Tracker records')
        pages, tickets, runs = [], [], []
    if any(not valid_run(r) for r in runs):
        errors.append('saved runs')
    runs = [r for r in runs if valid_run(r)]
    page_map = {p.get('id'): p for p in pages}
    ticket_map = {t.get('key'): t for t in tickets}
    reviews = [r for r in runs if r.get('requirement_page_id') and not r.get('exercise')]

    def report_saved(run):
        page = page_map.get(run.get('report_page_id'), {})
        return bool(run['analysis_markdown']) and any(v.get('run_id') == run['id'] and str(v.get('body','')).rstrip().endswith(run['analysis_markdown'].rstrip()) for v in page.get('versions', []))

    def tools_saved(run):
        calls, successful = {}, set()
        for message in run.get('messages', []):
            for call in message.get('tool_calls', []):
                calls[call.get('id')] = call.get('name')
            if message.get('type') == 'tool' and message.get('status') != 'error':
                content = str(message.get('content',''))
                if content and not content.lower().startswith(('error','denied')):
                    successful.add(calls.get(message.get('tool_call_id')))
        return {'fetch_requirement','write_file','edit_file'} <= successful

    linked = [r for r in reviews if r.get('ticket_key') in ticket_map and r['requirement_page_id'] in page_map]
    if len(linked) != len(reviews): errors.append('review links')
    agent = next((r for r in reversed(linked) if tools_saved(r) and report_saved(r)), None)

    def revised(run):
        grades = run.get('grading', [])
        for first, second in zip(grades, grades[1:]):
            if (first.get('result') == 'needs_revision' and first.get('explanation')
                and first.get('analysis_markdown') and first['analysis_markdown'] != second.get('analysis_markdown')
                and second.get('result') == 'satisfied'
                and {c['name'] for c in second.get('criteria', []) if c.get('passed')} == CRITERIA
                and second['analysis_markdown'] == run['analysis_markdown']):
                return True
        return False

    verification = next((r for r in reversed(linked) if revised(r) and report_saved(r)), None)
    if not verification:
        for run in reversed(runs):
            if not run.get('exercise'): continue
            source = next((r for r in linked if r['id'] == run.get('source_run_id')), None)
            exercise = read('verification-exercises/'+str(run.get('source_run_id'))+'/run.json', {})
            if source and exercise == run and run.get('supplied_draft') and revised(run) and source['requirement_doc'] == run.get('requirement_doc'):
                verification = run
                break

    event = None
    for page in pages:
        if page.get('kind') != 'requirement': continue
        versions = page.get('versions', [])
        for before, after in zip(versions, versions[1:]):
            if before.get('body','').strip() == after.get('body','').strip(): continue
            changed = [r for r in linked if r['requirement_page_id'] == page['id'] and r.get('requirement_version') == after['n'] and r.get('trigger') == 'page_saved' and after['body'] in r.get('requirement_doc','') and report_saved(r)]
            earlier = [r for r in linked if r['requirement_page_id'] == page['id'] and r.get('requirement_version',0) < after['n'] and report_saved(r)]
            added = set(after['body'].splitlines()) - set(before['body'].splitlines())
            if (len({r['ticket_key'] for r in changed}) >= 2 and earlier
                and all(all(line in r['analysis_markdown'] for line in added if line.strip()) for r in changed)
                and any(a['analysis_markdown'] != b['analysis_markdown'] for a in earlier for b in changed)):
                event = page['id']

    records, summaries, snapshots, complete = {}, {}, {}, {}
    for label, names in [('v1', ['avatar-upload.md','password-reset.md','notifications.md']),
                         ('v2', ['avatar-upload.md','password-reset.md','notifications.md']),
                         ('new', ['data-export.md','search.md'])]:
        folder = root/'batches'/label
        summary = read('batches/'+label+'/summary.json', {})
        if not isinstance(summary, dict):
            errors.append('batch summary '+label)
            summary = {}
        recs = [read(str(p.relative_to(root)), {}) for p in sorted(folder.glob('run_*.json'))]
        records[label], summaries[label] = recs, summary
        try:
            path = folder/'AGENTS.md'
            if not path.exists(): path = folder/'instructions-snapshot.md'
            snapshots[label] = path.read_text()
        except OSError:
            snapshots[label] = None
        complete[label] = bool(summary.get('runs') == summary.get('graded') == len(names)
            and not summary.get('grader_errors') and summary.get('documents') == names
            and [r.get('doc_name') for r in recs] == names and snapshots[label]
            and all(valid_run(r) and r.get('instructions') == snapshots[label] and r['grading']
                and all(g.get('result') != 'grader_error' for g in r['grading'])
                and {c['name'] for c in r['grading'][0].get('criteria', [])} == CRITERIA for r in recs))
    proposal = read('batches/v1/proposal.json', {})
    approval = read('batches/v1/approval.json', {})
    comparison = read('batches/v2/comparison.json', {})
    if any(not isinstance(x, dict) for x in (proposal,approval,comparison)):
        errors.append('Learning records')
        proposal, approval, comparison = {}, {}, {}
    evidence = {r.get('id','')+':'+c['name']: (r.get('id'), c) for r in records['v1'] for c in (r.get('grading') or [{}])[0].get('criteria', [])}
    ids = proposal.get('evidence_ids', [])
    supported = isinstance(ids, list) and all(isinstance(x,str) and x in evidence for x in ids) and len({evidence[x][0] for x in ids if x in evidence}) >= 2
    if supported and proposal.get('decision') == 'propose':
        supported = any(not evidence[ref][1].get('passed') for ref in ids)
    source = root/str(proposal.get('source_path', 'missing'))
    reviewer = False
    if source.is_file() and root.resolve() in source.resolve().parents:
        reviewer = (source.name == 'learning_agent.py' and source.parent.name != 'app'
                    and hashlib.sha256(source.read_bytes()).hexdigest() == proposal.get('source_sha256')
                    and read(str((source.parent/'result.json').relative_to(root)), {}).get('status') == 'completed')
    decision = (approval.get('approved') and approval.get('decision') in ('apply','reject','keep')
                and approval.get('reason') and approval.get('original_instructions') == snapshots['v1']
                and approval.get('instructions') == snapshots['v2'] == snapshots['new'])
    if decision:
        if approval['decision'] == 'apply':
            decision = (proposal.get('decision') == 'propose' and snapshots['v1'] != snapshots['v2']
                        and proposal.get('change','').strip() in snapshots['v2'])
        else:
            decision = (snapshots['v1'] == snapshots['v2'] and not approval.get('diff')
                        and proposal.get('decision') == ('propose' if approval['decision'] == 'reject' else 'keep'))
    comparable = bool(complete['v1'] and complete['v2'] and comparison
                      and summaries['v1'].get('settings') == summaries['v2'].get('settings')
                      and comparison.get('run_ids') == {label: [r['id'] for r in records[label]] for label in ('v1','v2','new')})
    if comparable:
        for criterion in CRITERIA:
            actual = [sum(bool(next(c for c in r['grading'][0]['criteria'] if c['name'] == criterion)['passed']) for r in records[label]) for label in ('v1','v2')]
            if comparison.get('criteria', {}).get(criterion) != actual: comparable = False
    reflection = comparison.get('reflection', {})
    reflected = (isinstance(reflection,dict) and all(isinstance(reflection.get(k), str) and reflection[k].strip() for k in ('mistake','decision','outcome')) and reflection.get('run_ids') == comparison.get('run_ids'))
    learning = bool(complete['v1'] and complete['v2'] and complete['new'] and reviewer and supported and decision and comparable and reflected)
    return {'minimum': {'p0': bool(agent), 'p1': bool(verification), 'p2': bool(event), 'p3': learning},
            'links': {'p0': 'run/'+agent['id'] if agent else '.#tracker',
                      'p1': 'run/'+verification['id'] if verification else '.#tracker',
                      'p2': 'page/'+(event or 'page-req-avatar-upload'), 'p3': '.#learning'},
            'learning': {'baseline': complete['v1'], 'reviewer': bool(reviewer and supported),
                         'decision': bool(decision), 'comparison': comparable, 'new_inputs': complete['new'],
                         'reflection': bool(reflected)},
            'activity': bool(runs or any(summaries.values()) or proposal or approval), 'errors': errors}


def reflection_examples(root):
    """Named baseline drafts for the reflection picker, never a new review."""
    options = []
    for path in sorted((Path(root)/'batches/v1').glob('run_*.json')):
        run = json.loads(path.read_text())
        requirement = run['requirement_doc'].splitlines()[0].removeprefix('REQUIREMENT: ').strip()
        requirement = requirement[:1].upper() + requirement[1:].lower()
        for draft, evaluation in enumerate(run.get('grading', []), 1):
            if not evaluation.get('analysis_markdown'):
                continue
            name = 'first draft' if draft == 1 else f'revised draft {draft-1}'
            options.append({'run_id': run['id'], 'draft': draft,
                            'label': requirement + ' · ' + name,
                            'href': 'run/' + run['id'] + '?draft=' + str(draft)})
    return options


def reflection_bindings(root, comparison, selected=None):
    """Bind examples and current context on the server; never parse answer text."""
    root = Path(root)
    options = {(option['run_id'], option['draft']): option for option in reflection_examples(root)}
    previous = comparison.get('reflection', {})
    if selected is None:
        if isinstance(previous.get('references'), dict):
            selected = previous['references'].get('examples', [])
        else:
            # Older reflections already linked the baseline runs as a group.
            linked = previous.get('run_ids', {}).get('v1', [])
            selected = [{'run_id': run_id, 'draft': 1} for run_id in linked if (run_id, 1) in options]
    if not isinstance(selected, list) or len(selected) > len(options):
        raise ValueError('Choose saved examples using the report checkboxes.')
    examples = []
    for item in selected:
        if (not isinstance(item, dict) or not isinstance(item.get('run_id'), str)
            or type(item.get('draft')) is not int or (item['run_id'], item['draft']) not in options):
            raise ValueError('One selected report is unavailable. Reload the saved examples and choose it again; your answers are kept.')
        ref = {'run_id': item['run_id'], 'draft': item['draft']}
        if ref not in examples:
            examples.append(ref)
    def saved_file(name):
        return {'path': name, 'sha256': hashlib.sha256((root/name).read_bytes()).hexdigest()}
    context = {key: value for key, value in comparison.items() if key != 'reflection'}
    return {'examples': examples,
            'proposal': saved_file('batches/v1/proposal.json'),
            'decision': saved_file('batches/v1/approval.json'),
            'comparison': {'path': 'batches/v2/comparison.json',
                           'sha256': hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()}}


def reflection_grading_context(root):
    """Resolve saved references for the grader, including older saved answers."""
    root = Path(root)
    path = root/'batches/v2/comparison.json'
    if not path.exists():
        return {'available': False, 'message': 'No saved reflection comparison.'}
    comparison = json.loads(path.read_text())
    reflection = comparison.get('reflection', {})
    if not reflection:
        return {'available': False, 'message': 'No saved reflection answers.'}
    legacy = 'references' not in reflection
    expected = reflection_bindings(root, comparison)
    references = expected if legacy else reflection['references']
    records = {run['id']: run for file in (root/'batches/v1').glob('run_*.json')
               for run in [json.loads(file.read_text())]}
    labels = {(item['run_id'], item['draft']): item['label'] for item in reflection_examples(root)}
    examples = []
    for ref in expected['examples']:
        run = records[ref['run_id']]
        evaluation = run['grading'][ref['draft']-1]
        examples.append({**ref, 'label': labels[(ref['run_id'], ref['draft'])],
                         'requirement': run['requirement_doc'],
                         'report': evaluation['analysis_markdown'], 'evaluation': evaluation})
    proposal = json.loads((root/'batches/v1/proposal.json').read_text())
    return {'available': True, 'legacy_context': legacy,
            'mistake': {'answer': reflection.get('mistake',''), 'examples': examples},
            'decision': {'answer': reflection.get('decision',''),
                         'references_match': all(references.get(key) == expected[key] for key in ('proposal','decision')),
                         'proposal': proposal,
                         'decision': json.loads((root/'batches/v1/approval.json').read_text())},
            'outcome': {'answer': reflection.get('outcome',''),
                        'reference_matches': references.get('comparison') == expected['comparison'],
                        'original_diagnosis': proposal.get('learner_diagnosis'),
                        'comparison': {key: value for key, value in comparison.items() if key != 'reflection'}}}
