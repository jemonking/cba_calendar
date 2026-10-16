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
    url = base_url.rstrip('/') + '/shanghai-sharks.ics'
    webcal = 'webcal://' + urlsplit(url).netloc + urlsplit(url).path
    stamp = datetime.fromisoformat(state['checked_at']).astimezone(ZoneInfo('Asia/Shanghai'))
    audit = report['crosscheck']
    if audit.get('status') == 'unavailable':
        evidence = '备用来源本轮未能核对；以下日程来自官方公开接口。'
    else:
        evidence = f'本轮备用来源匹配 {audit["matched"]} 场；缺失或不一致 {len(audit["missing_official_ids"])} 场。采用官方赛程。'
    rows = []
    for event in sorted(state['events'].values(), key=lambda e: (e['start'], e['id'])):
        start = event['start'][:16].replace('T', ' ')
        place = '主场' if event['home_id'] == 29125 else '客场'
        label = {'scheduled': '', 'live': ' · 进行中', 'completed': ' · 已完赛', 'cancelled': ' · 已取消', 'tentative': ' · 时间待定'}[event['status']]
        rows.append(f'<tr><td>{html.escape(start)}</td><td>{html.escape(event["home"])} vs {html.escape(event["away"])}</td><td>{place}{label}</td></tr>')
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>CBA Calendar · 上海大鲨鱼赛程</title>
<style>
:root{{color-scheme:light;--ink:#142e47;--blue:#004b85;--line:#d5e1ea}}*{{box-sizing:border-box}}body{{margin:0;background:#f5f8fa;color:var(--ink);font:16px/1.7 system-ui,-apple-system,"PingFang SC",sans-serif}}main{{max-width:900px;margin:auto;padding:64px 24px}}.eyebrow{{letter-spacing:.18em;color:var(--blue);font-weight:700;font-size:13px}}h1{{font-size:clamp(30px,6vw,48px);line-height:1.25;margin:16px 0}}h2{{font-size:22px;margin-top:38px}}.lead{{max-width:650px;color:#415b70}}a{{color:var(--blue)}}.button{{display:inline-block;margin:18px 0 8px;padding:12px 24px;background:var(--blue);color:white;border-radius:6px;text-decoration:none;font-weight:700}}.url{{display:block;overflow-wrap:anywhere;padding:12px;background:white;border:1px solid var(--line);border-radius:6px;font:14px/1.6 ui-monospace,monospace}}.note{{font-size:14px;color:#4e6577}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}}th{{color:var(--blue)}}td:first-child{{white-space:nowrap}}footer{{margin-top:36px;border-top:1px solid var(--line);padding-top:20px;font-size:13px}}a:focus-visible{{outline:3px solid #e48a2e;outline-offset:4px}}@media(max-width:500px){{main{{padding:32px 16px}}th,td{{padding:10px 8px}}}}
</style></head><body><main><div class="eyebrow">CBA CALENDAR · 2026–2027</div><h1>上海大鲨鱼 CBA 赛程</h1>
<p class="lead">订阅一次，持续获取上海久事的常规赛与已公布的季后赛。官方调整比赛时间后，在同一条日程中更新。</p>
<a class="button" href="{html.escape(webcal, quote=True)}">添加到 Apple 日历</a><p class="note">请使用订阅功能；下载后导入不会持续更新。</p>
<span class="url">{html.escape(url)}</span><p><a href="shanghai-sharks.ics">查看 ICS 文件</a></p>
<h2>如何订阅</h2><ol><li>iPhone / iPad：点击上方按钮并确认订阅；或在日历 App 中选择“日历 → 添加日历 → 添加订阅日历”，粘贴上方地址。</li><li>Mac：打开日历，选择“文件 → 新建日历订阅”，粘贴地址，并设置自动刷新。</li><li>已订阅后无需重复添加。刷新速度取决于 Apple Calendar 和你的设备设置。</li></ol>
<h2>更新与范围</h2><p>每天北京时间 10:23、18:23 检查官方赛程。GitHub 排队和客户端刷新可能产生延迟。包含常规赛和已公布的季后赛；不含季前赛、俱乐部杯与全明星赛。</p>
<p>北京时间显示。比赛预计持续 2 小时；延期标为待定，取消保留取消标记。来源故障时继续提供上次成功版本。</p>
<p class="note">最近核验：{stamp:%Y-%m-%d %H:%M} 北京时间 · 常规赛 {report['regular_count']} 场 · 日历共 {report['event_count']} 场<br>{html.escape(evidence)}<br>浙江浙商证券为浙江广厦队当前官方冠名；日历沿用官方队名。</p>
<h2>比赛安排</h2><div class="table-wrap"><table><thead><tr><th scope="col">北京时间</th><th scope="col">比赛</th><th scope="col">上海主客场 / 状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<footer>公开赛程来源：<a href="https://www.cbaleague.com/">CBA 官方</a> · <a href="https://nba.90vs.com/zl/3/index.html">90vs 交叉核对</a> · <a href="https://github.com/jemonking/cba_calendar">项目与故障说明</a><br>非官方球迷项目，与 CBA 及俱乐部无隶属关系。</footer></main></body></html>'''


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
