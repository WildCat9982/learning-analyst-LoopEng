"""One background batch worker for the single-process learner app."""
import json
import threading
import uuid
from datetime import datetime, timezone


class BatchJobs:
    def __init__(self, root):
        self.folder = root / 'batch-jobs'
        self.gate = threading.Lock()
        self.lock = threading.RLock()
        self.jobs = {}
        self.stops = {}
        for path in sorted(self.folder.glob('*.json')):
            try:
                job = json.loads(path.read_text())
                if not isinstance(job, dict) or not all(k in job for k in ('id','label','status','created_at')): continue
            except (OSError, ValueError):
                continue
            if job['status'] in ('queued', 'running'):
                job.update(status='interrupted', error='The app restarted. Retry to resume saved reviews.')
                self._save(job)
            self.jobs[job['id']] = job

    def _save(self, job):
        job['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / (job['id'] + '.json')
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(job, indent=2) + '\n')
        temporary.replace(target)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def latest(self, label):
        with self.lock:
            jobs = [j for j in self.jobs.values() if j['label'] == label]
            return dict(max(jobs, key=lambda j: j['created_at'])) if jobs else None

    def start(self, label, total, run, acquired=False, metadata=None):
        with self.lock:
            for job in self.jobs.values():
                if job['status'] in ('queued', 'running'):
                    if job['label'] == label:
                        return dict(job)
                    raise FileExistsError('Another batch is running. Wait for it to finish.')
            if not acquired and not self.gate.acquire(blocking=False):
                raise FileExistsError('Another action is running. Wait for it to finish.')
            job = dict(id=uuid.uuid4().hex, label=label, status='queued', completed=0,
                       total=total, error=None, created_at=datetime.now(timezone.utc).isoformat())
            if metadata:job['metadata']=dict(metadata)
            self.jobs[job['id']] = job
            self.stops[job['id']] = threading.Event()
            try:
                self._save(job)
                threading.Thread(target=self._work, args=(job, run), daemon=True).start()
            except Exception:
                job.update(status='failed', error='Could not start the batch. Retry to resume saved reviews.')
                if not acquired: self.gate.release()
                self._save(job)
                raise
            return dict(job)

    def _update(self, job, **values):
        with self.lock:
            job.update(values)
            self._save(job)

    def _work(self, job, run):
        try:
            self._update(job, status='running')
            result = run(lambda completed, total: self._update(job, completed=completed, total=total))
            if self.stops[job['id']].is_set():
                self._update(job, status='interrupted', error='Stopped. Completed reviews are kept; resume or submit partial work.')
            elif result.get('grader_errors') or ('graded' in result and result['graded'] != result['runs']):
                self._update(job, status='failed', error='Some reviews could not be graded. Retry; completed reviews are kept.')
            elif result.get('exercise', {}).get('status') not in (None, 'satisfied'):
                self._update(job, status='failed', error='The exercise saved an unfinished revision. Inspect the feedback, retry, or submit partial work.')
            else:
                self._update(job, status='completed')
        except Exception as error:
            from .diagnostics import exception_details, failure_text, is_provider_error
            from .models import ProviderFailure
            from .bounded import Stopped
            if isinstance(error, Stopped):
                self._update(job, status='interrupted', error=str(error))
                return
            kind = 'provider' if isinstance(error, ProviderFailure) or is_provider_error(error) else 'local'
            details = exception_details(error, kind)
            self._update(job, status='failed', error_details=details,
                         error=failure_text(details) + ' Retry to resume saved reviews.')
        finally:
            self.gate.release()

    def cancelled(self, label):
        with self.lock:
            return any(j['label'] == label and self.stops.get(j['id']) is not None
                       and self.stops[j['id']].is_set() and j['status'] in ('queued','running')
                       for j in self.jobs.values())

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise ValueError('This action was not found. Refresh to reconnect.')
            if job['status'] in ('queued','running'):
                self.stops[job_id].set()
            return dict(job)
