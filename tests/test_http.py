"""Real HTTP + separate agent containers + PostgreSQL, explicitly fixture model."""
import json,os,uuid
from pathlib import Path
import httpx,pytest
BASE=os.getenv('BASE_URL');pytestmark=pytest.mark.skipif(not BASE,reason='make test runs isolated containers')
@pytest.fixture(scope='session',autouse=True)
def require_fixture():
    if BASE and httpx.get(BASE+'/api/health').json().get('llm_mode')!='fixture':pytest.exit('Tests require isolated fixture backend; no real model call was made',returncode=2)
def api(method,path,who='mark',**kw):return httpx.request(method,BASE+path,headers={'X-Person':who},timeout=90,**kw)
def launch(agent='task-intake',data=None):
    r=api('POST','/api/runs',json={'agent':agent,'input':data or {'event_id':'E001'},'request_id':str(uuid.uuid4())});assert r.status_code==200,r.text;return r.json()
def test_real_container_closed_loop():
    initial=api('GET','/api/workspace').json();assert len(initial['tasks'])==2
    first=launch();assert first['status']=='needs_review',first
    assert first['output']['action']=='create' and 'PRIVATE-FINANCE' not in json.dumps(first)
    assert api('POST','/api/runs/'+first['id']+'/approve','anna',json={'version':1}).status_code==200
    second=launch(data={'event_id':'E002'});assert second['output']['task_id']=='TASK-E001'
    assert api('POST','/api/runs/'+second['id']+'/approve','anna',json={'version':1}).status_code==200
    task=next(t for t in api('GET','/api/workspace').json()['tasks'] if t['id']=='TASK-E001')
    assert task['status']=='done' and len(task['history'])==2
    assert launch()['id']==first['id']
    assert launch(data={'event_id':'E004'})['output']['action']=='no_action'
    assert launch(data={'event_id':'E003'})['output']['action']=='question'

def test_real_container_generic_and_brief():
    generic=launch('work-assistant',{'request':'Объясни путь от сообщения до решения','skill':'auto','project_id':'all'})
    assert generic['status']=='needs_review',generic
    assert generic['output']['selected_skill'] and len(generic['model_calls'])==2
    assert generic['model_calls'][-1]['skill_refs']
    brief=launch('daily-brief',{'project_id':'all'});assert brief['status']=='needs_review'
    assert brief['output']['source_refs']

def test_agent_manifest_examples():
    root=Path(__file__).resolve().parents[1]
    for path in sorted((root/'agents').glob('*/tests/cases.json')):
        if path.parent.parent.name.startswith('_'):continue
        for case in json.loads(path.read_text()):
            row=launch(path.parent.parent.name,case['input']);assert row['status'] in ['needs_review','approved'],row
            for field,value in case['expect'].items():
                if field=='contains':assert all(text in row['output']['markdown'] for text in value)
                else:assert row['output'][field]==value
