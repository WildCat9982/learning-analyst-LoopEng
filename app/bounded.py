"""Run learner code and Step 4 reviews outside the Flask process.

This is a recovery boundary, not a security sandbox for hostile code.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class Stopped(ValueError):
    pass


def run(payload, timeout=180, cancelled=None):
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='loopeng-action-') as scratch:
        folder = Path(scratch)
        source, output = folder/'input.json', folder/'output.json'
        source.write_text(json.dumps(payload))
        env = dict(os.environ)
        env['PYTHONPATH'] = str(root)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['LOOPENG_PARENT_PID'] = str(os.getpid())
        if payload.get('action') == 'review' and payload['arguments'].get('mode_override') == 'live':
            from .models import LUNA
            env['LOOPENG_RUN_MODEL'] = LUNA
        with (folder/'worker.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'app.worker', str(source), str(output)],
                                       cwd=folder, env=env, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if cancelled and cancelled():
                        raise Stopped('Stopped. Completed reviews are saved; you can resume or submit partial work.')
                    if time.monotonic() >= deadline:
                        raise Stopped('This action took too long and was stopped. Fix or retry it; completed work is saved and can be submitted.')
                    time.sleep(.05)
                if not output.exists():
                    raise ValueError('The reviewer process stopped without a result. Check your code; saved work is unchanged.')
                if output.stat().st_size > 2_000_000:
                    raise ValueError('The reviewer returned too much data. Return a short proposal with evidence IDs.')
                result = json.loads(output.read_text())
                if not result.get('ok'):
                    raise ValueError(result.get('error', 'The action could not finish. Your saved work is unchanged.'))
                return result['result']
            finally:
                # Stop descendants too, including those left after the main worker exits.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
