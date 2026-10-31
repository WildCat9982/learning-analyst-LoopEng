"""Clean starter and learner contract for the isolated capstone."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin
import pytest
from app import core

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATA',str(tmp_path));return core.create_app().test_client()

def test_clean_starter_has_five_documents_and_unfinished_analyst():
    root=Path(__file__).resolve().parents[1]
    import ast
    tree=ast.parse((root/'app/learning_agent.py').read_text())
    assert any(isinstance(n,ast.FunctionDef) and n.name=='review' and len(n.args.args)==3 for n in tree.body)
    assert len(list((root/'fixtures/learning/practice').glob('*.md')))==5
    assert len(list((root/'fixtures/learning/new').glob('*.md')))==2
    import hashlib
    expected={'avatar-upload.md': 'e4cda89aea5b9c312ccf5f845e95bb6a4a36f08b51930819b6ac368f26b43531', 'password-reset.md': 'd6e4316f90cfbc19e2bcc5af48609ebdcdee568f63ff995aa516f9588dbfe889', 'notifications.md': '1b7caf6139b3a38e53d32b3356854124f05ae57cd836a6be41d8a70f8b6f820e'}
    for name in ('avatar-upload.md','password-reset.md','notifications.md'):
        assert hashlib.sha256((root/'fixtures/learning/practice'/name).read_bytes()).hexdigest()==expected[name]

def test_instructions_and_spec_have_one_capstone():
    root=Path(__file__).resolve().parents[1]
    if not (root.parent/'instructions.md').exists():pytest.skip('Instruction artifact authoring check; not a runtime workspace file.')
    text=(root.parent/'instructions.md').read_text()
    for title in ('1. Build your analyst','2. Run the analysis','3. Review and decide','4. Compare the results'):
        assert title in text
    assert text.count('class="capstone-step"')==4
    assert 'Need a starting prompt?' in text and '```chat' in text
    assert 'mandatory human-diagnosis' not in text and 'Check new inputs' not in text
    assert 'boundary or failure scenarios' not in (root/'fixtures/learning/instructions_v1.md').read_text()
    assert 'Do not generate activity' in (root/'spec.coding-agent-lab.md').read_text()

@pytest.mark.parametrize('prefix',['','/app-preview','/course/lesson/app-preview'])
def test_root_and_assets_work_with_preview_prefix(client,prefix):
    response=client.get('/',headers={'X-Forwarded-Prefix':prefix})
    assert response.status_code==200
    class Assets(HTMLParser):
        def __init__(self):super().__init__();self.urls=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='script' and 'src' in a:self.urls.append(a['src'])
            if tag=='link' and a.get('rel')=='stylesheet':self.urls.append(a['href'])
    parser=Assets();parser.feed(response.text)
    assert parser.urls and all(not p.startswith('/') for p in parser.urls)
    for asset in parser.urls:
        assert urljoin('https://lab.example'+prefix+'/',asset).startswith('https://lab.example'+prefix+'/')
        assert client.get('/'+asset).status_code==200
    assert client.get('/api/capstone').status_code==200
    assert client.get('/api/readiness').status_code==200
    assert client.post('/api/grading/submit').status_code==404
