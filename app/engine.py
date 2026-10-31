"""Real DeepAgents tool execution; scripted responses replace only the model.

The scripted model never calls a provider. Traces come from messages returned by
DeepAgents, and grading reads the file that its filesystem tools actually wrote.
"""
import os
import re
import uuid
from pathlib import Path
from typing import Any
from pydantic import Field
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from .models import is_scripted, provider_failure

HEADINGS = ['Confirmed Facts', 'Ambiguities', 'Clarification Questions', 'Assumptions', 'Summary']


def section(text, name):
    match = re.search(r'^## ' + re.escape(name) + r'\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return match.group(0).rstrip() if match else ''


class ScriptedReview(BaseChatModel):
    """scripted-stand-in: a fake that returns declared responses, never results."""
    queue: list = Field(default_factory=list)
    previous: dict | None = None
    document: str = ''
    first_text: str = ''
    final_text: str = ''
    initialized: bool = False
    call_count: int = 0
    variant: str = ''
    injected: bool = False
    recovery: dict | None = None

    @property
    def _llm_type(self): return 'scripted-stand-in'
    def bind_tools(self, tools, **kwargs): return self
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from .core import analysis_markdown
        self.call_count += 1
        last = messages[-1]
        def call(name, args):
            item = {'name': name, 'args': args, 'id': uuid.uuid4().hex}
            self.previous = item
            return AIMessage(content='', tool_calls=[item])
        if self.variant == 'loop_forever':
            result = call('fetch_requirement', {'ticket_key': 'UPL-310'})
        elif isinstance(last, ToolMessage) and last.name == 'fetch_requirement' and str(last.content).lower().startswith('error'):
            result = call('fetch_requirement', {'ticket_key': 'UPL-310'})
        elif not self.initialized and not any(isinstance(m, ToolMessage) and m.name == 'fetch_requirement' for m in messages):
            result = call('fetch_requirement', {'ticket_key': 'UPL-310'})
        elif isinstance(last, ToolMessage) and last.name == 'edit_file' and ('Error' in str(last.content) or last.status == 'error') and self.recovery:
            self.queue.insert(0, self.recovery); self.recovery = None
            result = call('read_file', {'file_path': '/analysis.md'})
        else:
            if not self.initialized:
                self.document = str(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'fetch_requirement'))
                title, *clauses = self.document.strip().splitlines()
                enhanced = 'Resolved by:' in str(messages[0].content)
                self.first_text = analysis_markdown(title, clauses, enhanced or title == 'REQUIREMENT: Search')
                self.final_text = analysis_markdown(title, clauses, True)
                # Match the video's first-attempt exception in document 3.
                # The normal grader sees a genuinely missing fact in the file.
                if title == 'REQUIREMENT: API Rate Limiting' and not enhanced:
                    self.first_text = self.first_text.replace('- ' + clauses[-1] + '\n', '', 1)
                    self.first_text = self.first_text.replace(
                        f'The document states {len(clauses)} facts',
                        f'The document states {len(clauses) - 1} facts', 1)
                skeleton = section(self.first_text, HEADINGS[0]) + '\n\n' + '\n\n'.join('## '+h for h in HEADINGS[1:]) + '\n'
                self.queue = [{'name': 'write_file', 'args': {'file_path': '/analysis.md', 'content': skeleton}}]
                for h in HEADINGS[1:]:
                    item = {'name': 'edit_file', 'args': {'file_path': '/analysis.md', 'old_string': '## '+h, 'new_string': section(self.first_text, h)}}
                    if h == 'Ambiguities' and 'API Rate Limiting' in title:
                        self.recovery = item
                        item = {'name': 'edit_file', 'args': {**item['args'], 'old_string': '## '}}
                    self.queue.append(item)
                if self.variant == 'self_edit': self.queue.insert(0, {'name': 'write_file', 'args': {'file_path': '/memories/AGENTS.md', 'content': 'hacked'}})
                if self.variant == 'escape': self.queue.insert(0, {'name': 'read_file', 'args': {'file_path': '../fixtures/tickets.json'}})
                self.initialized = True
            if isinstance(last, HumanMessage) and str(last.content).startswith('Grader feedback:') and self.variant != 'never_fixes':
                if self.variant == 'verification_exercise':
                    self.queue = [{'name': 'edit_file', 'args': {'file_path': '/analysis.md', 'old_string': self.first_text, 'new_string': self.final_text}}]
                else:
                    self.queue = [
                    {'name': 'edit_file', 'args': {'file_path': '/analysis.md', 'old_string': section(self.first_text, h), 'new_string': section(self.final_text, h)}}
                    for h in HEADINGS if section(self.first_text, h) != section(self.final_text, h)
                ]
            if self.queue:
                item = self.queue.pop(0); result = call(item['name'], item['args'])
            else: result = AIMessage(content='Review complete.')
        return ChatResult(generations=[ChatGeneration(message=result)])


def build_review_agent(root, requirement, cap, failures, mode_override=None, initial_draft=None):
    root = Path(root)
    if not (root / 'memories' / 'AGENTS.md').exists(): raise FileNotFoundError('missing /memories/AGENTS.md')
    attempts = 0
    @tool
    def fetch_requirement(ticket_key: str) -> str:
        """Fetch the current requirement by its tracker identifier. Retry transient errors."""
        nonlocal attempts
        if ticket_key != 'UPL-310': return f'Error fetching ticket {ticket_key}'
        attempts += 1
        if attempts <= failures:
            return ['Error: 503 Service Unavailable — the tracker is busy, retry', 'Error: request timed out after 30 s'][min(attempts-1, 1)]
        return requirement
    scripted = mode_override == 'scripted' if mode_override else is_scripted()
    if scripted:
        model = ScriptedReview(variant=os.environ.get('SCRIPTED_VARIANT', ''))
    else:
        from .models import model_for
        from .models import LUNA
        model = model_for('review', LUNA if mode_override else None)
    if scripted and initial_draft is not None:
        from .core import analysis_markdown
        title, *clauses = requirement.strip().splitlines()
        model.variant = 'verification_exercise'
        model.initialized = True
        model.first_text = initial_draft
        model.final_text = analysis_markdown(title, clauses, True)
    agent = create_deep_agent(model=model, tools=[fetch_requirement], backend=FilesystemBackend(root_dir=root, virtual_mode=True), memory=['/memories/AGENTS.md'], system_prompt='Follow /memories/AGENTS.md to review the requirement.', permissions=[FilesystemPermission(operations=['write'], paths=['/memories/**', '/skills/**'], mode='deny')], middleware=[ModelCallLimitMiddleware(run_limit=cap, exit_behavior='end')])
    return agent


def execute_review(root, requirement, budget, cap, failures, mode_override=None, rubric=None, initial_draft=None, checkpoint=None):
    from .core import grader, read_json, write_json
    from langchain_core.messages import messages_to_dict, messages_from_dict
    scripted = mode_override == 'scripted' if mode_override else is_scripted()
    agent = build_review_agent(root, requirement, cap, failures, mode_override, initial_draft)
    messages = [HumanMessage(content='The requirement is tracked as ticket UPL-310; fetch it to begin.')]
    if initial_draft is not None:
        (Path(root)/'analysis.md').write_text(initial_draft)
    grading = []
    turns = 0
    saved = read_json(Path(checkpoint), {}) if checkpoint else {}
    if saved:
        if saved['requirement'] != requirement or saved['instructions'] != (Path(root)/'memories/AGENTS.md').read_text():
            raise ValueError('Restore the saved first-attempt inputs before resuming.')
        messages = messages_from_dict(saved['messages'])
        grading, turns = saved['grading'], saved['turns']
        (Path(root)/'analysis.md').write_text(saved['text'])
    start = saved.get('attempt', 0)
    pending = saved.get('pending', False)
    status = saved.get('status', 'running')
    text = saved.get('text', '')
    def freeze(attempt, pending, status):
        if checkpoint:
            write_json(Path(checkpoint), {'requirement': requirement,
                'instructions': (Path(root)/'memories/AGENTS.md').read_text(),
                'messages': messages_to_dict(messages), 'grading': grading,
                'text': text, 'turns': turns, 'attempt': attempt, 'pending': pending, 'status': status,
                **({'final_status': final_status} if status=='complete' else {})})
    # Recover a crash after a verifier response was saved but before the next step.
    if status == 'evaluated' and grading:
        last=grading[-1]
        if last['result'] in ('satisfied','failed') or start >= budget or turns >= cap:
            saved['status']='complete'
            saved['final_status']=last['result'] if last['result'] in ('satisfied','failed') else 'max_iterations_reached'
        else:
            messages.append(HumanMessage(content='Grader feedback: '+last['explanation']+'\n'+'\n'.join(c.get('gap','') for c in last['criteria'])))
            start+=1
    attempts = [] if saved.get('status') == 'complete' else range(start, budget+1 if budget else 1)
    if not attempts and saved.get('status') == 'complete': status = saved['final_status']
    for attempt in attempts:
        try:
            result = ({'messages': messages} if pending or (initial_draft is not None and attempt == 0) else
                      agent.invoke({'messages': messages, 'run_model_call_count': turns}, config={'recursion_limit': max(100, cap*4)}))
        except Exception as exc:
            if scripted:
                raise
            raise provider_failure('review', exc) from exc
        messages = result['messages']
        file = Path(root) / 'analysis.md'
        text = file.read_text() if file.exists() else ''
        turns = sum(isinstance(m, AIMessage) and not str(m.content).startswith('Model call limits exceeded:') for m in messages)
        if turns >= cap and not text:
            status = 'failed'; break
        if not budget: status = 'ungraded'; break
        if scripted and os.environ.get('SCRIPTED_VARIANT') == 'grader_error_doc02' and requirement.startswith('REQUIREMENT: Report Export'):
            grading.append({'iteration': attempt+1, 'result': 'grader_error', 'explanation': 'Injected grader error', 'criteria': [], 'analysis_markdown': text})
            status = 'grader_error'; break
        # Freeze the exact report before any verifier request.
        freeze(attempt, True, 'pending_verification')
        pending = False
        # Both evaluators receive exactly the bytes read from this saved file.
        try:
            if scripted:
                evaluation = grader(text, requirement)
            else:
                from .models import evaluate
                from .core import FIXTURES
                rubric = rubric or Path(os.environ.get('RUBRIC_PATH', FIXTURES / 'rubric.txt')).read_text()
                evaluation = evaluate(text, requirement, rubric)
        except ValueError as error:
            grading.append({'iteration': attempt+1, 'result': 'grader_error',
                            'explanation': str(error), 'criteria': [], 'analysis_markdown': text,
                            'tool_calls': [{'name': 'read_file', 'args': {'file_path': '/analysis.md'}, 'result': text}]})
            status = 'grader_error'
            break
        evaluation['tool_calls'] = [{'name': 'read_file', 'args': {'file_path': '/analysis.md'}, 'result': text}]
        grading.append({'iteration': attempt+1, **evaluation})
        freeze(attempt, False, 'evaluated')
        if evaluation['result'] in ('satisfied', 'failed'): status = evaluation['result']; break
        if attempt == budget or turns >= cap: status = 'max_iterations_reached'; break
        messages.append(HumanMessage(content='Grader feedback: ' + evaluation['explanation'] + '\n' + '\n'.join(c.get('gap', '') for c in evaluation['criteria'])))
        freeze(attempt+1, False, 'next_revision')
    if checkpoint and status != 'grader_error':
        final_status=status
        freeze(attempt if 'attempt' in locals() else start, False, 'complete')
    trace, serialized = [], []
    for m in messages:
        entry = {'type': m.type, 'content': m.content}
        if isinstance(m, AIMessage) and str(m.content).startswith('Model call limits exceeded:'):
            serialized.append(entry)
            continue
        if isinstance(m, AIMessage):
            entry['tool_calls'] = m.tool_calls
            # Retain only provider identifiers and numeric usage, never headers or credentials.
            metadata = m.response_metadata or {}
            entry['model_metadata'] = {key: metadata[key] for key in ('model_name', 'model', 'request_id')
                                       if isinstance(metadata.get(key), str)}
            usage = m.usage_metadata or metadata.get('token_usage') or {}
            entry['token_usage'] = {key: value for key, value in usage.items()
                                    if key in ('input_tokens', 'output_tokens', 'total_tokens', 'prompt_tokens', 'completion_tokens')
                                    and isinstance(value, int)}
            trace.append({'step': len(trace)+1, 'actor': 'Agent action', 'action': '; '.join(c['name']+' '+str(c['args']) for c in m.tool_calls) or str(m.content)})
        if isinstance(m, ToolMessage):
            from .core import compact
            entry.update(tool_call_id=m.tool_call_id, status=m.status)
            trace.append({'step': len(trace)+1, 'actor': 'Tool', 'action': m.name or 'tool', 'detail': compact(m.content)})
        serialized.append(entry)
    if turns >= cap and status != 'satisfied':
        trace.append({'step': len(trace)+1, 'actor': 'Harness', 'action': f'Stops: turn limit of {cap} reached'})
    return text, grading, status, turns, trace, serialized
