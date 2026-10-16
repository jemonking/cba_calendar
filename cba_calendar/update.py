"""Build a complete Pages artifact only after validating data and prior revisions."""
import argparse
import hashlib
import html
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from http.client import HTTPException
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .calendar import merge, render_ics, validate_state
from .sources import BACKUP_URL, OFFICIAL_URL, SourceError, crosscheck, parse_backup, parse_official

DEFAULT_BASE = 'https://jemonking.github.io/cba_calendar/'


def fetch(url):
    """Two attempts for transient transport/5xx errors; no retry on access restrictions."""
    request = Request(url, headers={'User-Agent': 'CBA-Calendar/0.1 (+https://github.com/jemonking/cba_calendar)',
                                    'Accept': 'application/json,text/html;q=0.9', 'Cache-Control': 'no-cache'})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25) as response:
                body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise SourceError('response exceeds 5 MB limit')
                return body
        except HTTPError as exc:
            if exc.code < 500 or attempt:
                raise
        except (URLError, TimeoutError, ConnectionError, OSError, HTTPException):
            if attempt:
                raise
        time.sleep(2)
    raise SourceError('network retries exhausted')


def load_previous(base_url, bootstrap=False, fetcher=None):
    fetcher = fetcher or fetch
    try:
        body = fetcher(base_url.rstrip('/') + '/state.json')
    except HTTPError as exc:
        if exc.code == 404 and bootstrap:
            try:
                fetcher(base_url.rstrip('/') + '/shanghai-sharks.ics')
            except HTTPError as calendar_error:
                if calendar_error.code == 404:
                    return None
                raise SourceError(f'bootstrap calendar probe HTTP {calendar_error.code}; refusing reset') from calendar_error
            except (URLError, TimeoutError, ConnectionError, OSError, HTTPException) as calendar_error:
                raise SourceError('bootstrap calendar probe failed; refusing reset') from calendar_error
            raise SourceError('calendar exists without state; restore history instead of bootstrap')
        raise SourceError(f'previous state HTTP {exc.code}; preserve deployment; first release needs explicit bootstrap on 404') from exc
    except (URLError, TimeoutError, ConnectionError, OSError, HTTPException) as exc:
        raise SourceError('previous state unavailable; preserve deployment and revision history') from exc
    if bootstrap:
        raise SourceError('previous state exists; bootstrap is forbidden after first release')
    try:
        state = json.loads(body)
        validate_state(state)
        if state.get('state_sha256') != state_digest(state):
            raise SourceError('previous state checksum mismatch')
        # Check the OLD artifact bytes, never reinterpret history with the NEW renderer.
        published_ics = fetcher(base_url.rstrip('/') + '/shanghai-sharks.ics')
        if state.get('ics_sha256') != hashlib.sha256(published_ics).hexdigest():
            raise SourceError('previous ICS checksum mismatch; preserve deployment')
        return state
    except SourceError:
        raise
    except (ValueError, TypeError, OSError, URLError, TimeoutError, HTTPException) as exc:
        raise SourceError(f'cannot restore previous state: {type(exc).__name__}; published history validation failed') from exc


def _page(state, report, base_url):
    """Small subscription landing page; do not offer an ICS import/download CTA."""
    url = base_url.rstrip('/') + '/shanghai-sharks.ics'
    parsed = urlsplit(url)
    webcal = 'webcal://' + parsed.netloc + parsed.path
    checked = datetime.fromisoformat(state['checked_at']).astimezone(ZoneInfo('Asia/Shanghai'))
    template = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="上海久事大鲨鱼 CBA 赛程 Apple 日历订阅">
<title>上海大鲨鱼赛程 · Apple 日历订阅</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f6f8fa;color:#182e3d;font:16px/1.65 system-ui,-apple-system,"PingFang SC",sans-serif}
main{max-width:640px;margin:0 auto;padding:64px 22px}
small{color:#536777;font-weight:700;letter-spacing:.1em}
h1{font-size:clamp(29px,6vw,42px);line-height:1.3;margin:12px 0}
p{margin:12px 0;color:#42596a}
.button{display:inline-block;margin:16px 0 6px;padding:12px 22px;border-radius:8px;background:#135b86;color:white;text-decoration:none;font-weight:700}
.button:focus-visible,a:focus-visible{outline:3px solid #bd7213;outline-offset:4px}
.notice{font-size:14px}
section{margin:26px 0;padding:20px;border:1px solid #dbe4ea;border-radius:10px;background:white}
h2{font-size:18px;margin:0 0 10px}
code{display:block;overflow-wrap:anywhere;padding:12px;border-radius:6px;background:#f2f5f7;font:13px/1.7 ui-monospace,SFMono-Regular,monospace}
footer{border-top:1px solid #dbe4ea;padding-top:18px;font-size:13px;color:#536777}
footer a{color:#135b86}
@media(max-width:480px){main{padding:32px 18px}}
</style>
</head>
<body>
<main>
<small>CBA · 2026–2027</small>
<h1>🏀 上海大鲨鱼赛程</h1>
<p>订阅上海久事的常规赛及已公布的季后赛。比赛改期、比分更新后，日历会随订阅刷新。</p>
<a class="button" href="__WEBCAL__">订阅到 Apple 日历</a>
<p class="notice"><strong>请选择「订阅」，不要下载 ICS 后导入现有日历。</strong> 导入的比赛不会自动更新，也无法作为一组取消订阅。</p>
<section>
<h2>iPhone 手动订阅</h2>
<p>日历 App →「日历」→「添加日历」→「添加订阅日历」，粘贴此地址：</p>
<code>__ICS_URL__</code>
<p class="notice">以后要移除全部比赛：日历列表 → 订阅日历旁的 ⓘ →「取消订阅」。</p>
</section>
<footer>最近核验：__CHECKED__（北京时间） · __EVENT_COUNT__ 场<br>
数据来源：<a href="https://www.cbaleague.com/">CBA 官方</a> ·
<a href="https://github.com/jemonking/cba_calendar">GitHub 项目</a> ·
非官方球迷项目</footer>
</main>
</body>
</html>
"""
    return (template
            .replace('__WEBCAL__', html.escape(webcal, quote=True))
            .replace('__ICS_URL__', html.escape(url))
            .replace('__CHECKED__', checked.strftime('%Y-%m-%d %H:%M'))
            .replace('__EVENT_COUNT__', str(report['event_count'])))



def build(output, official_payload, backup_html, previous, now, base_url=DEFAULT_BASE):
    games = parse_official(official_payload)
    state, changes = merge(previous, games, now)
    try:
        audit = crosscheck(games, parse_backup(backup_html)) if backup_html else {'status': 'unavailable'}
    except SourceError as exc:
        audit = {'status': 'unavailable', 'reason': str(exc)}
    ics = render_ics(state)
    digest = hashlib.sha256(ics).hexdigest()
    state['ics_sha256'] = digest
    state['state_sha256'] = state_digest(state)
    report = {'status': 'success', 'checked_at': state['checked_at'],
              'official_source': OFFICIAL_URL, 'backup_source': BACKUP_URL,
              'event_count': len(state['events']), 'regular_count': 46,
              'ics_sha256': digest, 'changes': changes, 'crosscheck': audit}
    files = {'shanghai-sharks.ics': ics, 'state.json': _json(state),
             'update-log.json': _json(report), 'index.html': _page(state, report, base_url).encode(), '.nojekyll': b''}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    old = None
    try:
        for name, body in files.items():
            (temporary / name).write_bytes(body)
        if output.exists():
            old = Path(tempfile.mkdtemp(prefix=f'.{output.name}-previous-', dir=output.parent))
            old.rmdir()
            output.rename(old)
        try:
            temporary.rename(output)
        except OSError:
            if old:
                old.rename(output)
                old = None
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if old and old.exists():
            shutil.rmtree(old)
    return report


def state_digest(state):
    # Schema 1 canonical definition: all state except the two digest fields.
    # Keep separators/UTF-8/sorted keys stable across output-rendering changes.
    payload = {k: v for k, v in state.items() if k not in ('state_sha256', 'ics_sha256')}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('site'))
    parser.add_argument('--log', type=Path, default=Path('update-log.json'))
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--bootstrap', action='store_true', help='First deployment only, requires published state HTTP 404')
    parser.add_argument('--preview', action='store_true', help='Local build only; does not restore published state')
    parser.add_argument('--official-file', type=Path)
    parser.add_argument('--backup-file', type=Path)
    parser.add_argument('--previous-file', type=Path)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    report = {'status': 'failed', 'checked_at': now.isoformat()}
    stage = 'configuration'
    try:
        url = urlsplit(args.base_url)
        if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise SourceError('base-url must be a public HTTPS URL without credentials, query or fragment')
        if not args.preview and (args.official_file or args.backup_file or args.previous_file):
            raise SourceError('local fixtures/previous-file require --preview; production must fetch live sources')
        if args.preview and args.bootstrap:
            raise SourceError('preview and bootstrap cannot be combined')
        stage = 'restore_previous'
        if args.preview:
            previous = json.loads(args.previous_file.read_bytes()) if args.previous_file else None
            if previous is not None:
                validate_state(previous)
        else:
            previous = load_previous(args.base_url, args.bootstrap)
        stage = 'fetch_official'
        payload = json.loads(args.official_file.read_bytes() if args.official_file else fetch(OFFICIAL_URL))
        backup_error = None
        try:
            backup = args.backup_file.read_text() if args.backup_file else fetch(BACKUP_URL).decode('utf-8')
        except (OSError, URLError, TimeoutError, SourceError, UnicodeError, HTTPException) as exc:
            backup = None
            backup_error = f'{type(exc).__name__}: backup unavailable; official remains authoritative'
        stage = 'validate_and_build'
        report = build(args.output, payload, backup, previous, now, args.base_url)
        if backup_error:
            report['warnings'] = [backup_error]
        report['mode'] = 'preview' if args.preview else 'bootstrap' if args.bootstrap else 'update'
        # Same report inside the artifact and beside it, including mode and network warnings.
        (args.output / 'update-log.json').write_bytes(_json(report))
    except (OSError, ValueError, TypeError, KeyError, URLError, TimeoutError, HTTPException) as exc:
        if isinstance(exc, HTTPError):
            error = f'HTTP {exc.code}; source unavailable/access restricted; no calendar published'
        elif isinstance(exc, URLError):
            error = 'Network unavailable; no calendar published'
        else:
            error = str(exc)
        report['error'] = error
        report['stage'] = stage
        print(f'::error title=CBA Calendar update blocked::{error.replace(chr(10), " ")}')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_bytes(_json(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
