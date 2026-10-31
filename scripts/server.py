"""Start or stop this workspace's app without keeping the agent's command open."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
STATE = RUNTIME / 'server.json'


def health(port):
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response)
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status', 'check-models'])
    parser.add_argument('--port', type=int, default=4000)
    args = parser.parse_args()
    if args.action == 'check-models':
        sys.path.insert(0, str(ROOT))
        from app.models import check_live_model
        try:
            print(json.dumps(check_live_model()))
        except ValueError as error:
            raise SystemExit(str(error)) from None
        return
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    running = health(saved['port']) if saved else {}
    owned = bool(saved and running.get('run_id') == saved['run_id'])
    if args.action == 'status':
        print(f"Running: http://127.0.0.1:{saved['port']}/ ({running.get('mode', 'unknown')} mode)" if owned else 'Not running')
        return
    if args.action == 'stop':
        if owned:
            os.kill(saved['pid'], signal.SIGTERM)
            for _ in range(40):
                if not health(saved['port']): break
                time.sleep(.1)
            else: raise SystemExit('App did not stop; inspect .runtime/app.log')
            STATE.unlink(missing_ok=True)
        print('Stopped' if owned else 'No running app owned by this workspace')
        return
    if owned:
        print(f"Already running: http://127.0.0.1:{saved['port']}/")
        return
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            raise SystemExit(f'Port {args.port} is occupied; no process was stopped')
    RUNTIME.mkdir(exist_ok=True)
    run_id = uuid.uuid4().hex
    env = dict(os.environ, STARTER_RUN_ID=run_id, PYTHONUNBUFFERED='1')
    env.setdefault('APP_DATA', str(ROOT/'data'))
    with (RUNTIME/'app.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, '-m', 'app', '--port', str(args.port)],
                                 cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
    for _ in range(100):
        if health(args.port).get('run_id') == run_id:
            STATE.write_text(json.dumps({'pid': child.pid, 'port': args.port, 'run_id': run_id}))
            print(f'Running: http://127.0.0.1:{args.port}/')
            return
        if child.poll() is not None: break
        time.sleep(.2)
    if child.poll() is None: child.terminate()
    raise SystemExit('Startup failed; inspect .runtime/app.log')


if __name__ == '__main__':
    main()
