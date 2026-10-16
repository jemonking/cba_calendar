import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from cba_calendar.calendar import merge, render_ics
from cba_calendar.sources import SourceError, parse_official
from cba_calendar.update import build, fetch, load_previous, main

FIXTURES = Path(__file__).parent / 'fixtures'
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)

@pytest.fixture
def payload():
    return json.loads((FIXTURES / 'official.json').read_text())


def test_representative_build_and_restore(payload, tmp_path):
    output = tmp_path / 'site'
    report = build(output, payload, (FIXTURES / '90vs.html').read_text(), None, NOW)
    state = json.loads((output / 'state.json').read_text())
    assert report['regular_count'] == 46
    assert report['crosscheck']['matched'] == 45
    assert (output / 'shanghai-sharks.ics').read_bytes() == render_ics(state)
    assert state['ics_sha256'] == report['ics_sha256']
    assert b'webcal:' in (output / 'index.html').read_bytes()
    restore = load_previous('https://example.com/cba_calendar', False, lambda url: (output / ('state.json' if url.endswith('state.json') else 'shanghai-sharks.ics')).read_bytes())
    assert restore == state


def test_landing_page_offers_subscription_not_ics_import(payload, tmp_path):
    output = tmp_path / 'site'
    build(output, payload, None, None, NOW)
    page = (output / 'index.html').read_text(encoding='utf-8')
    assert 'href="webcal://jemonking.github.io/cba_calendar/shanghai-sharks.ics"' in page
    assert '添加订阅日历' in page
    assert '取消订阅' in page
    assert '不要下载 ICS 后导入' in page
    assert '查看 ICS 文件' not in page
    assert '<table' not in page
    assert 'href="shanghai-sharks.ics"' not in page


def test_build_failure_preserves_all_previous_files(payload, tmp_path):
    output = tmp_path / 'site'
    build(output, payload, None, None, NOW)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    payload['data'] = []
    with pytest.raises(SourceError): build(output, payload, None, None, NOW)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_missing_or_corrupt_previous_is_not_silently_bootstrapped(payload, tmp_path):
    def missing(url): raise HTTPError(url, 404, 'Not Found', {}, None)
    with pytest.raises(SourceError, match='bootstrap'):
        load_previous('https://example.com/repo/', False, missing)
    assert load_previous('https://example.com/repo/', True, missing) is None
    build(tmp_path / 'site', payload, None, None, NOW)
    good = (tmp_path / 'site/state.json').read_bytes()
    with pytest.raises(SourceError, match='exists'):
        load_previous('https://example.com/repo/', True, lambda _: good)
    with pytest.raises(SourceError):
        load_previous('https://example.com/repo/', True, lambda _: b'not json')
    for code in (403, 429, 500):
        def bad(url): raise HTTPError(url, code, 'error', {}, None)
        with pytest.raises(SourceError): load_previous('https://example.com/', True, bad)


def test_previous_checksum_protects_revision_history(payload, tmp_path):
    build(tmp_path / 'site', payload, None, None, NOW)
    state = json.loads((tmp_path / 'site/state.json').read_text())
    state['events']['100110655']['sequence'] = 9
    with pytest.raises(SourceError, match='checksum'):
        load_previous('https://example.com/', False, lambda _: json.dumps(state).encode())


@pytest.mark.parametrize('code, attempts', [(403, 1), (429, 1), (503, 2)])
def test_http_stop_and_bounded_retry(monkeypatch, code, attempts):
    calls = []
    def opener(*args, **kwargs):
        calls.append(1)
        raise HTTPError('https://example.com', code, 'fail', {}, None)
    monkeypatch.setattr('cba_calendar.update.urlopen', opener)
    monkeypatch.setattr('cba_calendar.update.time.sleep', lambda _: None)
    with pytest.raises(HTTPError): fetch('https://example.com')
    assert len(calls) == attempts


def test_cli_network_failure_logs_and_preserves_output(payload, tmp_path, monkeypatch):
    output = tmp_path / 'site'
    build(output, payload, None, None, NOW)
    before = (output / 'shanghai-sharks.ics').read_bytes()
    def failed(*args, **kwargs): raise URLError('temporary offline')
    monkeypatch.setattr('cba_calendar.update.fetch', failed)
    log = tmp_path / 'log.json'
    assert main(['--base-url', 'https://example.com/', '--output', str(output), '--log', str(log)]) == 1
    assert json.loads(log.read_text())['status'] == 'failed'
    assert (output / 'shanghai-sharks.ics').read_bytes() == before


def test_cli_offline_end_to_end_and_backup_failure_is_warning(tmp_path):
    output = tmp_path / 'site'
    log = tmp_path / 'log.json'
    assert main(['--preview', '--official-file', str(FIXTURES / 'official.json'),
                 '--backup-file', str(FIXTURES / '90vs.html'), '--output', str(output), '--log', str(log)]) == 0
    assert (output / 'shanghai-sharks.ics').exists()
    assert json.loads(log.read_text())['event_count'] == 46


def test_backup_cannot_publish_without_official(tmp_path):
    with pytest.raises(SourceError):
        build(tmp_path / 'site', {'code': 500}, (FIXTURES / '90vs.html').read_text(), None, NOW)
    assert not (tmp_path / 'site').exists()


def test_bootstrap_refuses_existing_calendar_without_state():
    def remote(url):
        if url.endswith('state.json'):
            raise HTTPError(url, 404, 'Not Found', {}, None)
        return b'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n'
    with pytest.raises(SourceError, match='calendar exists'):
        load_previous('https://example.com/', True, remote)


def test_official_failure_after_restore_preserves_previous(payload, tmp_path, monkeypatch):
    output = tmp_path / 'site'
    build(output, payload, None, None, NOW)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    state = (output / 'state.json').read_bytes()
    def remote(url):
        if url.endswith('state.json'):
            return state
        if url.endswith('shanghai-sharks.ics'):
            return before['shanghai-sharks.ics']
        raise HTTPError(url, 503, 'Service unavailable', {}, None)
    monkeypatch.setattr('cba_calendar.update.fetch', remote)
    log = tmp_path / 'error.json'
    assert main(['--output', str(output), '--log', str(log)]) == 1
    assert json.loads(log.read_text())['status'] == 'failed'
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_renderer_change_does_not_invalidate_published_state(payload, tmp_path, monkeypatch):
    output = tmp_path / 'site'
    build(output, payload, None, None, NOW)
    original = render_ics
    monkeypatch.setattr('cba_calendar.update.render_ics', lambda state: original(state).replace(b'PRODID:', b'PRODID:NEW'))
    def remote(url):
        return (output / ('state.json' if url.endswith('state.json') else 'shanghai-sharks.ics')).read_bytes()
    restored = load_previous('https://example.com/', False, remote)
    assert len(restored['events']) == 46
