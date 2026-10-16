import copy
import json
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import pytest
from icalendar import Calendar

from cba_calendar.sources import SourceError, parse_official
from cba_calendar.calendar import merge, render_ics, validate_state

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)

@pytest.fixture
def games():
    return parse_official(json.loads((Path(__file__).parent / 'fixtures/official.json').read_text()))

def test_independent_ics_parser_roundtrip(games):
    state, log = merge(None, games, NOW)
    data = render_ics(state)
    assert data.endswith(b'\r\n') and b'\n' not in data.replace(b'\r\n', b'')
    assert all(len(line) <= 75 for line in data.split(b'\r\n'))
    cal = Calendar.from_ical(data)
    assert str(cal['X-WR-CALNAME']) == '上海大鲨鱼 CBA 赛程'
    assert str(cal['X-WR-TIMEZONE']) == 'Asia/Shanghai'
    events = cal.walk('VEVENT')
    assert len(events) == 46 and len({str(e['UID']) for e in events}) == 46
    first = next(e for e in events if '100110655@' in str(e['UID']))
    assert first.decoded('DTSTART') == datetime(2026, 10, 16, 11, 35, tzinfo=timezone.utc)
    assert first.decoded('DTEND') - first.decoded('DTSTART') == timedelta(hours=2)
    assert str(first['LOCATION']) == '上海体育馆'
    assert str(first['SUMMARY']) == '🏀 上海久事 vs 深圳马可波罗（主场）'
    assert all(not e.errors for e in events)
    assert len(log['added']) == 46

def test_identical_input_is_byte_stable_and_persistent(games):
    old, _ = merge(None, games, NOW)
    new, log = merge(old, games, LATER)
    assert render_ics(old) == render_ics(new)
    assert not log['changed']
    assert all(e['sequence'] == 0 for e in new['events'].values())

def test_reschedule_score_cancellation_and_recovery(games):
    old, _ = merge(None, games, NOW)
    uid = '100110655'
    games[0]['start'] = '2026-10-17T20:00:00+08:00'
    moved, log = merge(old, games, LATER)
    assert moved['events'][uid]['sequence'] == 1
    assert log['time_changes'][0]['id'] == int(uid)
    a = Calendar.from_ical(render_ics(old)).walk('VEVENT')[0]
    b = Calendar.from_ical(render_ics(moved)).walk('VEVENT')[0]
    assert str(a['UID']) == str(b['UID'])
    games[0].update(status='completed', score=[111, 99])
    scored, _ = merge(moved, games, LATER)
    assert '111–99' in render_ics(scored).decode()
    games[0]['status'] = 'cancelled'
    cancelled, _ = merge(scored, games, LATER)
    assert b'STATUS:CANCELLED' in render_ics(cancelled)
    games[0]['status'] = 'scheduled'; games[0]['score'] = None
    recovered, _ = merge(cancelled, games, LATER)
    assert recovered['events'][uid]['sequence'] == 4
    assert b'STATUS:CANCELLED' not in render_ics(recovered)

def test_postponed_no_date_keeps_time_location_and_uid(games):
    old, _ = merge(None, games, NOW)
    games[0].update(start=None, status='tentative', location='')
    state, log = merge(old, games, LATER)
    assert state['events']['100110655']['start'] == old['events']['100110655']['start']
    assert state['events']['100110655']['location'] == '上海体育馆'
    assert state['events']['100110655']['sequence'] == 1
    assert b'STATUS:TENTATIVE' in render_ics(state)


def test_playoff_appends_and_omission_keeps_event(games):
    old, _ = merge(None, games, NOW)
    extra = dict(games[0], id=999, phase='playoffs', start='2027-04-20', status='tentative')
    added, _ = merge(old, games + [extra], LATER)
    missing, log = merge(added, games, LATER)
    assert len(missing['events']) == 47
    assert log['retained_missing'] == [999]
    event = next(e for e in Calendar.from_ical(render_ics(missing)).walk('VEVENT') if '999@' in str(e['UID']))
    assert event.decoded('DTSTART') == date(2027, 4, 20)
    assert event.decoded('DTEND') == date(2027, 4, 21)

@pytest.mark.parametrize('change', ['remove', 'rekey', 'identity', 'new_no_date', 'regress'])
def test_merge_refuses_unsafe_changes(games, change):
    old, _ = merge(None, games, NOW)
    if change == 'remove': games.pop()
    elif change == 'rekey': games[0]['id'] = 1234
    elif change == 'identity': games[0]['away_id'] = 1234
    elif change == 'new_no_date':
        games.append(dict(games[0], id=1234, phase='playoffs', start=None, status='tentative'))
    elif change == 'regress':
        old['events']['100110655'].update(status='completed', score=[111, 99])
    with pytest.raises(SourceError): merge(old, games, LATER)

@pytest.mark.parametrize('corruption', ['version', 'season', 'sequence', 'time', 'key', 'empty', 'stamp'])
def test_state_validation(games, corruption):
    state, _ = merge(None, games, NOW)
    if corruption == 'version': state['schema'] = 999
    elif corruption == 'season': state['season'] = 2025
    elif corruption == 'sequence': state['events']['100110655']['sequence'] = -1
    elif corruption == 'time': state['events']['100110655']['start'] = 'garbage'
    elif corruption == 'key': state['events']['100110655']['id'] = 999
    elif corruption == 'empty': state['events'] = {}
    elif corruption == 'stamp': state['events']['100110655']['modified'] = 'yesterday'
    with pytest.raises(SourceError): validate_state(state)

def test_ics_escaping_no_property_injection(games):
    games[0]['location'] = '体育馆,上海;A\\B\nEND:VEVENT\nBEGIN:VEVENT'
    games[0]['home'] = '上海久事' * 40
    state, _ = merge(None, games, NOW)
    data = render_ics(state)
    parsed = Calendar.from_ical(data).walk('VEVENT')
    assert len(parsed) == 46
    assert str(parsed[0]['LOCATION']) == games[0]['location']
    assert all(len(line) <= 75 for line in data.split(b'\r\n'))


def test_playoff_rekey_is_not_silently_duplicated(games):
    extra = dict(games[0], id=999, phase='playoffs', start='2027-04-20T19:35:00+08:00')
    old, _ = merge(None, games + [extra], NOW)
    rekeyed = dict(extra, id=1000, start='2027-04-21T19:35:00+08:00')
    with pytest.raises(SourceError, match='playoff identity'):
        merge(old, games + [rekeyed], LATER)


def test_render_revision_bump_increases_existing_sequences(games, monkeypatch):
    old, _ = merge(None, games, NOW)
    monkeypatch.setattr('cba_calendar.calendar.RENDER_REVISION', old['render_revision'] + 1)
    new, log = merge(old, games, LATER)
    assert all(e['sequence'] == 1 for e in new['events'].values())
    assert len(log['changed']) == 46
    assert not log['time_changes']


def test_postponed_new_date_without_time_uses_official_date(games):
    old, _ = merge(None, games, NOW)
    games[0].update(start='2026-10-18', status='tentative')
    state, log = merge(old, games, LATER)
    assert state['events']['100110655']['start'] == '2026-10-18'
    assert state['events']['100110655']['sequence'] == 1
    event = Calendar.from_ical(render_ics(state)).walk('VEVENT')[0]
    assert event.decoded('DTSTART') == date(2026, 10, 18)
