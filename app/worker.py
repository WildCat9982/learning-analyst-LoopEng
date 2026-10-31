"""Private subprocess entry point. Never accepts browser-supplied code paths."""
import importlib.util
import json
import os
import signal
import threading
import time
import resource
import sys
from pathlib import Path


class LimitedModel:
    def __init__(self, model=None, count=None):
        self.model = model
        self.count = count if count is not None else [0]

    def get(self):
        if self.model is None:
            from .models import model_for, LUNA
            self.model = model_for('analyst', LUNA)
        return self.model

    def invoke(self, *args, **kwargs):
        self.count[0] += 1
        if self.count[0] > 8:
            raise ValueError('The learning reviewer exceeded eight model requests. Use the saved evidence in fewer requests.')
        return self.get().invoke(*args, **kwargs)

    def with_structured_output(self, *args, **kwargs):
        return LimitedModel(self.get().with_structured_output(*args, **kwargs), self.count)


def main(payload):
    if payload['action'] == 'reviewer':
        spec = importlib.util.spec_from_file_location('learner_review', payload['source'])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, 'review', None)
        if not callable(function):
            raise ValueError('Define review(instructions, saved_runs, model) in app/learning_agent.py.')
        result=function(payload['instructions'], payload['saved_runs'], LimitedModel())
        from pydantic import BaseModel
        return result.model_dump(mode='json') if isinstance(result,BaseModel) else result
    if payload['action'] == 'review':
        from .engine import execute_review
        return execute_review(**payload['arguments'])
    raise ValueError('Unknown background action')


if __name__ == '__main__':
    def stop_if_parent_exits():
        parent = int(os.environ.get('LOOPENG_PARENT_PID', os.getppid()))
        while True:
            if os.getppid() != parent:
                os.killpg(os.getpgrp(), signal.SIGKILL)
            time.sleep(.5)
    threading.Thread(target=stop_if_parent_exits, daemon=True).start()
    resource.setrlimit(resource.RLIMIT_FSIZE, (2_000_000, 2_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
    output = Path(sys.argv[2])
    try:
        result = {'ok': True, 'result': main(json.loads(Path(sys.argv[1]).read_text()))}
        json.dumps(result, allow_nan=False)
    except BaseException as error:
        from .diagnostics import safe_message
        if isinstance(error, SyntaxError):
            message = f'Fix the syntax error on line {error.lineno} of app/learning_agent.py.'
        elif isinstance(error, (ValueError, NotImplementedError, TypeError)):
            message = safe_message(str(error))[:700]
        else:
            message = f'The action stopped ({type(error).__name__}). Ask Coding chat to inspect the code. Saved work is unchanged.'
        result = {'ok': False, 'error': message}
    output.write_text(json.dumps(result, allow_nan=False))
