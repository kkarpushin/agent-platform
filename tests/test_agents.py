"""Unit rules for model suggestions; no real model is called here."""
import importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('intake',ROOT/'agents/task-intake/agent.py');intake=importlib.util.module_from_spec(spec);spec.loader.exec_module(intake)

def proposal():return {'markdown':'Предложение','action':'create','event_id':'E001','project_id':'P01','task_id':None,'base_version':None,'title':'Получить тексты','owner':'mark','status':'blocked','due_date':None,'blocked_by':'Нет текстов','question':'','source_refs':['P01']}

@pytest.mark.parametrize('change',[{'owner':'unknown'},{'source_refs':['PRIVATE']},{'event_id':'E002'},{'project_id':'P02'},{'due_date':'2026-99-99'},{'action':'update','task_id':'missing','base_version':1},{'action':'create','task_id':'T1'},{'title':''},{'action':'question','question':''}])
def test_invalid_suggestion_rejected(change):
    with pytest.raises(ValueError):intake.parse_proposal(json.dumps({**proposal(),**change}),{'event_id':'E001','project_id':'P01'},[],[{'id':'mark'}],['P01'])

def test_existing_task_version_required():
    p={**proposal(),'action':'update','task_id':'T1','base_version':2};t={'id':'T1','project_id':'P01','version':2}
    assert intake.parse_proposal(json.dumps(p),{'event_id':'E001','project_id':'P01'},[t],[{'id':'mark'}],['P01'])==p

def test_sdk_rejects_arbitrary_gateway():
    from sdk import Context
    with pytest.raises(ValueError):Context('http://169.254.169.254','token')
