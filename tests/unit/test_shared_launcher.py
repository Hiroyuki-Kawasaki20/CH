"""実conda・GUIを起動せず、共通batをWindows cmdで実行する。"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_local_output_path import REPO_ROOT, _run_child

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows bat integration')


@pytest.fixture
def launcher(tmp_path):
    shared = tmp_path / '共有 app'
    shared.mkdir()
    shutil.copy2(REPO_ROOT / 'run_ch_kanban.bat', shared / 'run_ch_kanban.bat')
    script = REPO_ROOT / 'scripts' / 'start_ch_kanban.ps1'
    if script.exists():
        (shared / 'scripts').mkdir()
        shutil.copy2(script, shared / 'scripts' / script.name)
    home = tmp_path / 'user home'
    home.mkdir()
    prefix = home / '.conda' / 'envs' / 'DIG_new'
    prefix.mkdir(parents=True)
    (prefix / 'python.exe').touch()  # fake condaはこのファイルを実行しない
    (prefix / 'conda-meta').mkdir()
    conda = home / 'miniconda3' / 'condabin' / 'conda.bat'
    conda.parent.mkdir(parents=True)
    conda.write_text('@echo off\necho %* >> "%CH_TEST_CALLS%"\necho %CD% >> "%CH_TEST_CWD%"\nexit /b %CH_TEST_EXIT%\n', encoding='ascii')
    env = os.environ.copy()
    env.update({
        'USERPROFILE': str(home), 'HOME': str(home), 'LOCALAPPDATA': str(home / 'AppData' / 'Local'),
        'TEMP': str(tmp_path), 'TMP': str(tmp_path), 'ProgramData': str(tmp_path / 'shared-conda'),
        'ProgramFiles': str(tmp_path / 'program-files'), 'ProgramFiles(x86)': str(tmp_path / 'program-files-x86'),
        'PATH': str(Path(os.environ['SystemRoot']) / 'System32'),
        'CONDA_EXE': str(conda), 'CH_KANBAN_ENV_PREFIX': str(prefix),
        'CH_TEST_CALLS': str(tmp_path / 'calls.txt'), 'CH_TEST_CWD': str(tmp_path / 'cwd.txt'), 'CH_TEST_EXIT': '0',
    })
    return shared, env


def _launch(launcher, *, self_test=True):
    shared, env = launcher
    command = f'""{shared / "run_ch_kanban.bat"}"' + (' --self-test' if self_test else '') + '"'
    result = subprocess.run(
        f'"{os.environ["COMSPEC"]}" /d /s /c {command}', cwd=shared.parent, env=env,
        input=b'\n', capture_output=True, timeout=30,
    )
    return result


def _calls(env):
    path = Path(env['CH_TEST_CALLS'])
    return path.read_bytes() if path.exists() else b''


def test_bat_requires_explicit_personal_environment(launcher):
    _, env = launcher
    env.pop('CH_KANBAN_ENV_PREFIX')
    result = _launch(launcher)
    assert result.returncode != 0
    assert b'CH_KANBAN_ENV_PREFIX' in result.stdout + result.stderr
    assert not _calls(env)


@pytest.mark.parametrize('invalid', ['missing', 'other-user', 'base'])
def test_bat_rejects_missing_foreign_or_base_environment(launcher, invalid):
    shared, env = launcher
    prefix = Path(env['CH_KANBAN_ENV_PREFIX'])
    if invalid == 'missing':
        (prefix / 'python.exe').unlink()
    else:
        wrong = shared.parent / 'other-user' / 'DIG_new' if invalid == 'other-user' else Path(env['USERPROFILE']) / 'base'
        wrong.mkdir(parents=True)
        (wrong / 'python.exe').touch(); (wrong / 'conda-meta').mkdir()
        env['CH_KANBAN_ENV_PREFIX'] = str(wrong)
    assert _launch(launcher).returncode != 0
    assert not _calls(env)


def test_bat_reports_no_conda_without_system_python_fallback(launcher):
    _, env = launcher
    Path(env['CONDA_EXE']).unlink()
    env.pop('CONDA_EXE')
    result = _launch(launcher)
    assert result.returncode != 0
    assert b'conda' in result.stdout.lower() + result.stderr.lower()
    assert not _calls(env)


def test_bat_does_not_execute_other_users_conda(launcher):
    shared, env = launcher
    foreign = shared.parent / 'other-user' / 'conda.bat'
    foreign.parent.mkdir()
    shutil.copy2(env['CONDA_EXE'], foreign)
    env['CONDA_EXE'] = str(foreign)
    assert _launch(launcher).returncode != 0
    assert not _calls(env)


@pytest.mark.parametrize('shared_conda', [False, True])
def test_bat_uses_prefix_and_self_test_without_gui(launcher, shared_conda):
    shared, env = launcher
    if shared_conda:
        conda = Path(env['ProgramData']) / 'anaconda3' / 'condabin' / 'conda.bat'
        conda.parent.mkdir(parents=True)
        shutil.copy2(env['CONDA_EXE'], conda)
        env['CONDA_EXE'] = str(conda)
    result = _launch(launcher)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(env)
    assert b'run -p ' in calls and b'run -n ' not in calls
    assert env['CH_KANBAN_ENV_PREFIX'].encode('ascii') in calls
    assert b'src.app.startup_check' in calls and b'src.app.gui' not in calls
    log_dir = Path(env['LOCALAPPDATA']) / 'CHKanban' / 'output' / 'logs'
    logs = list(log_dir.glob('startup_*.log'))
    assert logs
    text = logs[0].read_text(encoding='utf-8-sig')
    assert '\x00' not in text and 'Conda:' in text
    assert not list(shared.glob('*.log'))


def test_normal_launch_uses_script_directory_and_disables_bytecode(launcher):
    shared, env = launcher
    result = _launch(launcher, self_test=False)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(env)
    assert b'-B -m src.app.gui' in calls
    recorded_cwd = Path(env['CH_TEST_CWD']).read_bytes()
    assert str(shared).encode('utf-8') in recorded_cwd or str(shared).encode('mbcs') in recorded_cwd


def test_diagnostics_failure_stops_before_gui(launcher):
    _, env = launcher
    env['CH_TEST_EXIT'] = '7'
    result = _launch(launcher, self_test=False)
    assert result.returncode != 0
    assert b'src.app.gui' not in _calls(env)


def test_startup_check_reports_interpreter_libraries_and_paths(tmp_path):
    # APIが存在しないだけのREDを本件のREDとして扱わない。bat動作テストと併用する。
    output = _run_child(tmp_path, """
        import runpy
        sys.argv = ['startup_check', '--expected-python', sys.executable]
        runpy.run_module('src.app.startup_check', run_name='__main__')
    """)
    for label in ('sys.executable:', 'Python:', 'Library: tkinter', 'Library: pandas',
                  'Library: numpy', 'Library: openpyxl', 'Library: customtkinter',
                  'Settings:', 'History:', 'Local output:', 'Staging:', '[OK]'):
        assert label in output


@pytest.mark.parametrize('localappdata', [None, ''])
def test_bat_logging_falls_back_to_own_home(launcher, localappdata):
    _, env = launcher
    if localappdata is None:
        env.pop('LOCALAPPDATA')
    else:
        env['LOCALAPPDATA'] = localappdata
    assert _launch(launcher).returncode == 0
    logs = Path(env['USERPROFILE']) / 'AppData' / 'Local' / 'CHKanban' / 'output' / 'logs'
    assert list(logs.glob('startup_*.log'))
