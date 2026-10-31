"""Read saved capstone evidence. No app imports, model calls, or learner execution."""
import hashlib
import json
from pathlib import Path

CRITERIA = ('completeness', 'clarity', 'depth')
POLICY = 'loopeng-capstone-v1'
DOCUMENTS = ('avatar-upload.md', 'password-reset.md', 'notifications.md', 'team-invitations.md', 'report-export.md')


def digest(value):
    data = value if isinstance(value, bytes) else str(value).encode()
    return hashlib.sha256(data).hexdigest()


def read(path, default=None):
    try:
        if path.is_symlink(): raise ValueError('Linked evidence is not supported')
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def first(record):
    if not isinstance(record,dict):return None
    grades=record.get('grading')
    if not isinstance(grades,list) or not grades or not isinstance(grades[0],dict):return None
    grade=grades[0];criteria=grade.get('criteria')
    if (not isinstance(criteria,list) or len(criteria)!=3 or any(not isinstance(c,dict) for c in criteria)
        or {c.get('name') for c in criteria}!=set(CRITERIA)
        or any(type(c.get('passed')) is not bool for c in criteria)
        or not isinstance(grade.get('analysis_markdown'),str) or not grade['analysis_markdown'].strip()):return None
    passed=all(c['passed'] for c in criteria)
    if grade.get('result') not in (('satisfied',) if passed else ('needs_revision','failed')):return None
    return {c['name']:c['passed'] for c in criteria}


def batch(folder):
    settings = read(folder/'settings.json', {})
    snapshot=folder/'AGENTS.md'
    if not snapshot.exists(): snapshot=folder/'instructions-snapshot.md'
    instructions=snapshot.read_text() if snapshot.exists() else ''
    records = [];errors=[]
    for i, name in enumerate(DOCUMENTS, 1):
        try:rec = read(folder/f'run_{i:02}_{Path(name).stem}.json', {})
        except (ValueError,TypeError):rec={};errors.append('Unreadable saved evaluation: '+name)
        if not isinstance(rec,dict):rec={};errors.append('Invalid saved evaluation: '+name)
        if rec and (rec.get('doc_name') != name or rec.get('instructions') != instructions
                    or digest(rec.get('requirement_doc', '')) != settings.get('documents', {}).get(name)
                    or rec.get('model')!=settings.get('review_model') or rec.get('execution_mode')!='live'):
            raise ValueError('Saved reports do not match their documents or instruction version.')
        records.append(rec)
    counts = {c: sum(bool((first(r) or {}).get(c)) for r in records) for c in CRITERIA}
    valid = sum(first(r) is not None for r in records)
    for rec in records:
        if first(rec) is None: continue
        frozen = folder/'checkpoints'/(rec['doc_name']+'.json')
        checkpoint = read(frozen, {})
        if not checkpoint or not checkpoint.get('grading'): continue
        if (checkpoint['grading'][0].get('analysis_markdown') != rec.get('grading', [{}])[0].get('analysis_markdown')
                or checkpoint['grading'][0].get('criteria') != rec.get('grading', [{}])[0].get('criteria')):
            raise ValueError('The saved first attempt differs from its execution checkpoint.')
    return {'records': records, 'counts': counts, 'passed': sum(counts.values()),
            'valid': valid, 'complete': valid == 5 and not errors, 'errors':errors, 'settings': settings, 'instructions': instructions}


def tools_saved(record):
    calls={};successful=set()
    for message in record.get('messages',[]):
        for call in message.get('tool_calls',[]):calls[call.get('id')]=call.get('name')
        if message.get('type')=='tool' and message.get('status')!='error':
            content=str(message.get('content',''))
            if content and not content.lower().startswith(('error','denied')):
                successful.add(calls.get(message.get('tool_call_id')))
    return {'fetch_requirement','write_file'}<=successful


def comparison(root, candidate):
    before = batch(root/'capstone/baseline')
    after = batch(candidate/'evaluation')
    decision = read(candidate/'decision.json', {})
    equal = bool(before['settings'] and before['settings'] == after['settings'])
    if after['valid'] and not equal: raise ValueError('Baseline and evaluation settings differ.')
    selected = decision.get('instructions', '')
    if after['valid'] and selected != after['instructions']: raise ValueError('Evaluation used unapproved instructions.')
    complete = before['complete'] and after['complete'] and equal
    no_decline = all(after['counts'][c] >= before['counts'][c] for c in CRITERIA)
    kept = decision.get('decision') in ('reject', 'keep')
    same = selected == before['instructions']
    qualifies = bool(complete and no_decline and (
        (kept and same and before['passed'] >= 12 and after['passed'] >= 12)
        or (decision.get('decision') == 'apply' and not same and
            (after['passed'] >= 12 or after['passed'] - before['passed'] >= 3))))
    rows = []
    for name, left, right in zip(DOCUMENTS, before['records'], after['records']):
        rows.append({'document': name, 'title': name.removesuffix('.md').replace('-', ' ').title(),
                     'before': first(left), 'after': first(right),
                     'before_run': left.get('id'), 'after_run': right.get('id')})
    return {'complete': complete, 'qualifies': qualifies, 'no_decline': no_decline,
            'before': before['counts'], 'after': after['counts'],
            'passed': [before['passed'], after['passed']], 'total': 15,
            'change_percentage_points': round((after['passed']-before['passed'])*100/15, 2),
            'rows': rows, 'valid_after': after['valid'],
            'outcome_points': 50 if qualifies else round(50*after['passed']/15, 4),
            'errors':before['errors']+after['errors'],
            'status': 'Result target met' if qualifies else 'Below passing target' if complete else 'Not fully evaluated'}


def inspect(root, candidate_id=None):
    root = Path(root)
    try:
        index = read(root/'capstone/index.json', {'candidates': []})
        ids = index.get('candidates', [])
        if not isinstance(ids, list) or any(not isinstance(x, str) or not x.isalnum() for x in ids):
            raise ValueError('Invalid saved candidate list')
        key = candidate_id or (ids[-1] if ids else None)
        if key and key not in ids: raise ValueError('Unknown candidate')
        folder = root/'capstone/candidates'/(key or 'missing')
        proposal = read(folder/'proposal.json', {})
        decision = read(folder/'decision.json', {})
        event = read(folder/'event.json', {})
        note = read(folder/'outcome.json', {})
        result = comparison(root, folder)
        source_path = proposal.get('source_path', '')
        source = root/source_path
        source_ok = bool(source_path and source.is_file() and not source.is_symlink()
                         and root.resolve() in source.resolve().parents
                         and source.parent.name == 'analyst-attempts' and source.name.endswith('.py')
                         and digest(source.read_bytes()) == proposal.get('source_sha256'))
        attempt = read(source.with_suffix('.result.json'), {}) if source_ok else {}
        executed = bool(source_ok and attempt.get('status') == 'completed'
                        and attempt.get('proposal') == proposal)
        baseline = batch(root/'capstone/baseline')
        saved_input=read(source.with_suffix('.input.json'),{}) if source_ok else {}
        input_runs=saved_input.get('saved_runs',[])
        executed=bool(executed and saved_input.get('instructions')==baseline['instructions']
                      and len(input_runs)==5 and all(a.get('id')==b.get('id') and a.get('requirement_doc')==b.get('requirement_doc')
                      and a.get('grading',[None])[0]==b.get('grading',[None])[0] for a,b in zip(input_runs,baseline['records'])))
        tools=all(tools_saved(r) for r in baseline['records'])
        allowed = {r.get('id','')+':'+c['name']: c for r in baseline['records']
                   for c in (r.get('grading') or [{}])[0].get('criteria', [])}
        refs = proposal.get('evidence_ids', [])
        support = bool(isinstance(refs, list) and len(set(x.split(':')[0] for x in refs if isinstance(x,str))) >= 2
                       and all(isinstance(x,str) and x in allowed for x in refs)
                       and (proposal.get('decision') == 'keep' or any(not allowed[x]['passed'] for x in refs)))
        job=read(root/'batch-jobs'/(str(event.get('evaluation_job',''))+'.json'),{})
        chosen = bool(decision.get('proposal_sha256') == digest(json.dumps(proposal, sort_keys=True))
                      and decision.get('reason', '').strip() and decision.get('decision') in ('apply','reject','keep')
                      and event.get('id') == decision.get('event_id') and event.get('candidate') == key
                      and event.get('instructions_sha256') == digest(decision.get('instructions',''))
                      and event.get('status') == 'completed' and event.get('evaluation_job')
                      and job.get('label') == 'capstone-'+str(key)
                      and job.get('metadata')=={'operation':'capstone_evaluation','candidate':key,'event_id':event.get('id'),'instructions_sha256':digest(decision.get('instructions',''))}
                      and job.get('status') in ('completed','interrupted','running'))
        notes = bool(note.get('explanation','').strip() and note.get('comparison_sha256') == digest(json.dumps(result, sort_keys=True)))
        gates = {'analyst': executed and support and tools, 'decision_event': chosen,
                 'comparison': result['complete'], 'explanations': notes and bool(decision.get('reason','').strip()),
                 'result': result['qualifies']}
        return {'candidate': key, 'candidates': ids, 'proposal': proposal, 'decision': decision, 'event': event,
                'outcome': note, 'comparison': result, 'gates': gates, 'ready': all(gates.values()),
                'evidence_ready':all(v for k,v in gates.items() if k!='result'),
                'activity': bool(ids or baseline['valid']), 'errors': result['errors']}
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        return {'candidate': candidate_id, 'candidates': [], 'proposal': {}, 'decision': {}, 'event': {},
                'outcome': {}, 'comparison': {}, 'gates': dict.fromkeys(('analyst','decision_event','comparison','explanations','result'), False),
                'ready': False, 'activity': True, 'errors': [str(error)]}


def grading_context(root):
    """Compact assessment context; full immutable files remain available to read."""
    root=Path(root);state=inspect(root);key=state.get('candidate')
    if not key:return state
    folder=root/'capstone/candidates'/key
    def summary(record):
        if not record:return {}
        grade=(record.get('grading') or [{}])[0]
        checked={k:(v[:30000] if k=='analysis_markdown' else v[:4000]) if isinstance(v,str) else v for k,v in grade.items() if k!='tool_calls'}
        checked['criteria']=[{k:v[:4000] if isinstance(v,str) else v for k,v in c.items()} for c in grade.get('criteria',[])]
        return {'id':record['id'],'doc_name':record['doc_name'],'requirement_doc':record.get('requirement_doc',''),
                'first_evaluation':checked,'final_status':record.get('status'),
                'verification_attempts':len(record.get('grading',[])),
                'tools':[{k:str(v)[:350] for k,v in item.items()} for item in record.get('trace',[])[:40]],
                'report_truncated':len(grade.get('analysis_markdown',''))>30000}
    result=dict(state)
    result['baseline_records']=[summary(r) for r in batch(root/'capstone/baseline')['records']]
    result['evaluation_records']=[summary(r) for r in batch(folder/'evaluation')['records']]
    source=root/state['proposal'].get('source_path','missing')
    if state['gates']['analyst']:
        result['executed_source']=source.read_text()[:60000]
        result['executed_input_path']=str(source.with_suffix('.input.json').relative_to(root))
        saved=read(source.with_suffix('.input.json'),{})
        result['executed_input']={'instructions':saved.get('instructions'),
                                  'run_ids':[r.get('id') for r in saved.get('saved_runs',[])]}
    return result
