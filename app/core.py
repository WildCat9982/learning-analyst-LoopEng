import difflib
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix
from .models import LUNA, ExecutionFailure, ProviderFailure, is_scripted, save_settings, settings as model_settings

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("APP_DATA", ROOT / "data"))
FIXTURES = ROOT / "fixtures"
BOT = "Review Agent (bot)"
PEOPLE = ["Avery (Product Manager)", "Blake (Eng Lead)", "Casey (QA Lead)", "Devon (Backend Engineer)", "Emery (Frontend Engineer)"]


def now():
    return datetime.now(timezone.utc).isoformat()


def compact(value, limit=220):
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:220] + ("…" if len(text) > 220 else "")


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def fixture_requirements():
    files = {'UPL-310': 'UPL-310.md', 'SESS-101': '01_session_timeout.md',
             'EXP-202': '02_export_reports.md', 'RATE-303': '03_rate_limiting.md',
             'AUD-404': '04_audit_logging.md', 'SRCH-505': '05_search_relevance.md'}
    result = {}
    for key, name in files.items():
        title, *clauses = (FIXTURES/'requirements'/name).read_text().strip().splitlines()
        result[key] = (title.removeprefix('REQUIREMENT: '), [c for c in clauses if c.strip()])
    return result


def requirement_text(title, clauses):
    return "REQUIREMENT: " + title + "\n" + "\n".join(clauses) + "\n"


def vague_word(clause):
    words = re.findall(r"\b(securely|common|reasonable|appropriately|quickly|sensible|easily)\b", clause, re.I)
    return words[0] if words else None


def analysis_markdown(title, clauses, enhanced=False):
    vague = [(i + 1, c, vague_word(c)) for i, c in enumerate(clauses) if vague_word(c)]
    lines = ["## Confirmed Facts", ""] + [f"- {c}" for c in clauses]
    lines += ["", "## Ambiguities", ""]
    for n, clause, word in vague:
        lines.append(f'- **"{clause}"**')
        lines.append(f'  Reason: the word "{word}" is not defined')
        if enhanced:
            lines.append(f'  Resolved by: a definition of "{word}" for clause {n}')
            lines.append(f'  Edge case: an unhandled "{word}" case in production for clause {n}')
    lines += ["", "## Clarification Questions", ""]
    lines += [f'- What does "{word}" mean for clause {n}?' for n, _, word in vague]
    lines += ["", "## Assumptions", ""]
    lines += [f'- Assume the narrowest reading of "{word}" until confirmed.' for _, _, word in vague]
    lines += ["", "## Summary", "", f"The document states {len(clauses)} facts and leaves {len(vague)} clauses under-specified. Clarification is needed before implementation.", ""]
    return "\n".join(lines)


def parse_analysis(text):
    sections = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current and line.strip():
            sections[current].append(line)
    counts = {k: sum(1 for x in sections.get(k, []) if x.lstrip().startswith("-")) for k in ("Confirmed Facts", "Ambiguities", "Clarification Questions", "Assumptions")}
    summary = " ".join(sections.get("Summary", []))
    sentences = len(re.findall(r"(?:\.|!|\?)(?=\s|$)", summary))
    return {"sections": sections, "counts": counts, "summary_words": len(summary.split()), "summary_sentences": sentences, "complete": all(counts.values()) and bool(summary), "text": text}


def stage_order(text):
    names = ["Confirmed Facts", "Ambiguities", "Clarification Questions", "Assumptions", "Summary"]
    found = [h for h in re.findall(r"^## (.+)$", text, re.M) if h in names]
    parsed = parse_analysis(text)
    missing = [n for n in names if not parsed["sections"].get(n)]
    return {"in_order": found == names, "missing": missing, "complete": parsed["complete"], "order": found}



class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pages_path, self.tickets_path, self.runs_path, self.batches_path = [self.root / x for x in ("pages.json", "tickets.json", "runs.json", "batches.json")]
        self.load_errors = []
        def load_records(path):
            try:
                value = read_json(path, [])
                if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
                    raise ValueError('Invalid saved records')
                return value
            except (OSError, ValueError):
                self.load_errors.append(path.name)
                return []
        self.pages = load_records(self.pages_path)
        self.tickets = load_records(self.tickets_path)
        self.runs = load_records(self.runs_path)
        self.batches = load_records(self.batches_path)
        if not self.pages and not self.load_errors:
            title, clauses = fixture_requirements()['UPL-310']
            self.pages = [{"id": "page-req-avatar-upload", "kind": "requirement", "title": title + " — Requirements", "linked_ticket": None, "versions": [{"n": 1, "author": PEOPLE[0], "timestamp": now(), "body": "\n".join(clauses)}]}]
            self.tickets = [{"key": "REV-100", "title": "Review requirements: Profile Avatar Upload", "description": "", "linked_page_id": "page-req-avatar-upload", "assignee": PEOPLE[1], "status": "Open", "comments": [], "created_at": now(), "last_analyzed_version": None, "last_run_id": None}]
            self.save()

    def save(self):
        if self.load_errors:
            raise ValueError('Saved records need repair: '+', '.join(self.load_errors)+'. Ask Coding chat to inspect them without resetting work. Partial work remains submittable.')
        for path, value in ((self.pages_path, self.pages), (self.tickets_path, self.tickets), (self.runs_path, self.runs), (self.batches_path, self.batches)):
            write_json(path, value)

    def page(self, page_id): return next((x for x in self.pages if x["id"] == page_id), None)
    def ticket(self, key): return next((x for x in self.tickets if x["key"] == key), None)
    def run(self, run_id): return next((x for x in self.runs if x["id"] == run_id), None)


class Workspace:
    def __init__(self, root, instructions):
        self.root = Path(root)
        (self.root / "memories").mkdir(parents=True, exist_ok=True)
        (self.root / "memories" / "AGENTS.md").write_text(instructions)

    def path(self, value):
        relative = value.lstrip("/")
        target = (self.root / relative).resolve()
        if target != self.root.resolve() and self.root.resolve() not in target.parents:
            raise ValueError("path is outside workspace")
        return target

    def read(self, value): return self.path(value).read_text()
    def write(self, value, text):
        path = self.path(value)
        if path.relative_to(self.root.resolve()).parts[0] in ("memories", "skills"):
            return "Denied: instruction files are read-only to the agent"
        path = self.path(value); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text); return "ok"
    def edit(self, value, anchor, replacement):
        path = self.path(value)
        if path.relative_to(self.root.resolve()).parts[0] in ("memories", "skills"):
            return "Denied: instruction files are read-only to the agent"
        text = path.read_text(); count = text.count(anchor)
        if count != 1: return f"Error: anchor is {'non-unique' if count > 1 else 'missing'}"
        path.write_text(text.replace(anchor, replacement)); return "ok"


def grader(text, requirement, rubric=None):
    parsed = parse_analysis(text)
    structure = stage_order(text)
    if not structure['in_order'] or structure['missing']:
        return {'result': 'needs_revision', 'explanation': 'Write all five nonempty report sections in order',
                'criteria': [{'name': n, 'passed': False, 'gap': 'Missing, empty or reordered report sections'}
                             for n in ('completeness','clarity','depth')], 'analysis_markdown': text}
    clauses = [x for x in requirement.splitlines()[1:] if x.strip()]
    rubric_path = os.environ.get("RUBRIC_PATH")
    if rubric_path: rubric = Path(rubric_path).read_text()
    if rubric and len(re.findall(r"^- ([^:]+):", rubric, re.M)) != len(set(re.findall(r"^- ([^:]+):", rubric, re.M))):
        return {"result": "failed", "explanation": "Duplicate rubric criteria", "criteria": [], "analysis_markdown": text}
    criteria = []
    ambiguity_lines = parsed["sections"].get("Ambiguities", [])
    bullets = [x for x in ambiguity_lines if x.startswith("-")]
    checks = [("completeness", all("- " + c in parsed["sections"].get("Confirmed Facts", []) for c in clauses), "Confirmed Facts"), ("clarity", bool(bullets) and all(re.search(r"^  Resolved by: .+", b, re.M) for b in re.split(r"(?m)^- ", "\n".join(ambiguity_lines))[1:]), "Resolved by:"), ("depth", bool(bullets) and all(re.search(r"^  Edge case: .+", b, re.M) for b in re.split(r"(?m)^- ", "\n".join(ambiguity_lines))[1:]), "Edge case:")]
    for name, passed, marker in checks:
        if passed:
            line = next((f"L{i}: {x}" for i, x in enumerate(text.splitlines(), 1) if marker in x), f"L1: {marker}")
            criteria.append({"name": name, "passed": True, "evidence": line})
        else:
            gap = f"missing indented '{marker}' line under ambiguity bullet 1" if marker != "Confirmed Facts" else f"only {len(parsed['sections'].get('Confirmed Facts', []))} of {len(clauses)} clauses addressed"
            criteria.append({"name": name, "passed": False, "gap": gap})
    return {"result": "satisfied" if all(x["passed"] for x in criteria) else "needs_revision", "explanation": "All criteria passed" if all(x["passed"] for x in criteria) else "Failed: " + ", ".join(x["name"] for x in criteria if not x["passed"]), "criteria": criteria, "analysis_markdown": text}


def data_root(): return Path(os.environ.get("APP_DATA", DATA))

def instructions_path(): return data_root() / "instructions.md"


def baseline_instructions():
    return (FIXTURES / 'instructions_v1.md').read_text()


def ensure_instructions():
    instructions_path().parent.mkdir(parents=True, exist_ok=True)
    if not instructions_path().exists(): instructions_path().write_text(baseline_instructions())
    return instructions_path().read_text()


def run_analysis(store, ticket_key, trigger="manual_rerun", requirement=None, ticket=None, budget=None, cap=None, failures=None, workspace_root=None, batch_label=None, doc_name=None, instructions=None, execution=None):
    started_at, started_clock = now(), time.monotonic()
    execution_mode = (execution or {}).get("mode", model_settings()["mode"])
    ticket = ticket or (store.ticket(ticket_key) if not execution else None)
    if requirement is None:
        if ticket and store.page(ticket["linked_page_id"]):
            page = store.page(ticket["linked_page_id"])
            requirement = requirement_text(page["title"].replace(" — Requirements", ""), page["versions"][-1]["body"].splitlines())
        elif ticket_key in fixture_requirements():
            requirement = requirement_text(*fixture_requirements()[ticket_key])
        else:
            raise ValueError(f"Unknown ticket {ticket_key}")
    instructions = ensure_instructions() if instructions is None else instructions
    budget = int(os.environ.get("RUN_BUDGET", "3")) if budget is None else budget
    cap = int(os.environ.get("RUN_TURN_CAP", "40" if budget else "12")) if cap is None else cap
    failures = int(os.environ.get("FETCH_FAILURES", "0")) if failures is None else failures
    if budget < 0 or cap < 1 or failures < 0: raise ValueError('Use a non-negative budget/failure count and positive turn cap')
    workspace_root = Path(workspace_root or os.environ.get("WORKSPACE_ROOT", data_root() / "workspaces")).resolve()
    if data_root().resolve() not in workspace_root.parents:
        raise ValueError('WORKSPACE_ROOT must be inside APP_DATA')
    ws = Workspace(workspace_root if batch_label else workspace_root / uuid.uuid4().hex[:8], instructions)
    from .engine import execute_review
    if execution:
        from .bounded import run
        arguments = dict(root=str(ws.root), requirement=requirement, budget=budget, cap=cap, failures=failures,
                         mode_override=execution_mode, rubric=execution.get('rubric'), initial_draft=execution.get('initial_draft'), checkpoint=execution.get('checkpoint'))
        text, grading, status, turns, trace, messages = run({'action': 'review', 'arguments': arguments},
                   timeout=600, cancelled=execution.get('cancelled'))
    else:
        text, grading, status, turns, trace, messages = execute_review(ws.root, requirement, budget, cap, failures)
    parsed = parse_analysis(text)
    run_id = uuid.uuid4().hex[:8]
    record = {"id": run_id, "trigger": trigger, "ticket_key": ticket_key, "requirement_page_id": ticket.get("linked_page_id") if ticket else None, "requirement_version": (store.page(ticket["linked_page_id"])["versions"][-1]["n"] if ticket and store.page(ticket["linked_page_id"]) else 1), "model": "scripted-stand-in" if execution_mode == "scripted" else (LUNA if execution else model_settings()['review_model']), "workspace": str(ws.root.resolve()), "requirement_doc": requirement, "instructions": instructions, "trace": trace, "messages": messages, "grading": grading, "analysis_markdown": text, "status": status, "turns": turns, "counts": parsed["counts"], "started_at": started_at, "finished_at": now(), "duration_ms": round((time.monotonic() - started_clock) * 1000), "execution_mode": execution_mode}
    if batch_label: record.update({"label": batch_label, "doc_name": doc_name})
    store.runs.append(record)
    if ticket:
        report_id = f"page-analysis-{ticket_key.lower()}"
        report = store.page(report_id)
        body = f"Ticket: {ticket_key}\nRequirement version {record['requirement_version']} analyzed\nVerification: {status} after {len(grading)} grading attempt(s)\n\n{text}"
        if not report:
            report = {"id": report_id, "kind": "analysis_report", "title": f"Analysis Report — {ticket_key}", "linked_ticket": ticket_key, "versions": []}; store.pages.append(report)
        report["versions"].append({"n": len(report["versions"]) + 1, "author": BOT, "timestamp": now(), "body": body, "run_id": run_id})
        ticket["status"] = "Analysis Ready" if status == "satisfied" else "Needs attention"; ticket["last_analyzed_version"] = record["requirement_version"]; ticket["last_run_id"] = run_id
        ticket["comments"].append({"author": BOT, "text": f"Review result ({status}): requirement version {record['requirement_version']}, report: {report['title']}", "timestamp": now()})
        record["report_page_id"] = report_id; record["report_version"] = len(report["versions"])
    store.save()
    return record


def batch_folder(label):
    if label not in ('v1', 'v2', 'new'):
        raise ValueError('Choose v1, v2, or the new-input checks.')
    return data_root() / 'batches' / label


def learning_files(label):
    manifest = read_json(FIXTURES/'learning/manifest.json', {})
    group = 'new' if label == 'new' else 'practice'
    paths = [(FIXTURES/'learning'/name).resolve() for name in manifest.get(group, [])]
    allowed = (FIXTURES/'learning'/group).resolve()
    if not paths or any(allowed not in p.parents or not p.is_file() for p in paths):
        raise ValueError('Learning documents are missing or outside their fixture folder.')
    return paths


def learning_instructions():
    path = data_root()/'learning/instructions.md'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((FIXTURES/'learning/instructions_v1.md').read_text())
    return path.read_text()


def batch_approved(label='v1'):
    return bool(read_json(batch_folder(label)/'approval.json', {}).get('approved'))


def batch_run(store, label, progress=None, cancelled=None):
    folder = batch_folder(label)
    approval = read_json(batch_folder('v1')/'approval.json', {})
    if label != 'v1' and not approval.get('approved'):
        raise ValueError('Run your learning reviewer and save an accept, reject, or keep decision first.')
    if label == 'new' and not completed_batch('v2'):
        raise ValueError('Finish the practice rerun before checking new inputs.')
    prior = read_json(folder/'summary.json', {})
    if prior and prior.get('graded') == len(learning_files(label)) and not prior.get('grader_errors'):
        raise FileExistsError('This batch is already saved; completed evidence is kept unchanged.')
    files = learning_files(label)
    limits = read_json(data_root()/'review-settings.json', {})
    budget = int(limits.get('revision_limit', limits.get('revisions', os.environ.get('RUN_BUDGET', 3))))
    cap = int(limits.get('turn_limit', limits.get('turns', os.environ.get('RUN_TURN_CAP', 40))))
    if not 1 <= budget <= 5 or not 1 <= cap <= 100:
        raise ValueError('Learning reviews need 1–5 revisions and 1–100 model turns.')
    rubric = (FIXTURES/'learning/rubric.txt').read_text()
    settings = {'mode': 'live', 'budget': budget, 'cap': cap, 'review_model': LUNA, 'grader_model': LUNA,
                'rubric_sha256': hashlib.sha256(rubric.encode()).hexdigest(),
                'documents': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    if label != 'v1':
        baseline = read_json(batch_folder('v1')/'settings.json', {})
        keys = ('mode','budget','cap','review_model','grader_model','rubric_sha256')
        if any(settings[key] != baseline.get(key) for key in keys):
            raise ValueError('Restore the baseline model, review limits and verifier before rerunning or checking new inputs. Saved work is unchanged.')
    folder.mkdir(parents=True, exist_ok=True)
    saved_settings = read_json(folder/'settings.json', None)
    if saved_settings and saved_settings != settings:
        raise ValueError('Restore the batch’s original documents and settings before resuming. Saved work can still be submitted.')
    instructions = learning_instructions() if label == 'v1' else approval['instructions']
    snapshot_path = folder/'AGENTS.md'
    if snapshot_path.exists() and snapshot_path.read_text() != instructions:
        raise ValueError('Instructions differ from this batch’s saved version. Restore them to resume; saved evidence is unchanged.')
    snapshot_path.write_text(instructions)
    write_json(folder/'settings.json', settings)
    (folder/'rubric.txt').write_text(rubric)
    batch = {'label': label, 'model': LUNA, 'settings': settings, 'runs': 0, 'graded': 0,
             'grader_errors': 0, 'documents': [p.name for p in files], 'revisions_needed': 0,
             'verification_attempts': 0,
             'first_attempt': {n: {'passed': 0, 'total': 0, 'pass_rate': None} for n in ('completeness','clarity','depth')}}
    def save():
        write_json(folder/'summary.json', batch)
        store.batches = [b for b in store.batches if b['label'] != label] + [batch]
        store.save()
    from .bounded import Stopped
    for i, file in enumerate(files, 1):
        if cancelled and cancelled():
            raise Stopped('Stopped. Completed reviews are saved; resume when ready or submit partial work.')
        saved = folder/f'run_{i:02}_{file.stem}.json'
        rec = read_json(saved, None)
        if not rec or not rec.get('grading') or any(g['result'] == 'grader_error' for g in rec['grading']):
            workspace = folder/f'ws_{i:02}'
            if workspace.exists():
                archive = folder/'interrupted'/uuid.uuid4().hex
                archive.mkdir(parents=True)
                shutil.move(str(workspace), str(archive/'workspace'))
                if rec: write_json(archive/'run.json', rec)
            try:
                rec = run_analysis(store, 'LEARNING', 'learning_batch', requirement=file.read_text(),
                                   budget=budget, cap=cap, failures=0, batch_label=label, doc_name=file.name,
                                   workspace_root=workspace, instructions=instructions,
                                   execution={'mode': 'live', 'rubric': rubric, 'cancelled': cancelled})
            except Exception:
                save()
                raise
            write_json(saved, rec)
        batch['runs'] += 1
        grades = rec.get('grading', [])
        first = grades[0] if grades else {}
        if (not grades or any(g['result'] == 'grader_error' for g in grades)
            or {c['name'] for c in first.get('criteria', [])} != {'completeness','clarity','depth'}):
            batch['grader_errors'] += 1
        else:
            batch['graded'] += 1
            batch['verification_attempts'] += len(grades)
            batch['revisions_needed'] += int(first['result'] != 'satisfied')
            for criterion in first['criteria']:
                item = batch['first_attempt'][criterion['name']]
                item['total'] += 1
                item['passed'] += int(criterion['passed'])
                item['pass_rate'] = round(item['passed']/item['total'], 3)
        save()
        if progress: progress(i, len(files))
    return batch


def completed_batch(label):
    summary = read_json(batch_folder(label)/'summary.json', {})
    return bool(summary and summary.get('graded') == summary.get('runs') == len(learning_files(label))
                and not summary.get('grader_errors'))


def practice_evidence():
    folder = batch_folder('v1')
    if not completed_batch('v1'):
        raise ValueError('Finish the three practice reviews before running your learning reviewer.')
    records = [read_json(p, {}) for p in sorted(folder.glob('run_*.json'))]
    summary = read_json(folder/'summary.json', {})
    if [r.get('doc_name') for r in records] != summary['documents']:
        raise ValueError('Saved practice runs are missing or inconsistent. Ask Coding chat to inspect them without resetting work.')
    entries = []
    for rec in records:
        rec['allowed_evidence'] = []
        for criterion in rec['grading'][0]['criteria']:
            entry = {'id': rec['id'] + ':' + criterion['name'], 'run_id': rec['id'],
                     'criterion': criterion['name'], 'passed': criterion['passed'],
                     'quote': criterion.get('gap') or criterion.get('evidence', '')}
            rec['allowed_evidence'].append(entry)
            entries.append(entry)
    return records, entries


def validate_learning_proposal(result, entries, instructions):
    if isinstance(result,dict):
        result=dict(result)
        if isinstance(result.get('decision'),str):result['decision']=result['decision'].strip().casefold()
    if not isinstance(result, dict) or result.get('decision') not in ('propose', 'keep'):
        raise ValueError('Return decision="propose" or "keep", explanation, and evidence_ids from the saved runs.')
    explanation = result.get('explanation')
    ids = result.get('evidence_ids')
    if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 6000:
        raise ValueError('Explain the observed issue or the evidence for keeping the instructions.')
    allowed = {e['id']: e for e in entries}
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or x not in allowed for x in ids):
        raise ValueError('Use evidence_ids from the saved practice runs; invented references cannot be applied.')
    selected = [allowed[x] for x in dict.fromkeys(ids)]
    if len({e['run_id'] for e in selected}) < 2:
        raise ValueError('Cite at least two saved practice runs to support your finding or keep decision.')
    proposal = {'decision': result['decision'], 'explanation': explanation.strip(),
                'evidence_ids': [e['id'] for e in selected], 'evidence': selected}
    if result['decision'] == 'propose':
        section, change = result.get('section'), result.get('change')
        all_headings = re.findall(r'^#{1,6} .+$', instructions, re.M)
        headings = [heading for heading in all_headings if all_headings.count(heading) == 1]
        if section not in headings and isinstance(section,str):
            def heading_text(value):
                return ' '.join(value.strip().strip('`').strip().lstrip('#').rstrip('#').split()).casefold()
            matches=[h for h in headings if heading_text(h)==heading_text(section)]
            if len(matches)==1:section=matches[0]
        if section not in headings:
            raise ValueError('Choose an existing instruction heading: ' + ', '.join(headings))
        if not isinstance(change, str) or not change.strip() or len(change) > 6000:
            raise ValueError('Return a short, nonempty instruction addition.')
        failed = [e for e in selected if not e['passed']]
        if not failed:
            raise ValueError('An instruction change must cite an actual first-attempt failure and a second practice report for comparison. Otherwise recommend keeping the instructions.')
        proposal['evidence_scope'] = ('possible_pattern' if any(len({e['run_id'] for e in failed if e['criterion'] == name}) >= 2 for name in ('completeness','clarity','depth')) else 'observed_issue')
        if change.strip() in instructions:
            raise ValueError('That instruction addition already exists. Explain why it should be kept or propose a different supported change.')
        proposal.update(target='prompt', section=section, change=change.strip())
    else:
        proposal['target'] = None
    return proposal


def analyze_batch(label='v1', cancelled=None):
    if label != 'v1': raise ValueError('Your reviewer learns only from the baseline practice runs.')
    folder = batch_folder(label)
    if (folder/'approval.json').exists():
        raise FileExistsError('A decision is already saved for this cycle; the proposal is kept unchanged.')
    records, entries = practice_evidence()
    diagnosis = read_json(folder/'diagnosis.json', {})
    if not diagnosis and not (folder/'proposal.json').exists():
        raise ValueError('Save your diagnosis in Learning before asking Coding chat to build the reviewer.')
    if diagnosis:
        from .diagnosis import validate
        validate(data_root(), diagnosis)
        for record in records:
            record['learner_diagnosis'] = diagnosis
    instructions = (folder/'AGENTS.md').read_text()
    source = ROOT/'app/learning_agent.py'
    if not source.is_file():
        raise ValueError('app/learning_agent.py is missing. Ask Coding chat to restore the reviewer entry point; your saved practice reviews are kept.')
    attempt = folder/'reviewer-attempts'/uuid.uuid4().hex
    attempt.mkdir(parents=True)
    snapshot = attempt/'learning_agent.py'
    snapshot.write_bytes(source.read_bytes())
    write_json(attempt/'input.json', {'instructions': instructions, 'saved_runs': records, 'learner_diagnosis': diagnosis})
    from .bounded import run
    try:
        raw = run({'action': 'reviewer', 'source': str(snapshot.resolve()),
                   'instructions': instructions, 'saved_runs': records}, cancelled=cancelled)
        proposal = validate_learning_proposal(raw, entries, instructions)
    except Exception as error:
        from .diagnostics import safe_message
        write_json(attempt/'result.json', {'status': 'failed', 'error': safe_message(str(error)), 'finished_at': now()})
        raise
    proposal.update(source_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                    source_path=str(snapshot.relative_to(data_root())), timestamp=now())
    if diagnosis:
        proposal['learner_diagnosis'] = diagnosis
    write_json(attempt/'result.json', {'status': 'completed', 'proposal': proposal})
    write_json(folder/'proposal.json', proposal)
    write_json(folder/'analyst_reads.json', [p.name for p in sorted(folder.glob('run_*.json'))])
    return proposal


def approve_batch(label='v1', decision='apply', reason=''):
    if label != 'v1' or decision not in ('apply','reject','keep'):
        raise ValueError('Choose accept and apply, reject and keep original, or keep original instructions.')
    folder = batch_folder(label)
    prior = read_json(folder/'approval.json', None)
    if prior:
        if prior['decision'] != decision:
            raise ValueError('This cycle already has a saved decision. Original evidence is kept unchanged.')
        return prior
    records, entries = practice_evidence()
    before = (folder/'AGENTS.md').read_text()
    if learning_instructions() != before:
        raise ValueError('Instructions changed outside this cycle. Restore the baseline before saving your decision.')
    proposal = read_json(folder/'proposal.json', {})
    checked = validate_learning_proposal(proposal, entries, before)
    if decision == 'keep' and checked['decision'] != 'keep':
        raise ValueError('Use Reject change — keep original to decline this proposal.')
    if decision in ('apply','reject') and checked['decision'] != 'propose':
        raise ValueError('The reviewer recommended keeping the instructions. Choose Keep original instructions.')
    if decision == 'reject' and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError('Explain why you rejected the proposed change.')
    if not isinstance(reason, str) or len(reason) > 6000:
        raise ValueError('Keep your decision explanation under 6000 characters.')
    updated = before
    if decision == 'apply':
        section = checked['section']
        match = re.search(r'(?m)^' + re.escape(section) + r'$', before)
        depth = len(section.split()[0])
        tail = before[match.end():]
        next_heading = re.search(r'^#{1,'+str(depth)+r'} ', tail, re.M)
        end = match.end() + (next_heading.start() if next_heading else len(tail))
        updated = before[:end].rstrip() + '\n\n' + checked['change'] + '\n\n' + before[end:].lstrip('\n')
        updated = updated.rstrip() + '\n'
    result = {'approved': True, 'applied': decision == 'apply', 'decision': decision,
              'reason': reason.strip() or checked['explanation'], 'instructions': updated,
              'original_instructions': before, 'timestamp': now(),
              'diff': ''.join(difflib.unified_diff(before.splitlines(True), updated.splitlines(True), fromfile='before', tofile='after'))}
    # Commit the immutable decision first; a restart can recover the selected instructions.
    write_json(folder/'approval.json', result)
    (data_root()/'learning/instructions.md').write_text(updated)
    return result


def learning_comparison(store):
    if not completed_batch('v1') or not completed_batch('v2'):
        raise ValueError('Finish the baseline and practice rerun before comparing.')
    before = read_json(batch_folder('v1')/'summary.json', {})
    after = read_json(batch_folder('v2')/'summary.json', {})
    result = compare_summaries(before, after)
    result['verification_attempts'] = [before['verification_attempts'], after['verification_attempts']]
    result['decision'] = read_json(batch_folder('v1')/'approval.json', {})
    result['new_inputs'] = read_json(batch_folder('new')/'summary.json', {})
    prior = read_json(batch_folder('v2')/'comparison.json', {})
    result['reflection'] = prior.get('reflection', {})
    result['run_ids'] = {label: [read_json(p, {})['id'] for p in sorted(batch_folder(label).glob('run_*.json'))]
                         for label in ('v1','v2','new')}
    write_json(batch_folder('v2')/'comparison.json', result)
    return result


def verification_exercise(store, source_id, progress=None, cancelled=None):
    source = store.run(source_id)
    if not source or not source.get('requirement_page_id'):
        raise ValueError('Choose a saved Tracker review for this exercise.')
    folder = data_root()/'verification-exercises'/source_id
    prior = read_json(folder/'run.json', None)
    if prior and prior.get('status') == 'satisfied':
        if progress: progress(1, 1)
        return {'exercise': prior}
    if folder.exists():
        attempt = folder/'attempts'/uuid.uuid4().hex
        attempt.mkdir(parents=True)
        if (folder/'workspace').exists(): shutil.move(str(folder/'workspace'), str(attempt/'workspace'))
        if prior: write_json(attempt/'run.json', prior)
    initial = (FIXTURES/'verification/flawed-avatar-report.md').read_text()
    record = run_analysis(store, 'EXERCISE', 'verification_exercise', requirement=source['requirement_doc'],
                          budget=3, cap=40, failures=0, batch_label='exercise',
                          workspace_root=folder/'workspace', instructions=source['instructions'],
                          execution={'mode': source.get('execution_mode', 'scripted'),
                                     'initial_draft': initial, 'cancelled': cancelled})
    record.update(source_run_id=source_id, exercise=True, supplied_draft=True,
                  requirement_page_id=source['requirement_page_id'], requirement_version=source['requirement_version'],
                  source_ticket_key=source['ticket_key'])
    write_json(folder/'run.json', record)
    store.save()
    if progress: progress(1, 1)
    return {'exercise': record}


def compare_summaries(before, after):
    for key in ('documents', 'settings'):
        if key in before and key in after and before[key] != after[key]:
            raise ValueError('Batches must use the same documents and model settings')
    criteria = {}
    improved, regressed = [], []
    for name in ("completeness", "clarity", "depth"):
        left = before["first_attempt"][name]["passed"]
        right = after["first_attempt"][name]["passed"]
        criteria[name] = [left, right]
        if right > left: improved.append(name)
        if right < left: regressed.append(name)
    if any(b.get('grader_errors') or b.get('graded', b['runs']) != b['runs'] or not b['runs'] or (b.get('documents') and len(b['documents']) != b['runs']) for b in (before, after)):
        verdict, keep = 'incomplete — retry failed reviews', False
    elif regressed: verdict, keep = "regression", False
    elif after["revisions_needed"] == 0: verdict, keep = "success", True
    elif improved: verdict, keep = "partial", True
    else: verdict, keep = "no effect", True
    return {"verdict": verdict, "keep": keep, "criteria": criteria, "runs": after["runs"], "revisions_needed": [before["revisions_needed"], after["revisions_needed"]], "improved": improved, "regressed": regressed}


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)
    store = Store(data_root())
    from .batch_jobs import BatchJobs
    jobs = BatchJobs(data_root())
    app.extensions['batch_jobs'] = jobs

    @app.before_request
    def guard_writes():
        if request.method in ('POST','PUT','PATCH','DELETE') and store.load_errors:
            return jsonify({'error':'Saved records need repair. Ask Coding chat to inspect them without resetting work; existing evidence remains available for submission.'}), 409
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.endpoint not in ('start_batch_job', 'start_verification_exercise', 'cancel_batch_job', 'capstone_analyze', 'capstone_decisions', 'capstone_resume'):
            if not jobs.gate.acquire(blocking=False):
                return jsonify({'error': 'Another action or batch is running. Wait for it to finish.'}), 409
            g.holds_write_gate = True

    @app.teardown_request
    def release_writes(error):
        if g.pop('holds_write_gate', False):
            jobs.gate.release()

    @app.post('/api/batch-jobs')
    def start_batch_job():
        payload = request.get_json(force=True)
        label = payload.get('label', 'v1')
        operation = payload.get('operation', 'batch')
        if operation not in ('batch','reviewer') or label not in ('v1','v2','new') or (operation == 'reviewer' and label != 'v1'):
            raise ValueError('Choose a practice batch, new-input check, or learning reviewer.')
        key = 'reviewer' if operation == 'reviewer' else label
        active = jobs.latest(key)
        if active and active['status'] in ('queued','running'):
            return jsonify(active), 202
        if operation == 'batch':
            if label != 'v1' and not batch_approved():
                raise ValueError('Save an accept, reject, or keep decision before the rerun.')
            if label == 'new' and not completed_batch('v2'):
                raise ValueError('Finish the practice rerun before checking new inputs.')
            if completed_batch(label):
                raise FileExistsError('This batch is already saved; completed evidence is unchanged.')
        elif not completed_batch('v1'):
            raise ValueError('Finish the baseline before running your learning reviewer.')
        elif not (batch_folder('v1')/'diagnosis.json').exists() and not (batch_folder('v1')/'proposal.json').exists():
            raise ValueError('Save your diagnosis in Learning before asking Coding chat to build the reviewer.')
        def run(progress):
            with app.app_context():
                if operation == 'reviewer':
                    result = analyze_batch(cancelled=lambda: jobs.cancelled(key))
                    progress(1, 1)
                    return {'proposal': result}
                return batch_run(store, label, progress=progress, cancelled=lambda: jobs.cancelled(key))
        return jsonify(jobs.start(key, 1 if operation == 'reviewer' else len(learning_files(label)), run)), 202

    @app.post('/api/batch-jobs/<job_id>/cancel')
    def cancel_batch_job(job_id):
        return jsonify(jobs.cancel(job_id))

    @app.post('/api/runs/<source_id>/verification-exercise')
    def start_verification_exercise(source_id):
        key = 'exercise-' + source_id
        def run(progress):
            with app.app_context():
                return verification_exercise(store, source_id, progress, lambda: jobs.cancelled(key))
        return jsonify(jobs.start(key, 1, run)), 202

    @app.get('/api/batch-jobs')
    def list_batch_jobs():
        with jobs.lock:
            return jsonify([dict(job) for job in jobs.jobs.values()])

    @app.get('/api/batch-jobs/latest')
    def latest_batch_job():
        return jsonify(jobs.latest(request.args.get('label', 'v1')))

    @app.get('/api/batch-jobs/<job_id>')
    def batch_job(job_id):
        job = jobs.get(job_id)
        return jsonify(job or {'error': 'Job not found'}), (200 if job else 404)

    @app.get("/")
    def index():
        if request.args.get('q'):
            from urllib.parse import urlencode
            return redirect('page/page-req-avatar-upload?' + urlencode({'q': request.args['q']}))
        return render_template("index.html", mode='Recommended settings' if is_scripted() else 'Live API — GPT-5.6 Luna',
                               model_settings=model_settings(), luna=LUNA)
    @app.get("/api/readiness")
    def readiness():
        from .readiness import inspect
        return jsonify(inspect(data_root()))

    @app.get("/api/health")
    def health(): return jsonify({"app": "loop-engineering-starter", "status": "ok",
                                 "run_id": os.environ.get("STARTER_RUN_ID"), **model_settings()})
    @app.get('/api/model-config')
    def model_config(): return jsonify(model_settings())
    @app.post('/api/model-config')
    def configure_model():
        data = request.get_json(force=True)
        return jsonify(save_settings(data.get('mode'), data.get('model')))
    @app.get("/api/pages")
    def pages(): return jsonify(store.pages)
    @app.get("/api/tickets")
    def tickets(): return jsonify(store.tickets)
    @app.get("/api/runs/<run_id>")
    def get_run(run_id): return jsonify(store.run(run_id) or {"error": "not found"}), (200 if store.run(run_id) else 404)
    @app.get("/api/batches")
    def batches(): return jsonify(store.batches)
    @app.get("/api/batches/<label>")
    def get_batch(label):
        batch = next((x for x in store.batches if x["label"] == label), None)
        return jsonify(batch or {"error": "not found"}), (200 if batch else 404)
    @app.post("/api/tickets")
    def create_ticket():
        data = request.get_json(silent=True) or request.form.to_dict(); nums = [int(x["key"].split("-")[1]) for x in store.tickets if x["key"].startswith("REV-")]
        if not isinstance(data.get('title'), str) or not data['title'].strip(): raise ValueError('Enter a ticket title.')
        linked = store.page(data.get('linked_page_id'))
        if not linked or linked['kind'] != 'requirement': raise ValueError('Choose an existing requirement page.')
        data['title'] = data['title'].strip()
        key = f"REV-{max(nums or [100]) + 1}"; ticket = {"key": key, "title": data["title"], "description": data.get("description", ""), "linked_page_id": data["linked_page_id"], "assignee": data.get("assignee", PEOPLE[1]), "status": "Open", "comments": [], "created_at": now(), "last_analyzed_version": None, "last_run_id": None}; store.tickets.append(ticket)
        try: run_analysis(store, key, "ticket_created", ticket=ticket)
        except Exception:
            store.tickets.remove(ticket)
            raise
        return jsonify(ticket), 201
    @app.post("/api/tickets/<key>/rerun")
    def rerun(key):
        ticket = store.ticket(key)
        if not ticket: return jsonify({"error": "not found"}), 404
        if ticket["status"] == "Done": return jsonify({"error": "Done tickets cannot be re-triggered"}), 409
        return jsonify(run_analysis(store, key, "manual_rerun", ticket=ticket))
    @app.post("/api/tickets/<key>/close")
    def close(key):
        ticket = store.ticket(key)
        if not ticket: return jsonify({"error": "not found"}), 404
        ticket["status"] = "Done"; store.save(); return jsonify(ticket)
    @app.post("/api/tickets/<key>/reopen")
    def reopen(key):
        ticket = store.ticket(key)
        if not ticket: return jsonify({'error': 'not found'}), 404
        ticket['status'] = 'Open'
        store.save()
        return jsonify(ticket)
    @app.post("/api/pages/<page_id>/save")
    def save_page(page_id):
        page = store.page(page_id)
        if not page or page["kind"] != "requirement": return jsonify({"error": "only requirement pages can be edited"}), 400
        data = request.get_json(silent=True) or request.form.to_dict()
        if not isinstance(data.get('body'), str) or not data['body'].strip(): raise ValueError('Enter requirement text before saving.')
        page["versions"].append({"n": len(page["versions"]) + 1, "author": data.get("author", PEOPLE[0]), "timestamp": now(), "body": data["body"]})
        store.save()
        retriggered = []
        for ticket in store.tickets:
            if ticket["linked_page_id"] == page_id and ticket["status"] != "Done": run_analysis(store, ticket["key"], "page_saved", ticket=ticket); retriggered.append(ticket["key"])
        store.save(); return jsonify({"page": page, "retriggered": retriggered})
    @app.get("/api/pages/<page_id>/compare")
    def compare(page_id):
        page = store.page(page_id)
        if not page: return jsonify({'error':'not found'}),404
        a, b = int(request.args.get('a', 0)), int(request.args.get('b', 0))
        if not 1 <= a <= len(page['versions']) or not 1 <= b <= len(page['versions']): raise ValueError('Choose two existing versions.')
        left, right = page["versions"][a - 1]["body"], page["versions"][b - 1]["body"]
        return jsonify({"diff": "".join(difflib.unified_diff(left.splitlines(True), right.splitlines(True), fromfile=f"version {a}", tofile=f"version {b}")), "from": parse_analysis(left).get("counts", {}), "to": parse_analysis(right).get("counts", {}), "runs": [store.run(v.get("run_id")) for v in (page["versions"][a-1], page["versions"][b-1])]})
    @app.errorhandler(500)
    def unexpected_error(error):
        return jsonify({'error':'The action could not finish. Ask Coding chat to inspect the app log without resetting saved work. Partial work remains submittable.'}), 500

    @app.errorhandler(ProviderFailure)
    def provider_error(error): return jsonify({'error': str(error)}),502
    @app.errorhandler(ExecutionFailure)
    def execution_error(error): return jsonify({'error': str(error)}),500
    @app.errorhandler(ValueError)
    def bad_input(error): return jsonify({'error':str(error)}),400
    @app.errorhandler(FileNotFoundError)
    def missing_evidence(error): return jsonify({'error':'Saved evidence is missing; restore it or run a new batch.'}),400
    @app.errorhandler(FileExistsError)
    def conflict(error): return jsonify({'error':str(error)}),409
    @app.get('/api/learning/instructions')
    def current_instructions(): return jsonify({'instructions':learning_instructions()})
    @app.post('/api/batches')
    def create_batch():
        label = request.get_json(force=True).get('label','v1')
        if label == 'v2' and not batch_approved('v1'):
            raise ValueError('Run v1, run the analyst, and approve a decision before v2.')
        return jsonify(batch_run(store, label)),201
    @app.post('/api/batches/<label>/analyze')
    def analyst(label): return jsonify(analyze_batch(label))
    @app.get('/api/batches/<label>/proposal')
    def proposal(label): return jsonify(read_json(batch_folder(label)/'proposal.json',{}))
    @app.get('/api/batches/<label>/approval')
    def approval(label): return jsonify(read_json(batch_folder(label)/'approval.json',{}))
    @app.post('/api/learning/approve')
    def learning_approve():
        data = request.get_json(force=True)
        return jsonify(approve_batch(data.get('label','v1'), data.get('decision','apply'), data.get('reason','')))
    @app.post('/api/learning/apply')
    def learning_apply(): return jsonify({'error':'Approve the saved batch proposal through Approve and apply'}),409
    @app.post('/api/learning/compare')
    def learning_compare():
        return jsonify(learning_comparison(store))

    @app.get('/api/learning/reflection')
    def get_reflection():
        return jsonify(read_json(batch_folder('v2')/'comparison.json', {}).get('reflection', {}))

    @app.get('/api/learning/diagnosis')
    def get_diagnosis():
        from .diagnosis import examples
        folder = batch_folder('v1')
        proposal = read_json(folder/'proposal.json', {})
        return jsonify({'diagnosis': proposal.get('learner_diagnosis') or read_json(folder/'diagnosis.json', {}),
                        'examples': examples(data_root()),
                        'locked': bool(proposal), 'legacy': bool(proposal and not proposal.get('learner_diagnosis'))})

    @app.post('/api/learning/diagnosis')
    def save_diagnosis():
        practice_evidence()
        folder = batch_folder('v1')
        if (folder/'proposal.json').exists() or (folder/'approval.json').exists():
            raise FileExistsError('Your original diagnosis is kept with the reviewer result. Explain what changed in your final reflection.')
        from .diagnosis import validate
        diagnosis = validate(data_root(), request.get_json(force=True))
        diagnosis['saved_at'] = now()
        write_json(folder/'diagnosis.json', diagnosis)
        return jsonify(diagnosis)

    @app.get('/api/learning/reflection/examples')
    def get_reflection_examples():
        from .evidence import reflection_examples
        return jsonify(reflection_examples(data_root()))

    @app.post('/api/learning/reflection')
    def save_reflection():
        data = request.get_json(force=True)
        comparison = learning_comparison(store)
        answers = {key: data.get(key) for key in ('mistake','decision','outcome')}
        if any(not isinstance(v, str) or not v.strip() or len(v) > 6000 for v in answers.values()):
            raise ValueError('Answer all three reflection questions. Keep each answer under 6000 characters.')
        reflection = {key: value.strip() for key, value in answers.items()}
        from .evidence import reflection_bindings
        reflection.update(updated_at=now(), run_ids=comparison['run_ids'],
                          references=reflection_bindings(data_root(), comparison, data.get('selected_examples')))
        comparison['reflection'] = reflection
        write_json(batch_folder('v2')/'comparison.json', comparison)
        return jsonify(reflection)

    @app.get("/ticket/<key>")
    def ticket_view(key):
        ticket = store.ticket(key)
        return render_template("detail.html", kind="ticket", title=f"{key} · Tracker", record=ticket, runs=[x for x in store.runs if x.get("ticket_key") == key and not x.get('exercise')]) if ticket else ("Not found", 404)
    @app.get('/api/learning/reports/<run_id>')
    def learning_report(run_id):
        record = store.run(run_id)
        if not record:
            return jsonify({'error': 'Saved report not found. Your other work is unchanged.'}), 404
        from .report_view import report_view
        return jsonify(report_view(record, request.args.get('draft', type=int) if 'draft' in request.args else 1))

    @app.get("/run/<run_id>")
    def run_view(run_id):
        record = store.run(run_id)
        if not record: return "Not found", 404
        draft = request.args.get('draft', type=int)
        if 'draft' in request.args and (draft is None or not 1 <= draft <= len(record['grading'])):
            raise ValueError('Choose an existing saved report draft.')
        return render_template("detail.html", kind="run", title=f"Run {run_id} · Trace", record=record, runs=[],
                               selected_draft=record['grading'][draft-1] if draft else None, draft_number=draft)
    @app.get("/page/<page_id>")
    def page_view(page_id):
        page = store.page(page_id)
        return render_template("detail.html", kind="page", title=page["title"] if page else "Not found", record=page, runs=[]) if page else ("Not found", 404)
    from .capstone import Controller
    controller = Controller(store, jobs)
    app.extensions['capstone'] = controller

    @app.get('/api/capstone')
    def capstone_state(): return jsonify(controller.state(request.args.get('candidate')))

    @app.post('/api/capstone/analyze')
    def capstone_analyze():
        payload = request.get_json(silent=True) or {}
        result = controller.start(new=payload.get('new_candidate') is True)
        return jsonify(result), 202

    @app.post('/api/capstone/decisions')
    def capstone_decisions():
        payload = request.get_json(force=True)
        return jsonify(controller.decide(payload.get('candidate'), payload.get('decision'), payload.get('reason', ''))), 202

    @app.post('/api/capstone/resume')
    def capstone_resume():
        return jsonify(controller.resume((request.get_json(silent=True) or {}).get('candidate'))), 202

    @app.post('/api/capstone/outcome')
    def capstone_outcome():
        payload = request.get_json(force=True)
        return jsonify(controller.note(payload.get('candidate'), payload.get('explanation')))

    @app.get('/api/capstone/reports/<run_id>')
    def capstone_report(run_id):
        from .report_view import report_view
        record = store.run(run_id)
        if not record: return jsonify({'error':'Saved report not found.'}), 404
        view = report_view(record, int(request.args.get('draft', 1)))
        view['phase'] = 'Before' if record.get('label') == 'baseline' else 'After'
        view['title'] = record.get('requirement_doc','').splitlines()[0].removeprefix('REQUIREMENT: ')
        return jsonify(view)

    return app
