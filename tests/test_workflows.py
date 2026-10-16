from pathlib import Path

import yaml


def test_pages_pipeline_is_direct_serial_and_failure_gated():
    workflow = yaml.load(Path('.github/workflows/update.yml').read_text(), Loader=yaml.BaseLoader)
    assert workflow['on']['schedule'][0]['cron'] == '23 2,10 * * *'
    assert workflow['on']['workflow_dispatch']['inputs']['bootstrap']['default'] == 'false'
    assert workflow['concurrency']['cancel-in-progress'] == 'false'
    assert workflow['permissions'] == {'contents': 'read'}
    build = workflow['jobs']['build']
    assert build['if'] == "github.ref == 'refs/heads/main'"
    steps = build['steps']
    artifact = next(s for s in steps if s.get('uses', '').startswith('actions/upload-pages-artifact@'))
    assert artifact['with']['path'] == 'site'
    assert 'if' not in artifact  # Default success(), never always().
    generate = next(s for s in steps if s.get('id') == 'generate')
    assert '--preview' not in generate['run']
    assert '--official-file' not in generate['run']
    deploy = workflow['jobs']['deploy']
    assert deploy['needs'] == 'build'
    assert deploy['if'] == "needs.build.outputs.ready == 'true'"
    assert deploy['permissions'] == {'pages': 'write', 'id-token': 'write'}
    assert deploy['steps'][0]['uses'].startswith('actions/deploy-pages@')
    assert not any('git push' in s.get('run', '') or 'git commit' in s.get('run', '') for s in steps)
