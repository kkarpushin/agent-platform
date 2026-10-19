"""Проверки настоящего Docker-цикла. Никакие существующие записи не удаляются."""
import json
import os
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

BASE = os.getenv('BASE_URL')
pytestmark = pytest.mark.skipif(not BASE, reason='Для HTTP-проверки выполните make test')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='session', autouse=True)
def require_demo_before_any_http_run():
    if BASE:
        mode = httpx.get(BASE + '/api/health', timeout=10).json().get('llm_mode')
        if mode != 'demo':
            pytest.exit('HTTP-проверки остановлены: требуется отдельная платформа в режиме demo. Настоящая модель не вызывалась.', returncode=2)


def api(method, path, who='mark', **kwargs):
    return httpx.request(method, BASE + path, headers={'X-Person': who}, timeout=90, **kwargs)


def launch(agent='commercial-proposal', data=None, request_id=None, who='mark'):
    data = data or {'client': 'Орбита', 'task': 'Нужен аудит процесса обработки заявок', 'budget': 2400, 'deadline': 'В течение двух недель', 'language': 'ru'}
    response = api('POST', '/api/runs', who, json={'agent': agent, 'input': data, 'request_id': request_id or 'test-' + uuid4().hex})
    assert response.status_code == 200, response.text
    return response.json()


def test_nine_layers_and_real_health():
    assert api('GET', '/api/health').json()['database'] == 'ok'
    body = api('GET', '/api/bootstrap').json()
    assert len(body['layers']) == 9
    assert body['person']['id'] == 'mark'
    assert body['llm_mode'] == 'demo'
    assert not any(a['name'].startswith('_') for a in body['agents'])


def test_sales_gets_price_not_cost_and_trace_has_hidden_count():
    run = launch()
    assert run['status'] == 'needs_review', run
    assert run['output']['total_price'] == 1800
    assert run['output']['timeline'] == 5
    assert 'Цена помещается в бюджет' in run['output']['markdown']
    encoded = json.dumps(run, ensure_ascii=False)
    assert 'PRIVATE-COST' not in encoded
    assert all('COST-' not in r['id'] for event in run['context_events'] for r in event['records'])
    assert any(e['section'] == 'costs' and e['hidden_count'] == 6 and not e['records'] for e in run['context_events'])
    assert len(run['model_calls']) == 2
    assert run['input_tokens'] == run['output_tokens'] == 0
    assert float(run['cost_usd']) == 0
    assert all(e['mode'] == 'demo' for e in run['model_calls'])
    assert all(e['skill_refs'] for e in run['model_calls'])


def test_delivery_denied_before_any_run_record():
    before = api('GET', '/api/runs', 'olga').json()['runs']
    response = api('POST', '/api/runs', 'olga', json={'agent':'commercial-proposal','input':{'client':'Орбита'},'request_id':'test-'+uuid4().hex})
    assert response.status_code == 403
    assert api('GET', '/api/runs', 'olga').json()['runs'] == before


def test_unknown_employee_and_invalid_input():
    assert api('GET', '/api/bootstrap', 'nobody').status_code == 401
    response = api('POST', '/api/runs', json={'agent':'commercial-proposal','input':{'client':'Орбита'},'request_id':'test-'+uuid4().hex})
    assert response.status_code == 422
    assert 'схем' in response.text.lower()


def test_record_visibility_and_search():
    sales = api('GET', '/api/knowledge', params={'section':'costs'}).json()
    assert sales['records'] == [] and sales['hidden_count'] == 6
    finance = api('GET', '/api/knowledge', 'irina', params={'section':'costs'}).json()
    assert len(finance['records']) == 6
    found = api('GET', '/api/knowledge', params={'section':'services','q':'аудит'}).json()
    assert [r['id'] for r in found['records']] == ['S01']
    assert api('GET', '/api/sync').status_code in (404, 405)
    assert api('POST', '/api/sync').status_code == 403


def test_repeated_request_is_same_run_and_changed_input_conflicts():
    key = 'test-repeat-' + uuid4().hex
    first = launch(request_id=key)
    again = launch(request_id=key)
    assert first['id'] == again['id']
    assert len(again['versions']) == 1 and len(again['model_calls']) == 2
    response = api('POST', '/api/runs', json={'agent':'client-brief','input':{'client':'Форма'},'request_id':key})
    assert response.status_code == 409


def test_concurrent_duplicate_does_not_execute_twice():
    key = 'test-concurrent-' + uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: launch(request_id=key), range(2)))
    assert rows[0]['id'] == rows[1]['id']
    final = api('GET', '/api/runs/' + rows[0]['id']).json()
    assert len(final['versions']) == 1 and len(final['model_calls']) == 2


def test_exact_version_approval_and_immutable_original():
    run = launch(); path = '/api/runs/' + run['id']
    original = run['output']['markdown']
    assert api('GET', path, 'lev').status_code == 404
    assert api('POST', path+'/approve', json={'version':1}).status_code == 403
    approved = api('POST', path+'/approve', 'anna', json={'version':1,'note':'Проверены источники и расчёт'}).json()
    assert approved['status'] == 'approved'
    revised = api('POST', path+'/revisions', json={'base_version':1,'markdown':original+'\n\nДополнительный вопрос: кто подтвердит материалы?'}).json()
    assert revised['status'] == 'needs_review' and revised['current_version'] == 2
    assert revised['versions'][0]['output']['markdown'] == original
    assert len(revised['decisions']) == 1 and revised['decisions'][0]['version'] == 1
    assert api('POST', path+'/approve', 'anna', json={'version':1}).status_code == 409
    assert api('POST', path+'/revisions', json={'base_version':1,'markdown':'Старая вкладка'}).status_code == 409
    accepted = api('POST', path+'/approve', 'anna', json={'version':2,'note':'Новая версия проверена'}).json()
    assert accepted['status'] == 'approved' and len(accepted['decisions']) == 2
    saved = api('POST', path+'/learnings', 'anna', json={'text':'После изменения текста нужно повторно согласовать точную версию.'})
    assert saved.status_code == 200 and saved.json()['version'] == 2
    assert api('GET', '/api/memory').json()['decisions']


CASES = [(p.parent.parent.name, i, case) for p in sorted((ROOT/'agents').glob('*/tests/cases.json')) if not p.parent.parent.name.startswith('_') for i,case in enumerate(json.loads(p.read_text()))]


@pytest.mark.parametrize('agent,index,case', CASES, ids=[f'{a}-{i}' for a,i,c in CASES])
def test_agent_examples(agent, index, case):
    row = launch(agent, case['input'])
    if case.get('expect_error'):
        assert row['status'] == 'error' and row['error']
        assert row['versions'] == []
        return
    assert row['status'] == 'needs_review', row
    result, expected = row['output'], case['expect']
    for key in ('total_price','timeline'):
        if key in expected:
            assert result[key] == expected[key]
    if 'service_ids' in expected:
        assert [s['service_id'] for s in result['services']] == expected['service_ids']
    for text in expected.get('contains',[]):
        assert text in result['markdown']
    for source in expected.get('sources',[]):
        assert source in result['sources']
