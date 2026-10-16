import copy
import json
from pathlib import Path

import pytest

from cba_calendar.sources import SourceError, parse_official, parse_backup, crosscheck, validate_schedule

FIXTURES = Path(__file__).parent / 'fixtures'

@pytest.fixture
def payload():
    return json.loads((FIXTURES / 'official.json').read_text())

def test_official_real_schedule_and_acceptance(payload):
    games = parse_official(payload)
    validate_schedule(games)
    assert len(games) == 46
    assert {g['round'] for g in games} == set(range(1, 47))
    assert sum(g['home_id'] == 29125 for g in games) == 23
    expected = {
        100110655: ('2026-10-16T19:35:00+08:00', 29125),
        100111019: ('2026-12-04T20:00:00+08:00', 29117),
        100110862: ('2027-01-11T20:00:00+08:00', 29117),
        100110805: ('2027-03-26T20:00:00+08:00', 29124),
        100111010: ('2027-04-07T19:35:00+08:00', 29125),
    }
    by_id = {g['id']: g for g in games}
    for match_id, (start, home) in expected.items():
        assert by_id[match_id]['start'] == start
        assert by_id[match_id]['home_id'] == home
    assert by_id[100111010]['away_id'] == 29128
    assert by_id[100110655]['location'] == '上海体育馆'
    assert sum(bool(g['location']) for g in games) == 1

def test_backup_all_hidden_months_is_incomplete(payload):
    backup = parse_backup((FIXTURES / '90vs.html').read_text())
    assert len(backup) == 45  # No preseason and no missing final manufactured.
    report = crosscheck(parse_official(payload), backup)
    assert report['matched'] == 45
    assert report['missing_official_ids'] == [100111010]
    assert report['conflicts'] == []

def test_backup_season_mismatch_rejected():
    html = (FIXTURES / '90vs.html').read_text().replace('2026-2027', '2025-2026')
    with pytest.raises(SourceError, match='season'):
        parse_backup(html)

@pytest.mark.parametrize('mode', ['empty', 'duplicate', 'missing', 'bad_round', 'bad_time', 'status', 'season', 'date', 'score'])
def test_rejects_bad_official(payload, mode):
    rows = payload['data']
    target = next(r for r in rows if r['ScheduleID'] == 100110655)
    if mode == 'empty': payload['data'] = []
    elif mode == 'duplicate': rows.append(copy.deepcopy(target))
    elif mode == 'missing': rows.remove(target)
    elif mode == 'bad_round': target['Round'] = 47
    elif mode == 'bad_time': target['time'] = '25:00'
    elif mode == 'status': target['Status'] = 999; target.pop('StatusCNName', None)
    elif mode == 'season': target['Season'] = 2025
    elif mode == 'date': target['dates'] = '2025-10-16'
    elif mode == 'score': target['Status'] = 4; target['HomeTeamScore'] = None
    with pytest.raises(SourceError):
        validate_schedule(parse_official(payload))

def test_playoff_only_type_two_and_tba(payload):
    game = copy.deepcopy(next(r for r in payload['data'] if r['ScheduleID'] == 100110655))
    game.update(ScheduleID=999, ScheduleTypeID=2, dates='2027-04-20', time='00:00', TimeTBAState=1)
    payload['data'].append(game)
    parsed = parse_official(payload)
    validate_schedule(parsed)
    assert parsed[-1]['phase'] == 'playoffs'
    assert parsed[-1]['status'] == 'tentative'
    assert parsed[-1]['start'] == '2027-04-20'

def test_crosscheck_time_conflict_does_not_replace_official(payload):
    games = parse_official(payload)
    backup = parse_backup((FIXTURES / '90vs.html').read_text().replace('26-12-04 20:00', '26-12-04 19:35'))
    assert crosscheck(games, backup)['conflicts']
    assert next(g for g in games if g['id'] == 100111019)['start'].endswith('20:00:00+08:00')
