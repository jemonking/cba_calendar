"""Monotonic event revisions and RFC 5545 serialization (UTC, UTF-8, CRLF)."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from .sources import OFFICIAL_URL, SEASON, TEAM_ID, SourceError, TZ, validate_schedule

FIELDS = ('id', 'season', 'phase', 'round', 'home_id', 'away_id', 'home', 'away',
          'start', 'status', 'score', 'location')
# Bump for any change to emitted event text/properties; merge revises existing events.
RENDER_REVISION = 1

STATUSES = {'scheduled', 'live', 'completed', 'tentative', 'cancelled'}


def _instant(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('timezone missing')
    return dt


def validate_state(state):
    try:
        if state['schema'] != 1 or state['season'] != SEASON:
            raise ValueError('unsupported state schema/season')
        _instant(state['checked_at'])
        if type(state['render_revision']) is not int or not 1 <= state['render_revision'] <= RENDER_REVISION:
            raise ValueError('unsupported render revision; deploy newer code')
        events = state['events']
        if not isinstance(events, dict):
            raise ValueError('events must be an object')
        validate_schedule(list(events.values()))
        for key, event in events.items():
            if str(event['id']) != key or event['season'] != SEASON:
                raise ValueError('event key/season mismatch')
            if type(event['sequence']) is not int or event['sequence'] < 0:
                raise ValueError('invalid SEQUENCE')
            _instant(event['modified'])
            if event['status'] not in STATUSES or event['phase'] not in ('regular', 'playoffs'):
                raise ValueError('unknown event status/phase')
            if event['home_id'] == event['away_id'] or TEAM_ID not in (event['home_id'], event['away_id']):
                raise ValueError('invalid teams')
            for field in ('home', 'away', 'location'):
                if not isinstance(event[field], str) or (field != 'location' and not event[field].strip()):
                    raise ValueError('invalid event text')
            value = event['start']
            if len(value) == 10:
                day = date.fromisoformat(value)
            else:
                dt = _instant(value)
                if dt.utcoffset() != timedelta(hours=8):
                    raise ValueError('event start must be Beijing time')
                day = dt.date()
            if not date(2026, 8, 1) <= day < date(2027, 8, 1):
                raise ValueError('event outside season')
            score = event['score']
            if score is not None and (not isinstance(score, list) or len(score) != 2 or
                                      any(type(s) is not int or s < 0 for s in score)):
                raise ValueError('invalid score')
            if event['status'] == 'completed' and score is None:
                raise ValueError('completed event missing score')
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise SourceError(f'invalid previous state: {exc}') from exc


def merge(previous, games, now):
    validate_schedule(games)
    if now.tzinfo is None:
        raise SourceError('update timestamp needs timezone')
    if previous is not None:
        validate_state(previous)
    old = previous['events'] if previous else {}
    events = deepcopy(old)
    stamp = now.astimezone(timezone.utc).isoformat()
    log = {'added': [], 'changed': [], 'time_changes': [], 'retained_missing': []}
    regular_slots = {e['round']: e['id'] for e in old.values() if e['phase'] == 'regular'}
    render_changed = previous is not None and previous['render_revision'] != RENDER_REVISION
    incoming_ids = {str(g['id']) for g in games}
    missing_playoffs = [e for key, e in old.items() if key not in incoming_ids and e['phase'] == 'playoffs']
    seen = set()
    for game in games:
        item = {k: deepcopy(game[k]) for k in FIELDS}
        key = str(item['id'])
        seen.add(key)
        if item['phase'] == 'regular' and item['round'] in regular_slots and regular_slots[item['round']] != item['id']:
            raise SourceError('official match ID changed for existing round; manual identity review required')
        before = old.get(key)
        if not before and item['phase'] == 'playoffs':
            for missing in missing_playoffs:
                if (missing['round'] == item['round'] and
                        {missing['home_id'], missing['away_id']} == {item['home_id'], item['away_id']}):
                    raise SourceError('ambiguous playoff identity: missing old match and new ID in same series; manual review required')
        if before:
            if any(before[k] != item[k] for k in ('season', 'phase', 'round', 'home_id', 'away_id')):
                raise SourceError(f'identity changed for match {key}')
            if before['status'] == 'completed' and item['status'] in ('scheduled', 'live'):
                raise SourceError(f'completed match {key} regressed; refusing stale data')
            if item['start'] is None or (len(item['start']) == 10 and item['start'] == before['start'][:10] and item['status'] in ('tentative', 'cancelled')):
                # No invented midnight. Keep the old clock only for the same/unknown day;
                # a newly announced day with unknown clock must move to that DATE.
                item['start'] = before['start']
            if not item['location']:
                item['location'] = before['location']
            if item['score'] is None and item['status'] in ('tentative', 'cancelled'):
                item['score'] = before['score']
            changed = [k for k in FIELDS if before[k] != item[k]]
            if render_changed:
                changed.append('render_revision')
            if not changed:
                continue
            item.update(sequence=before['sequence'] + 1, modified=stamp)
            log['changed'].append({'id': item['id'], 'fields': changed})
            if 'start' in changed:
                log['time_changes'].append({'id': item['id'], 'before': before['start'], 'after': item['start']})
        else:
            if item['start'] is None:
                raise SourceError(f'new match {key} has no date; cannot create event')
            item.update(sequence=0, modified=stamp)
            log['added'].append(item['id'])
        events[key] = item
    log['retained_missing'] = sorted(int(key) for key in old.keys() - seen)
    # Even retained missing playoff events must get a revision for new rendered content.
    if render_changed:
        for key in old.keys() - seen:
            events[key].update(sequence=old[key]['sequence'] + 1, modified=stamp)
            log['changed'].append({'id': events[key]['id'], 'fields': ['render_revision']})
    state = {'schema': 1, 'season': SEASON, 'render_revision': RENDER_REVISION,
             'checked_at': stamp, 'events': events}
    validate_state(state)
    return state, log


def _text(value):
    return str(value).replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _fold(line):
    # Continuation's leading space counts toward its 75-octet limit.
    lines, current = [], b''
    for character in line:
        octets = character.encode('utf-8')
        if len(current) + len(octets) > 75:
            lines.append(current)
            current = b' '
        current += octets
    lines.append(current)
    return b'\r\n'.join(lines)


def render_ics(state):
    validate_state(state)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CBA Calendar//Shanghai Sharks//ZH',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:上海大鲨鱼 CBA 赛程',
             'X-WR-TIMEZONE:Asia/Shanghai', 'REFRESH-INTERVAL;VALUE=DURATION:PT6H',
             'X-PUBLISHED-TTL:PT6H']
    # Stable source order (round rather than changing start) also aids diff auditing.
    for event in sorted(state['events'].values(), key=lambda e: (e['phase'] != 'regular', e['round'], e['id'])):
        home = event['home_id'] == TEAM_ID
        phase = '常规赛' if event['phase'] == 'regular' else '季后赛'
        status = {'scheduled': '赛前', 'live': '比赛进行中', 'completed': '已完赛',
                  'tentative': '延期或时间待定，请以官方公布为准', 'cancelled': '已取消'}[event['status']]
        description = [f'2026–2027 CBA {phase} 第{event["round"]}轮',
                       f'主队：{event["home"]}；客队：{event["away"]}', f'上海久事：{"主场" if home else "客场"}',
                       f'状态：{status}', '时间：北京时间（Asia/Shanghai），预计比赛时长2小时']
        if event['score'] is not None:
            description.append(f'比分（主队–客队）：{event["score"][0]}–{event["score"][1]}')
        if len(event['start']) == 10:
            description.append('开赛时间待定；全天占位不代表比赛持续一整天')
        elif event['status'] == 'tentative':
            description.append('日历保留上次已知时间供参考，新的开赛时间尚未确认')
        description.append(f'官方比赛编号：{event["id"]}\n来源：{OFFICIAL_URL}')
        stamp = _utc(_instant(event['modified']))
        lines += ['BEGIN:VEVENT', f'UID:cba-2026-2027-{event["id"]}@cba-calendar',
                  f'DTSTAMP:{stamp}', f'LAST-MODIFIED:{stamp}', f'SEQUENCE:{event["sequence"]}']
        if len(event['start']) == 10:
            day = date.fromisoformat(event['start'])
            lines += [f'DTSTART;VALUE=DATE:{day:%Y%m%d}', f'DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}']
        else:
            dt = _instant(event['start'])
            lines += [f'DTSTART:{_utc(dt)}', f'DTEND:{_utc(dt + timedelta(hours=2))}']
        lines += [f'SUMMARY:{_text(f"🏀 {event["home"]} vs {event["away"]}（{"主场" if home else "客场"}）")}',
                  f'DESCRIPTION:{_text(chr(10).join(description))}',
                  f'STATUS:{"CANCELLED" if event["status"] == "cancelled" else "TENTATIVE" if event["status"] == "tentative" else "CONFIRMED"}',
                  f'URL:{OFFICIAL_URL}']
        if event['location']:
            lines.append(f'LOCATION:{_text(event["location"])}')
        lines += ['TRANSP:TRANSPARENT', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return b'\r\n'.join(_fold(line) for line in lines) + b'\r\n'
