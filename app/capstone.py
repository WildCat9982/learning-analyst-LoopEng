"""Trusted orchestration for one saved baseline and versioned analyst experiments."""
import ast
import difflib
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from . import core
from .capstone_evidence import DOCUMENTS, CRITERIA, batch, digest, inspect


def location(): return core.data_root()/'capstone'
def candidate(key):
    if not isinstance(key, str) or not key.isalnum(): raise ValueError('Choose a saved candidate.')
    return location()/'candidates'/key

def index(): return core.read_json(location()/'index.json', {'candidates': []})

def settings():
    files = core.FIXTURES/'learning/practice'
    manifest = core.read_json(core.FIXTURES/'learning/manifest.json', {})
    if manifest.get('practice') != ['practice/'+n for n in DOCUMENTS]: raise ValueError('Restore the five prepared requirements.')
    limits = core.read_json(core.data_root()/'review-settings.json', {})
    budget = int(limits.get('revision_limit', 3)); cap = int(limits.get('turn_limit', 40))
    if not 1 <= budget <= 5 or not 1 <= cap <= 100: raise ValueError('Restore the supported review limits.')
    return {'mode':'live', 'review_model':core.LUNA, 'grader_model':core.LUNA,
            'budget':budget, 'cap':cap,
            'rubric_sha256':digest((core.FIXTURES/'learning/rubric.txt').read_bytes()),
            'documents':{n:digest((files/n).read_bytes()) for n in DOCUMENTS}}


def run_batch(store, folder, instructions, progress, cancelled):
    config = settings()
    baseline = core.read_json(location()/'baseline/settings.json', None)
    previous = core.read_json(folder/'settings.json', None)
    if (baseline and baseline != config) or (previous and previous != config):
        raise ValueError('Restore the original documents, models, verifier and limits; saved first attempts are kept.')
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder/'AGENTS.md'
    if snapshot.exists() and snapshot.read_text() != instructions:
        raise ValueError('This evaluation already belongs to different instructions.')
    snapshot.write_text(instructions)
    core.write_json(folder/'settings.json', config)
    for i, name in enumerate(DOCUMENTS, 1):
        from .bounded import Stopped
        if cancelled(): raise Stopped('Stopped. Saved drafts are kept. Resume or submit partial work.')
        saved = folder/f'run_{i:02}_{Path(name).stem}.json'
        record = core.read_json(saved, {})
        if not record or not record.get('grading') or any(g.get('result') == 'grader_error' for g in record['grading']):
            requirement = (core.FIXTURES/'learning/practice'/name).read_text()
            record = core.run_analysis(store, 'LEARNING', 'capstone_evaluation', requirement=requirement,
                budget=config['budget'], cap=config['cap'], failures=0,
                workspace_root=folder/'workspaces'/name, batch_label=folder.name, doc_name=name,
                instructions=instructions, execution={'mode':'live', 'rubric':(core.FIXTURES/'learning/rubric.txt').read_text(),
                    'cancelled':cancelled, 'checkpoint':str((folder/'checkpoints'/(name+'.json')).resolve())})
            core.write_json(saved, record)
        progress(i, 5)
        if any(g.get('result') == 'grader_error' for g in record.get('grading', [])):
            raise ValueError('The verifier could not check this saved draft. Resume to verify the same draft; it will not be regenerated.')
    result = batch(folder)
    if not result['complete']: raise ValueError('Some first attempts are not evaluated. Resume the saved work.')
    core.write_json(folder/'summary.json', {k:result[k] for k in ('counts','passed','valid','complete')})
    return result


def selected_instructions(before,proposal,choice):
    if choice!='apply':return before
    import re
    section=proposal['section'];pos=before.index(section)+len(section)
    tail=before[pos:];depth=len(section.split()[0]);following=re.search(r'^#{1,'+str(depth)+'} ',tail,re.M)
    end=pos+(following.start() if following else len(tail))
    return (before[:end].rstrip()+'\n\n'+proposal['change']+'\n\n'+before[end:].lstrip('\n')).rstrip()+'\n'


def unused_version(key,instructions):
    for old in index()['candidates']:
        if old==key:continue
        decision=core.read_json(candidate(old)/'decision.json',{})
        if digest(decision.get('instructions',''))==digest(instructions):
            raise ValueError('These instruction bytes already have an evaluation. Revise your analyst to propose a different supported change; unchanged quality runs are not repeated.')


class Controller:
    def __init__(self, store, jobs): self.store, self.jobs = store, jobs

    def state(self, key=None):
        with self.jobs.lock:
            try:chosen=key or (index()['candidates'] or [None])[-1]
            except (ValueError,TypeError,KeyError):chosen=None
            job=self.jobs.latest('capstone-'+chosen) if chosen else None
            result = inspect(core.data_root(), chosen)
            key = result.get('candidate')
            result['job'] = job
            result['stage']='analyzing' if job and job['status'] in ('queued','running') and not result['decision'] else 'evaluating' if job and job['status'] in ('queued','running') else 'compare' if result['decision'] else 'decide' if result['proposal'] else 'build'
            result['baseline'] = batch(location()/'baseline') if not result['errors'] else {}
            # Report bodies are fetched on demand, not repeated in every progress response.
            result['baseline'].pop('records', None)
            result['requirements'] = [{'name':n,'title':n.removesuffix('.md').replace('-', ' ').title(),'text':(core.FIXTURES/'learning/practice'/n).read_text()} for n in DOCUMENTS]
            result['analyst_built'] = self.source_check(raise_error=False)
            return result

    def source_check(self, raise_error=True):
        source = core.ROOT/'app/learning_agent.py'
        try:
            text = source.read_text(); tree = ast.parse(text)
            entry = next((x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'review'), None)
            if not entry or len(entry.args.args) != 3: raise ValueError('Define review(instructions, saved_runs, model).')
            if any(isinstance(x, ast.Raise) and isinstance(x.exc, ast.Call)
                   and isinstance(x.exc.func, ast.Name) and x.exc.func.id == 'NotImplementedError' for x in ast.walk(entry)):
                raise ValueError('Build your analyst in Coding chat first. The supplied function is still unfinished.')
            return True
        except (OSError, SyntaxError, ValueError) as error:
            if raise_error: raise ValueError(str(error)) from error
            return False

    def start(self, new=False):
        with self.jobs.lock:
            ids = index()['candidates']; key = ids[-1] if ids else None
            active = self.jobs.latest('capstone-'+key) if key else None
            if active and active['status'] in ('queued','running'): return active
            self.source_check()
            if not self.jobs.gate.acquire(blocking=False): raise FileExistsError('Another action is running.')
            handed = False
            try:
                source = (core.ROOT/'app/learning_agent.py').read_bytes()
                if key and not new:
                    if (candidate(key)/'decision.json').exists(): raise ValueError('This decision is saved. Resume its evaluation or revise your analyst for a new candidate.')
                    if (candidate(key)/'proposal.json').exists(): return {'id':None, 'status':'awaiting_decision','candidate':key}
                else:
                    if key:
                        if not inspect(core.data_root(),key).get('comparison',{}).get('complete'): raise ValueError('Finish or resume the current evaluation before starting another candidate.')
                        previous = core.read_json(candidate(key)/'analyst-source.json', {})
                        if previous.get('sha256') == digest(source): raise ValueError('Revise your analyst before creating a new candidate; unchanged quality runs are not repeated.')
                    key = 'c'+uuid.uuid4().hex[:12]
                    candidate(key).mkdir(parents=True)
                    core.write_json(candidate(key)/'analyst-source.json', {'sha256':digest(source)})
                    ids.append(key); core.write_json(location()/'index.json', {'candidates':ids})
                job = self.jobs.start('capstone-'+key, 5, lambda progress:self.analyze(key,progress), acquired=True,metadata={'operation':'capstone_analysis','candidate':key})
                handed = True; return {**job,'candidate':key}
            finally:
                if not handed: self.jobs.gate.release()

    def analyze(self, key, progress):
        folder = candidate(key)
        instructions = (core.FIXTURES/'learning/instructions_v1.md').read_text()
        config = settings()
        if (location()/'baseline/settings.json').exists() and core.read_json(location()/'baseline/settings.json', {}) != config:
            raise ValueError('Restore the baseline configuration before resuming.')
        run_batch(self.store, location()/'baseline', instructions, progress, lambda:self.jobs.cancelled('capstone-'+key))
        records = batch(location()/'baseline')['records']; entries=[]
        for record in records:
            record['allowed_evidence'] = []
            for c in record['grading'][0]['criteria']:
                e={'id':record['id']+':'+c['name'], 'run_id':record['id'], 'criterion':c['name'],
                   'passed':c['passed'], 'quote':c.get('gap') or c.get('evidence','')}
                entries.append(e); record['allowed_evidence'].append(e)
        attempts = folder/'analyst-attempts'; attempts.mkdir(exist_ok=True)
        stem = attempts/uuid.uuid4().hex
        source = stem.with_suffix('.py'); source.write_bytes((core.ROOT/'app/learning_agent.py').read_bytes())
        core.write_json(stem.with_suffix('.input.json'), {'instructions':instructions,'saved_runs':records})
        from .bounded import run
        try:
            raw=run({'action':'reviewer','source':str(source.resolve()),'instructions':instructions,'saved_runs':records},
                    cancelled=lambda:self.jobs.cancelled('capstone-'+key))
            proposal=core.validate_learning_proposal(raw, entries, instructions)
            unused_version(key,selected_instructions(instructions,proposal,'apply' if proposal['decision']=='propose' else 'keep'))
            proposal.update(source_path=str(source.relative_to(core.data_root())),source_sha256=digest(source.read_bytes()),timestamp=core.now())
            core.write_json(stem.with_suffix('.result.json'), {'status':'completed','proposal':proposal})
            core.write_json(folder/'proposal.json',proposal)
            core.write_json(folder/'analyst-source.json', {'sha256':digest(source.read_bytes())})
            return {'proposal':proposal}
        except Exception as error:
            from .diagnostics import safe_message
            core.write_json(stem.with_suffix('.result.json'), {'status':'failed','error':safe_message(str(error))})
            raise

    def decide(self, key, choice, reason):
        if not isinstance(reason,str): raise ValueError('Explain your decision briefly.')
        if key not in index()['candidates']: raise ValueError('Choose the current saved candidate.')
        if key != index()['candidates'][-1]: raise ValueError('Older decisions are preserved read-only.')
        with self.jobs.lock:
            folder=candidate(key); previous=core.read_json(folder/'decision.json', None)
            if previous:
                if previous['decision'] != choice or previous['reason'] != reason.strip(): raise ValueError('This decision is immutable; start a new candidate to change instructions.')
                return self.resume(key)
            if not self.jobs.gate.acquire(blocking=False): raise FileExistsError('Another action is running.')
            handed=False
            try:
                if choice not in ('apply','reject','keep') or not isinstance(reason,str) or not reason.strip() or len(reason)>3000:
                    raise ValueError('Choose a decision and explain it briefly.')
                before=(location()/'baseline/AGENTS.md').read_text()
                proposal=core.read_json(folder/'proposal.json',{})
                entries=[{'id':r['id']+':'+c['name'],'run_id':r['id'],'passed':c['passed'],'criterion':c['name']} for r in batch(location()/'baseline')['records'] for c in r['grading'][0]['criteria']]
                core.validate_learning_proposal(proposal,entries,before)
                if (proposal['decision']=='keep') != (choice=='keep'): raise ValueError('Choose the decision offered for this proposal.')
                selected=selected_instructions(before,proposal,choice)
                if choice=='apply' and selected==before: raise ValueError('An accepted change must change the original instructions.')
                unused_version(key,selected)
                decision={'decision':choice,'reason':reason.strip(),'instructions':selected,'original_instructions':before,
                          'proposal_sha256':digest(json.dumps(proposal,sort_keys=True)), 'event_id':uuid.uuid4().hex,'timestamp':core.now(),
                          'diff':''.join(difflib.unified_diff(before.splitlines(True),selected.splitlines(True),fromfile='v1',tofile=key))}
                core.write_json(folder/'decision.json',decision)
                self.save_event(key,decision)
                job=self.jobs.start('capstone-'+key,5,lambda p:self.evaluate(key,p),acquired=True,metadata=self.event_metadata(key,decision))
                handed=True;self.link_event(key,job['id']);return {**job,'candidate':key}
            finally:
                if not handed:self.jobs.gate.release()

    def event_metadata(self,key,decision):
        return {'operation':'capstone_evaluation','candidate':key,'event_id':decision['event_id'],'instructions_sha256':digest(decision['instructions'])}

    def save_event(self,key,decision):
        folder=candidate(key)
        if not (folder/'event.json').exists():core.write_json(folder/'event.json',{'id':decision['event_id'],'candidate':key,'instructions_sha256':digest(decision['instructions']),'status':'pending','evaluation_job':None})
    def link_event(self,key,job_id):
        path=candidate(key)/'event.json';event=core.read_json(path,{})
        event.update(evaluation_job=job_id);core.write_json(path,event)

    def resume(self,key):
        if key != (index()['candidates'] or [None])[-1]: raise ValueError('Resume the current candidate.')
        with self.jobs.lock:
            active=self.jobs.latest('capstone-'+key)
            folder=candidate(key);decision=core.read_json(folder/'decision.json',{})
            if active and active['status'] in ('queued','running'):
                if decision and active.get('metadata')==self.event_metadata(key,decision):
                    self.save_event(key,decision);self.link_event(key,active['id'])
                return active
            if not decision:return self.start()
            if (folder/'comparison.json').exists():
                from .capstone_evidence import comparison
                result=comparison(core.data_root(),folder)
                if not result['complete']: raise ValueError('The saved comparison is incomplete. Restore its evaluated records.')
                self.save_event(key,decision)
                event=core.read_json(folder/'event.json',{})
                matching=[j for j in self.jobs.jobs.values() if j.get('metadata')==self.event_metadata(key,decision)]
                if not matching:raise ValueError('The evaluation job record is missing. Restore it before submitting this comparison.')
                linked=max(matching,key=lambda j:j['created_at'])
                event.update(status='completed',evaluation_job=linked['id'])
                core.write_json(folder/'event.json',event)
                return {'id':active['id'] if active else None,'status':'completed','candidate':key}
            if not self.jobs.gate.acquire(blocking=False):raise FileExistsError('Another action is running.')
            try:
                self.save_event(key,decision)
                job=self.jobs.start('capstone-'+key,5,lambda p:self.evaluate(key,p),acquired=True,metadata=self.event_metadata(key,decision))
            except Exception:
                self.jobs.gate.release();raise
            self.link_event(key,job['id']);return {**job,'candidate':key}

    def evaluate(self,key,progress):
        folder=candidate(key);decision=core.read_json(folder/'decision.json',{})
        run_batch(self.store,folder/'evaluation',decision['instructions'],progress,lambda:self.jobs.cancelled('capstone-'+key))
        from .capstone_evidence import comparison
        result=comparison(core.data_root(),folder);core.write_json(folder/'comparison.json',result)
        # The event is committed after all evaluated reports and comparison exist.
        with self.jobs.lock:
            event=core.read_json(folder/'event.json',{});event['status']='completed';core.write_json(folder/'event.json',event)
        return result

    def note(self,key,text):
        if key != (index()['candidates'] or [None])[-1]: raise ValueError('Choose the current candidate.')
        state=inspect(core.data_root(),key)
        if not state.get('comparison',{}).get('complete'):raise ValueError('Finish the evaluation before explaining the outcome.')
        if not isinstance(text,str) or not text.strip() or len(text)>3000:raise ValueError('Explain the result in one or two sentences.')
        note={'explanation':text.strip(),'comparison_sha256':digest(json.dumps(state['comparison'],sort_keys=True)),'saved_at':core.now()}
        core.write_json(candidate(key)/'outcome.json',note);return note
