"""Чистые тесты бизнес-правил: деньги, неизвестные услуги, отсутствие клиента."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'agents' / name / 'agent.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


proposal = module('commercial-proposal')
brief = module('client-brief')


def test_money_is_decimal_and_duration_is_code():
    assert proposal.calculate([{'price_usd': 0.1, 'days': 2}, {'price_usd': 0.2, 'days': 3}]) == (0.3, 5)


@pytest.mark.parametrize('text', ['{}', '{"service_ids":[]}', '{"service_ids":["unknown"]}', '{"service_ids":["S01","S01"]}', '{"service_ids":"S01"}', 'не JSON'])
def test_model_cannot_invent_or_repeat_services(text):
    with pytest.raises(ValueError):
        proposal.parse_selection(text, {'S01': {'price_usd': 1800, 'days': 5}})


def test_structured_selection_uses_catalog_price():
    selected = proposal.parse_selection('{"service_ids":["S01"],"price_usd":0}', {'S01': {'price_usd': 1800, 'days': 5}})
    assert proposal.calculate(selected) == (1800, 5)


def test_unknown_client_stops_before_model():
    class Empty:
        def search(self, section, query):
            return []
        def llm(self, *args):
            pytest.fail('Unknown client must not consume model calls')
    with pytest.raises(ValueError, match='Клиент не найден'):
        proposal.app.agent_function({'client': 'нет'}, Empty())


def test_sdk_rejects_arbitrary_gateway():
    from sdk import Context
    with pytest.raises(ValueError, match='Адрес платформы'):
        Context('http://169.254.169.254', 'token')
