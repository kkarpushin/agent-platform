"""Real PostgreSQL in random schemas; actual agents use an explicit fixture model."""
import importlib.util,json,os,shutil,sys,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import httpx,psycopg,pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mayak_backend',ROOT/'platform/app.py');backend=importlib.util.module_from_spec(spec);sys.modules[spec.name]=backend;spec.loader.exec_module(backend)

def load_agent(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'agents'/name/'agent.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.fixture
def system(tmp_path,monkeypatch):
    dsn=os.getenv('TEST_DATABASE_URL')
    if not dsn:pytest.skip('Требуется PostgreSQL через make test')
    schema='test_'+uuid.uuid4().hex
    with psycopg.connect(dsn,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    for folder in ('config','knowledge','agents','skills','processes'):shutil.copytree(ROOT/folder,tmp_path/folder)
    names=['task-intake','daily-brief','work-assistant']
    settings=backend.Settings(root=tmp_path,database_url=make_conninfo(dsn,options=f'-c search_path={schema}'),llm_mode='fixture',auth_mode='demo',agent_urls={n:'http://'+n for n in names},cli_worker_token='x'*40)
    app=backend.create_app(settings);monkeypatch.setattr(backend,'resolve_agent_addresses',lambda _: {'172.30.0.21'})
    original=httpx.Client;state={'calls':0,'tokens':[],'behavior':'ok','internal':[]}
    with TestClient(app) as client:
        class Context:
            def __init__(self,token):self.headers={'Authorization':'Bearer '+token}
            def get(self,section,query=''):
                response=client.get('/internal/context',params={'section':section,'q':query},headers=self.headers)
                if response.status_code!=200:raise ValueError(response.json()['detail'])
                return response.json()['records']
            search=get
            def workspace(self):
                result=client.get('/internal/workspace',headers=self.headers).json();state.setdefault('workspaces',[]).append(result);return result
            def skills(self):return client.get('/internal/skills',headers=self.headers).json()['skills']
            def llm(self,purpose,data,system,prompt,max_tokens=2048,response_schema=None,skill_name=None):
                response=client.post('/internal/llm',headers=self.headers,json=dict(purpose=purpose,data=data,system=system,prompt=prompt,max_tokens=max_tokens,response_schema=response_schema,skill_name=skill_name));state['internal'].append(response)
                if response.status_code!=200:raise ValueError(response.json()['detail'])
                return response.json()['text']
        def handler(request):
            state['calls']+=1;payload=json.loads(request.content);state['tokens'].append(payload['run_token'])
            if state['behavior']=='timeout':raise httpx.ReadTimeout('private error')
            if state['behavior']=='invalid':return httpx.Response(200,json={'output':{'private':'SECRET'},'steps':[]})
            if state['behavior']=='change_source_before_workspace':
                source=tmp_path/'knowledge/projects/P01.md';source.write_text(source.read_text()+'\nИзменение после снимка, перед чтением агента.\n')
                assert client.post('/api/sync',headers={'X-Person':'anna'}).status_code==200
            try:
                out,steps=load_agent(request.url.host).app.agent_function(payload['input'],Context(payload['run_token']))
                if state['behavior']=='bad_source':out['source_refs']=['F01']
                if state['behavior']=='echo':out['markdown']=payload['run_token']
                return httpx.Response(200,json={'output':out,'steps':steps})
            except ValueError as e:return httpx.Response(422,json={'detail':str(e)})
        monkeypatch.setattr(backend.httpx,'Client',lambda *a,**kw:original(*a,**kw,transport=httpx.MockTransport(handler)))
        yield client,app,state,tmp_path
    with psycopg.connect(dsn,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

def launch(client,event='E001',person='mark',key=None,agent='task-intake',input=None):
    data=input if input is not None else ({'event_id':event} if agent=='task-intake' else {'project_id':'all'})
    return client.post('/api/runs',headers={'X-Person':person},json={'agent':agent,'input':data,'request_id':key or str(uuid.uuid4())})

def approve(c,run,version=None):return c.post('/api/runs/'+run['id']+'/approve',headers={'X-Person':'anna'},json={'version':version or run['current_version'],'note':'Проверены источники и поля'})

def test_role_filtered_fts_and_workspace(system):
    c,_,_,_=system
    assert len(c.get('/api/bootstrap').json()['layers'])==9
    assert c.get('/api/knowledge?section=projects&q=тексты').json()['records'][0]['id']=='P01'
    assert c.get('/api/knowledge?section=finance').json()=={'records':[],'hidden_count':1}
    assert c.get('/api/knowledge?section=finance',headers={'X-Person':'irina'}).json()['records'][0]['id']=='F01'
    ws=c.get('/api/workspace').json();assert len(ws['tasks'])==2 and len(ws['inbox'])==5
    assert not c.get('/api/workspace',headers={'X-Person':'irina'}).json()['access']

def test_denied_before_agent_and_invalid_schema(system):
    c,_,state,_=system
    assert launch(c,person='olga').status_code==403
    assert launch(c,input={'event_id':'E001','secret':'PRIVATE'}).status_code==422
    assert state['calls']==0

def test_canonical_event_dedup_and_revoked_token(system):
    c,_,state,_=system
    first=launch(c).json();second=launch(c,key='other-request').json()
    assert first['id']==second['id'] and state['calls']==1 and first['status']=='needs_review'
    assert c.get('/internal/workspace',headers={'Authorization':'Bearer '+state['tokens'][0]}).status_code==401
    assert any(e['section']=='finance' and e['hidden_count']==1 and not e['records'] for e in first['context_events'])
    assert 'PRIVATE-FINANCE' not in json.dumps(first)

def test_full_loop_creates_then_updates_same_task_with_history(system):
    c,_,_,_=system
    first=launch(c).json();assert first['output']['action']=='create'
    assert len(c.get('/api/workspace').json()['tasks'])==2
    applied=approve(c,first);assert applied.status_code==200,applied.text
    assert applied.json()['task_application']['task_id']=='TASK-E001'
    assert approve(c,first).status_code==200
    second=launch(c,'E002').json();assert second['output']['action']=='update'
    assert approve(c,second).status_code==200
    tasks=c.get('/api/workspace').json()['tasks'];assert len(tasks)==3
    task=next(t for t in tasks if t['id']=='TASK-E001');assert task['status']=='done' and task['version']==2
    assert [h['snapshot']['status'] for h in task['history']]==['blocked','done']
    duplicate=launch(c,'E004').json();assert duplicate['output']['action']=='no_action'
    assert approve(c,duplicate).json()['task_application'] is None
    question=launch(c,'E003').json();assert question['output']['action']=='question'
    assert c.get('/api/workspace').json()['attention']['open_questions']==1
    assert len(c.get('/api/workspace').json()['tasks'])==3

def test_exact_revision_and_no_reedit_after_application(system):
    c,_,_,_=system;run=launch(c).json();url='/api/runs/'+run['id']
    assert c.post(url+'/approve',json={'version':1}).status_code==403
    edited=c.post(url+'/revisions',json={'base_version':1,'markdown':'Уточнено пояснение; поля задачи прежние.'}).json()
    assert edited['current_version']==2 and edited['versions'][0]['output']==run['output']
    assert approve(c,run,1).status_code==409
    assert approve(c,edited).status_code==200
    assert c.post(url+'/revisions',json={'base_version':2,'markdown':'Поздняя правка'}).status_code==409
    assert c.get(url,headers={'X-Person':'lev'}).status_code==404

def test_changed_source_blocks_approval_and_sync_is_atomic(system):
    c,_,_,root=system;run=launch(c).json()
    original=c.get('/api/knowledge').json()
    bad=root/'knowledge/projects/broken.md';bad.write_text('---\nid: broken\n---\n')
    assert c.post('/api/sync',headers={'X-Person':'anna'}).status_code==422
    assert c.get('/api/knowledge').json()==original;bad.unlink()
    source=root/'knowledge/projects/P01.md';source.write_text(source.read_text()+'\nУточнение владельца.\n')
    assert c.post('/api/sync',headers={'X-Person':'anna'}).status_code==200
    assert approve(c,run).status_code==409
    assert c.get('/api/runs/'+run['id']).json()['source_warnings']

def test_stale_task_version_blocks_second_update(system):
    c,app,_,_=system;first=launch(c).json();approve(c,first)
    pending=launch(c,'E002').json()
    with app.state.db() as connection:connection.execute("UPDATE tasks SET version=version+1 WHERE id='TASK-E001'")
    assert approve(c,pending).status_code==409
    assert c.get('/api/runs/'+pending['id']).json()['status']=='needs_review'

@pytest.mark.parametrize('behavior',['timeout','invalid','bad_source','echo'])
def test_bad_agent_never_commits_or_echoes_private_content(system,behavior):
    c,_,state,_=system;state['behavior']=behavior;run=launch(c).json()
    assert run['status']=='error' and run['versions']==[] and run['output'] is None
    assert state['tokens'][0] not in json.dumps(run) and 'SECRET' not in json.dumps(run)
    assert len(c.get('/api/workspace').json()['tasks'])==2

def test_cli_unavailable_is_error_never_fixture_fallback(system):
    c,app,_,_=system;app.state.settings.llm_mode='cli';run=launch(c).json()
    assert run['status']=='error' and run['output'] is None
    assert run['model_calls'][0]['mode']=='cli' and run['model_calls'][0]['status']=='error'
    assert run['cost_usd'] is None

def test_generic_new_skill_runs_without_core_code_change(system):
    c,_,_,root=system;p=root/'skills/meeting-check';p.mkdir();(p/'SKILL.md').write_text('---\nname: meeting-check\ndescription: "Проверить план встречи"\nexecution: draft\nroles: [sales, ceo]\ncontext: [projects, rules]\n---\nПокажи неизвестное и вопросы участникам.\n')
    assert c.post('/api/sync',headers={'X-Person':'anna'}).status_code==200
    run=launch(c,agent='work-assistant',input={'request':'Проверь план встречи проекта','skill':'meeting-check','project_id':'P01'}).json()
    assert run['status']=='needs_review',run
    assert run['output']['selected_skill']=='meeting-check'
    assert run['model_calls'][0]['skill_refs'][0]['name']=='meeting-check'
    denied=launch(c,person='olga',agent='work-assistant',input={'request':'Проверь план встречи','skill':'meeting-check','project_id':'all'}).json()
    assert denied['status']=='error'

def test_daily_brief_does_not_mutate_shared_tasks(system):
    c,_,_,_=system;before=c.get('/api/workspace').json()['tasks']
    run=launch(c,agent='daily-brief',person='olga').json()
    assert run['status']=='needs_review' and run['model_calls'][0]['skill_refs']
    assert c.get('/api/workspace').json()['tasks']==before

def test_person_tokens_ignore_employee_header(system):
    c,app,_,_=system;app.state.settings.auth_mode='token';app.state.settings.person_tokens={'private-test':'mark'}
    assert c.get('/api/bootstrap',headers={'X-Person':'anna'}).status_code==401
    h={'Authorization':'Bearer private-test','X-Person':'anna'}
    assert c.get('/api/bootstrap',headers=h).json()['person']['id']=='mark'
    assert c.post('/api/sync',headers=h).status_code==403

@pytest.mark.parametrize('peer',['172.30.0.21','::ffff:172.30.0.21'])
def test_agent_cannot_impersonate_user_or_claim_cli_jobs(system,peer):
    c,app,_,_=system;agent=TestClient(app,client=(peer,5000));headers={'X-Person':'anna','X-Forwarded-For':'127.0.0.1','Authorization':'Bearer '+'x'*40}
    for path in ['/api/bootstrap','/api/workspace','/api/knowledge?section=finance','/api/runs','/api/memory','/docs','/','/app.js']:
        assert agent.get(path,headers=headers).status_code==403
    assert agent.post('/api/cli/claim',headers=headers,json={'worker_id':'w','provider':'codex'}).status_code==403
    assert agent.get('/internal/workspace',headers=headers).status_code==401
    agent.close()

def test_network_gate_fails_closed(system,monkeypatch):
    c,_,_,_=system
    def unavailable(_):raise OSError('dns')
    monkeypatch.setattr(backend,'resolve_agent_addresses',unavailable)
    assert c.get('/api/bootstrap').status_code==503
    assert c.get('/api/health').status_code==200

def test_inbox_idempotency_and_immutable_event(system):
    c,_,_,_=system;body={'event_id':'NEW-01','project_id':'P01','text':'Нужен проверяемый результат','author':'Марк','received_at':'2026-10-21T09:00:00+00:00'}
    assert c.post('/api/inbox',json=body).json()['created']
    assert not c.post('/api/inbox',json=body).json()['created']
    assert c.post('/api/inbox',json={**body,'text':'Другая информация'}).status_code==409

def test_cli_queue_token_claim_and_duplicate_completion(system):
    c,app,_,_=system;worker={'worker_id':'testworker','provider':'codex'};h={'Authorization':'Bearer '+'x'*40}
    assert c.post('/api/cli/heartbeat',json=worker).status_code==401
    assert c.post('/api/cli/heartbeat',headers=h,json=worker).status_code==200
    assert c.get('/api/health').json()['cli_worker']['connected']
    # Explicit queue fixtures test protocol, not a real model invocation.
    run=launch(c).json();job=uuid.uuid4()
    with app.state.db() as connection:
        connection.execute("UPDATE runs SET status='running' WHERE id=%s",(run['id'],))
        call=connection.execute('SELECT id FROM model_calls WHERE run_id=%s',(run['id'],)).fetchone()['id']
        connection.execute("INSERT INTO cli_jobs(id,call_id,run_id,request,status) VALUES(%s,%s,%s,%s,'queued')",(job,call,run['id'],psycopg.types.json.Jsonb({'prompt':'test'})))
    claimed=c.post('/api/cli/claim',headers=h,json=worker).json()['job'];assert claimed['id']==str(job)
    assert c.post('/api/cli/claim',headers=h,json=worker).json()['job'] is None
    result={'text':'{}','model':'controlled-test','provider':'codex','input_tokens':1,'output_tokens':1,'usage':{},'duration_ms':10,'cost_usd':None}
    body={'claim_token':claimed['claim_token'],'status':'completed','result':result}
    path='/api/cli/jobs/'+str(job)+'/complete'
    assert c.post(path,headers=h,json=body).status_code==200
    assert c.post(path,headers=h,json=body).status_code==200
    assert c.post(path,headers=h,json={**body,'result':{**result,'text':'different'}}).status_code==409

def test_stale_proposal_refresh_preserves_old_run(system):
    c,_,_,root=system;old=launch(c).json()
    source=root/'knowledge/rules/R02.md';source.write_text(source.read_text()+'\nНовая проверенная оговорка владельца.\n')
    c.post('/api/sync',headers={'X-Person':'anna'})
    assert approve(c,old).status_code==409
    refreshed=c.post('/api/runs',json={'agent':'task-intake','input':{'event_id':'E001'},'request_id':str(uuid.uuid4()),'refresh':True})
    assert refreshed.status_code==200,refreshed.text
    new=refreshed.json();assert new['id']!=old['id'] and new['status']=='needs_review'
    assert c.get('/api/runs/'+old['id']).json()['versions']==old['versions']
    assert approve(c,old).status_code==409 and approve(c,new).status_code==200

def test_concurrent_creates_cannot_duplicate_same_project_snapshot(system):
    c,_,_,_=system
    first=launch(c,'E001').json();duplicate=launch(c,'E004').json()
    assert first['output']['action']==duplicate['output']['action']=='create'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda row:approve(c,row),[first,duplicate]))
    assert sorted(r.status_code for r in results)==[200,409]
    assert len(c.get('/api/workspace').json()['tasks'])==3

def test_concurrent_conflicting_event_payload_rejected(system):
    c,_,_,_=system
    body={'event_id':'CONCURRENT','project_id':'P01','text':'Первое сообщение','author':'Марк','received_at':'2026-10-21T09:00:00+00:00'}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda text:c.post('/api/inbox',json={**body,'text':text}),['Первое сообщение','Другое сообщение']))
    assert sorted(r.status_code for r in results)==[200,409]

def test_bound_skill_role_checked_before_agent(system):
    c,_,state,root=system;p=root/'skills/task-intake/SKILL.md';text=p.read_text();text=text.replace('description:', 'roles: [ceo]\ndescription:',1);p.write_text(text)
    assert c.post('/api/sync',headers={'X-Person':'anna'}).status_code==200
    assert launch(c).status_code==403 and state['calls']==0
    assert not any(s['name']=='task-intake' for s in c.get('/api/bootstrap').json()['skills'])

def test_request_key_conflict_checked_before_event_repeat(system):
    c,_,_,_=system
    assert launch(c,key='one-request').status_code==200
    assert launch(c,'E002',key='one-request').status_code==409

def test_draft_skill_context_does_not_receive_undeclared_workspace(system,monkeypatch):
    c,_,_,root=system;p=root/'skills/rules-only';p.mkdir();(p/'SKILL.md').write_text('---\nname: rules-only\ndescription: "Объяснить правила"\nexecution: draft\nroles: [sales]\ncontext: [rules]\n---\nОбъясни только правила.\n')
    c.post('/api/sync',headers={'X-Person':'anna'})
    original=backend.fixture_response;captured=[]
    def inspect(body):
        if body.purpose=='work_assistant':captured.append(body.data)
        return original(body)
    monkeypatch.setattr(backend,'fixture_response',inspect)
    run=launch(c,agent='work-assistant',input={'request':'Объясни правила работы','skill':'rules-only','project_id':'all'}).json()
    assert run['status']=='needs_review',run
    assert set(r['id'] for r in captured[0]['sources'])=={'R01','R02'}
    assert not captured[0]['workspace']['tasks'] and not captured[0]['workspace']['inbox'] and not captured[0]['workspace']['projects']

def test_failed_cli_structured_answer_retains_actual_usage(system):
    import time
    c,app,_,_=system;app.state.settings.llm_mode='cli';h={'Authorization':'Bearer '+'x'*40};worker={'worker_id':'usage-check','provider':'codex'}
    c.post('/api/cli/heartbeat',headers=h,json=worker)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(launch,c)
        job=None
        for _ in range(100):
            job=c.post('/api/cli/claim',headers=h,json=worker).json()['job']
            if job:break
            time.sleep(.02)
        assert job is not None
        result={'text':'{}','model':'fixture-cli-invalid','provider':'codex','input_tokens':13,'output_tokens':7,'usage':{'test':True},'duration_ms':10,'cost_usd':None}
        assert c.post('/api/cli/jobs/'+job['id']+'/complete',headers=h,json={'claim_token':job['claim_token'],'status':'completed','result':result}).status_code==200
        run=future.result(timeout=10).json()
    assert run['status']=='error' and run['input_tokens']==13 and run['output_tokens']==7
    assert run['model_calls'][0]['status']=='error' and run['cost_usd'] is None

def test_approved_task_is_not_marked_as_stale(system):
    c,_,_,_=system;run=launch(c).json();approved=approve(c,run).json()
    assert approved['status']=='approved' and not approved['task_state_stale']

@pytest.mark.parametrize('declared',[True,False])
def test_new_agent_workspace_capability_needs_no_core_code_change(system,declared):
    import yaml
    c,app,_,root=system
    target=root/'agents/team-snapshot';shutil.copytree(root/'agents/_template',target)
    path=target/'agent.yaml';manifest=yaml.safe_load(path.read_text());manifest['name']='team-snapshot';manifest['workspace']=declared;path.write_text(yaml.safe_dump(manifest,allow_unicode=True))
    app.state.settings.agent_urls['team-snapshot']='http://daily-brief'
    assert c.post('/api/sync',headers={'X-Person':'anna'}).status_code==200
    result=launch(c,agent='team-snapshot',input={'project_id':'all'}).json()
    assert result['status']==('needs_review' if declared else 'error'),result

def test_workspace_capability_respects_declared_project_section(system):
    import yaml
    c,app,state,root=system;target=root/'agents/rules-snapshot';shutil.copytree(root/'agents/_template',target)
    path=target/'agent.yaml';manifest=yaml.safe_load(path.read_text());manifest.update(name='rules-snapshot',workspace=True,context=['rules']);path.write_text(yaml.safe_dump(manifest,allow_unicode=True))
    app.state.settings.agent_urls['rules-snapshot']='http://daily-brief'
    assert c.post('/api/sync',headers={'X-Person':'anna'}).status_code==200
    run=launch(c,agent='rules-snapshot',input={'project_id':'all'}).json()
    assert run['status']=='error'  # Template requests projects, which are forbidden.
    assert state['workspaces'][-1]['tasks']==[] and state['workspaces'][-1]['projects']==[] and state['workspaces'][-1]['inbox']==[]

def test_manual_retry_with_feedback_keeps_history_and_same_event(system,monkeypatch):
    c,_,_,_=system;original=launch(c,key='original-request').json();received=[];fixture=backend.fixture_response
    def capture(body):
        if body.purpose=='classify_message':received.append(body.data.get('review_feedback'))
        return fixture(body)
    monkeypatch.setattr(backend,'fixture_response',capture)
    body={'agent':'task-intake','input':{'event_id':'E001'},'request_id':'retry-request','refresh':True}
    assert c.post('/api/runs',json=body).status_code==409
    reason='Проверь, что речь только о получении текстов, а не о запуске сайта.'
    retried=c.post('/api/runs',json={**body,'retry_reason':reason})
    assert retried.status_code==200,retried.text
    current=retried.json();assert current['id']!=original['id'] and current['review_feedback']==reason and received==[reason]
    assert c.get('/api/runs/'+original['id']).json()['versions']==original['versions']
    repeated=c.post('/api/runs',json={**body,'request_id':'original-request','retry_reason':reason}).json()
    assert repeated['id']==original['id'] and len(received)==1
    assert approve(c,original).status_code==409
    assert approve(c,current).status_code==200
    forbidden=c.post('/api/runs',json={**body,'request_id':'after-approval','retry_reason':reason})
    assert forbidden.status_code==409 and len(c.get('/api/workspace').json()['tasks'])==3

def test_manual_retry_requires_substantive_feedback(system):
    c,_,_,_=system;launch(c)
    base={'agent':'task-intake','input':{'event_id':'E001'},'request_id':'tiny-feedback','refresh':True,'retry_reason':'да'}
    assert c.post('/api/runs',json=base).status_code==422
    assert c.post('/api/runs',json={**base,'refresh':False,'retry_reason':'Неверно выбрана задача'}).status_code==422

def test_workspace_trace_uses_issued_snapshot_not_newer_database_version(system):
    import yaml
    c,app,state,root=system;target=root/'agents/custom-summary';shutil.copytree(root/'agents/_template',target)
    path=target/'agent.yaml';manifest=yaml.safe_load(path.read_text());manifest.update(name='custom-summary',workspace=True);path.write_text(yaml.safe_dump(manifest,allow_unicode=True))
    app.state.settings.agent_urls['custom-summary']='http://daily-brief'
    c.post('/api/sync',headers={'X-Person':'anna'})
    old=c.get('/api/knowledge?section=projects&q=Орбита').json()['records'][0]
    state['behavior']='change_source_before_workspace'
    run=launch(c,agent='custom-summary',input={'project_id':'P01'}).json()
    assert run['status']=='needs_review',run
    snapshot_trace=next(e for e in run['context_events'] if e['query']=='Снимок рабочего состояния')
    assert snapshot_trace['records']==[{'id':'P01','title':old['title'],'version':old['version']}]
    current=c.get('/api/knowledge?section=projects&q=Орбита').json()['records'][0]
    assert current['version']!=old['version']
    assert run['source_warnings'][0]['id']=='P01'
    assert approve(c,run).status_code==409
