"""Strict adapters for observed public CBA JSON and 90vs hidden HTML tables."""
import re
from collections import Counter
from datetime import date, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

OFFICIAL_URL = 'https://portal-server.cbaleague.com/home/home_schedules'
BACKUP_URL = 'https://nba.90vs.com/zl/3/index.html'
TEAM_ID = 29125
SEASON = 2026
TZ = ZoneInfo('Asia/Shanghai')


class SourceError(ValueError):
    pass


def _integer(value, field):
    if isinstance(value, bool):
        raise SourceError(f'invalid {field}')
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise SourceError(f'invalid {field}') from exc
    if str(result) != str(value):
        raise SourceError(f'invalid {field}')
    return result


def _text(value, field, required=True):
    if value is None and not required:
        return ''
    if not isinstance(value, str) or (required and not value.strip()):
        raise SourceError(f'invalid {field}')
    if any(ord(ch) < 32 and ch not in '\n\t\r' for ch in value):
        raise SourceError(f'control character in {field}')
    return value.strip()


def parse_official(payload):
    if not isinstance(payload, dict) or payload.get('code') != 200 or not isinstance(payload.get('data'), list):
        raise SourceError('official response schema/code changed')
    games = []
    for row in payload['data']:
        try:
            if not isinstance(row, dict):
                raise SourceError('official row is not an object')
            phase = _integer(row['ScheduleTypeID'], 'ScheduleTypeID')
            if phase not in (1, 2):
                continue
            home_id = _integer(row['HomeTeamID'], 'HomeTeamID')
            away_id = _integer(row['VisitingTeamID'], 'VisitingTeamID')
            if TEAM_ID not in (home_id, away_id):
                continue
            # Sparse official records lack Season: validate their date window below.
            if row.get('Season') is not None and _integer(row['Season'], 'Season') != SEASON:
                raise SourceError('unexpected season on Shanghai game')
            if home_id == away_id:
                raise SourceError('identical home and away team')
            raw_status = _integer(row['Status'], 'Status')
            label = _text(row.get('StatusCNName'), 'StatusCNName', False)
            if '取消' in label:
                status = 'cancelled'
            elif any(word in label for word in ('延期', '推迟', '待定', '中断')):
                status = 'tentative'
            elif raw_status in (1, 2, 4):
                status = {1: 'scheduled', 2: 'live', 4: 'completed'}[raw_status]
            else:
                raise SourceError(f'unknown official status {raw_status}; mapping needs review')
            day = row.get('dates')
            start = None
            if day:
                parsed_day = date.fromisoformat(day)
                if not date(2026, 8, 1) <= parsed_day < date(2027, 8, 1):
                    raise SourceError('date outside season window')
                clock = row.get('time')
                if row.get('TimeTBAState') == 1 or not clock or clock == '00:00':
                    start = day
                    if status != 'cancelled':
                        status = 'tentative'
                else:
                    start = datetime.strptime(f'{day} {clock}', '%Y-%m-%d %H:%M').replace(tzinfo=TZ).isoformat()
            elif status not in ('tentative', 'cancelled'):
                raise SourceError('missing schedule date')
            score = None
            if status in ('completed', 'live'):
                scores = (row.get('HomeTeamScore'), row.get('VisitingTeamScore'))
                if status == 'completed' or all(s is not None for s in scores):
                    score = [_integer(s, 'score') for s in scores]
                    if min(score) < 0:
                        raise SourceError('negative score')
            games.append({
                'id': _integer(row['ScheduleID'], 'ScheduleID'), 'season': SEASON,
                'phase': 'regular' if phase == 1 else 'playoffs',
                'round': _integer(row['Round'], 'Round'),
                'home_id': home_id, 'away_id': away_id,
                'home': _text(row['HomeTeamName'], 'HomeTeamName'),
                'away': _text(row['VisitingTeamName'], 'VisitingTeamName'),
                'start': start, 'status': status, 'score': score,
                'location': _text(row.get('stadium'), 'stadium', False),
            })
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SourceError):
                raise
            raise SourceError(f'invalid official Shanghai record: {exc}') from exc
    return games


def validate_schedule(games):
    if not games:
        raise SourceError('empty Shanghai schedule; refusing publication')
    ids = [g['id'] for g in games]
    if len(ids) != len(set(ids)) or any(i <= 0 for i in ids):
        raise SourceError('duplicate/invalid official match ID')
    regular = [g for g in games if g['phase'] == 'regular']
    if len(regular) != 46:
        raise SourceError(f'expected 46 regular games, got {len(regular)}; refusing publication')
    if Counter(g['round'] for g in regular) != Counter(range(1, 47)):
        raise SourceError('regular rounds must cover 1–46 exactly once')
    if sum(g['home_id'] == TEAM_ID for g in regular) != 23:
        raise SourceError('expected 23 home and 23 away regular games')


class _BackupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table = dict(attrs).get('id')
        elif tag == 'tr':
            self.row = []
        elif tag == 'td':
            self.cell = ''

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            if self.row is not None:
                self.row.append(self.cell.strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.table == 'divindex' or re.fullmatch(r'div3_57_[2-7]', self.table or ''):
                self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            self.table = None


def parse_backup(html):
    if not re.search(r'<h1[^>]*>\s*<span>2026-2027</span>', html):
        raise SourceError('backup season/header changed')
    parser = _BackupParser()
    parser.feed(html)
    games = []
    for row in parser.rows:
        if len(row) < 5 or '上海久事' not in (row[2], row[4]):
            continue
        try:
            start = datetime.strptime(row[1], '%y-%m-%d %H:%M').replace(tzinfo=TZ).isoformat()
        except ValueError as exc:
            raise SourceError('invalid backup date') from exc
        games.append({'home': row[2], 'away': row[4], 'start': start})
    if not games:
        raise SourceError('no Shanghai games in backup')
    return games


def crosscheck(official, backup):
    """Report evidence only. Backup never creates IDs or overwrites official times."""
    remaining = list(backup)
    missing, conflicts, matched = [], [], 0
    for game in official:
        if game['phase'] != 'regular':
            continue
        exact = next((r for r in remaining if all(r[k] == game[k] for k in ('home', 'away', 'start'))), None)
        if exact is not None:
            remaining.remove(exact)
            matched += 1
        else:
            missing.append(game['id'])
    # Pair unmatched games by teams only when unambiguous; repeated opponents stay unmatched.
    for game in official:
        if game['id'] not in missing:
            continue
        possible = [r for r in remaining if r['home'] == game['home'] and r['away'] == game['away']]
        if len(possible) == 1:
            row = possible[0]
            conflicts.append({'id': game['id'], 'official_start': game['start'], 'backup_start': row['start']})
            remaining.remove(row)
    return {'matched': matched, 'missing_official_ids': missing, 'conflicts': conflicts,
            'backup_only': remaining, 'backup_count': len(backup), 'authority': 'official'}
