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
    conda.write_text(
        '@echo off\n'
        'echo %* >> "%CH_TEST_CALLS%"\n'
        'echo %CD% >> "%CH_TEST_CWD%"\n'
        'if defined CH_TEST_STDOUT echo %CH_TEST_STDOUT%\n'
        'if defined CH_TEST_STDERR echo %CH_TEST_STDERR% 1>&2\n'
        'set "EXIT_TO_USE=%CH_TEST_EXIT%"\n'
        'echo %* | findstr /c:"src.app.gui" >nul\n'
        'if not errorlevel 1 set "EXIT_TO_USE=%CH_TEST_GUI_EXIT%"\n'
        'exit /b %EXIT_TO_USE%\n', encoding='ascii')
    env = os.environ.copy()
    env.update({
        'USERPROFILE': str(home), 'HOME': str(home), 'LOCALAPPDATA': str(home / 'AppData' / 'Local'),
        'TEMP': str(tmp_path), 'TMP': str(tmp_path), 'ProgramData': str(tmp_path / 'shared-conda'),
        'ProgramFiles': str(tmp_path / 'program-files'), 'ProgramFiles(x86)': str(tmp_path / 'program-files-x86'),
        'PATH': str(Path(os.environ['SystemRoot']) / 'System32'),
        'CONDA_EXE': str(conda), 'CH_KANBAN_ENV_PREFIX': str(prefix),
        'CH_TEST_CALLS': str(tmp_path / 'calls.txt'), 'CH_TEST_CWD': str(tmp_path / 'cwd.txt'),
        'CH_TEST_EXIT': '0', 'CH_TEST_GUI_EXIT': '0',
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


@pytest.mark.parametrize('self_test', [True, False], ids=['self-test', 'gui'])
def test_bat_logs_stdout_without_stderr_and_succeeds(launcher, self_test):
    _, env = launcher
    env['CH_TEST_STDOUT'] = '標準出力: 起動確認'
    result = _launch(launcher, self_test=self_test)
    assert result.returncode == 0, result.stdout + result.stderr

    log_dir = Path(env['LOCALAPPDATA']) / 'CHKanban' / 'output' / 'logs'
    logs = list(log_dir.glob('startup_*.log'))
    assert len(logs) == 1
    text = logs[0].read_text(encoding='utf-8-sig')
    assert '標準出力: 起動確認' in text
    assert '\x00' not in text


@pytest.mark.parametrize('self_test', [True, False], ids=['self-test', 'gui'])
def test_bat_logs_stdout_and_stderr_warning_without_failing(launcher, self_test):
    _, env = launcher
    env['CH_TEST_STDOUT'] = '標準出力: 起動確認'
    env['CH_TEST_STDERR'] = '警告: 任意の確認メッセージ'
    result = _launch(launcher, self_test=self_test)
    assert result.returncode == 0, result.stdout + result.stderr

    log_dir = Path(env['LOCALAPPDATA']) / 'CHKanban' / 'output' / 'logs'
    logs = list(log_dir.glob('startup_*.log'))
    assert len(logs) == 1
    text = logs[0].read_text(encoding='utf-8-sig')
    assert '標準出力: 起動確認' in text
    assert '警告: 任意の確認メッセージ' in text
    assert '\x00' not in text


@pytest.mark.parametrize('self_test', [True, False], ids=['self-test', 'gui'])
def test_bat_reports_nonzero_exit_after_logging_both_streams(launcher, self_test):
    _, env = launcher
    env['CH_TEST_STDOUT'] = '標準出力: 実行結果'
    env['CH_TEST_STDERR'] = '標準エラー: 実行警告'
    env['CH_TEST_EXIT'] = '7' if self_test else '0'
    env['CH_TEST_GUI_EXIT'] = '7' if not self_test else '0'
    result = _launch(launcher, self_test=self_test)
    assert result.returncode != 0

    log_dir = Path(env['LOCALAPPDATA']) / 'CHKanban' / 'output' / 'logs'
    logs = list(log_dir.glob('startup_*.log'))
    assert len(logs) == 1
    text = logs[0].read_text(encoding='utf-8-sig')
    assert '標準出力: 実行結果' in text
    assert '標準エラー: 実行警告' in text
    assert 'exit 7' in text
    assert '\x00' not in text


def test_bat_fails_when_conda_process_cannot_start(launcher):
    _, env = launcher
    invalid_exe = Path(env['USERPROFILE']) / 'miniconda3' / 'Scripts' / 'conda.exe'
    invalid_exe.parent.mkdir(parents=True)
    invalid_exe.write_bytes(b'not a Windows executable')
    env['CONDA_EXE'] = str(invalid_exe)
    result = _launch(launcher)
    assert result.returncode != 0
    assert b'[ERROR]' in result.stdout + result.stderr
    assert b'src.app.gui' not in _calls(env)


def test_bat_fails_when_startup_log_cannot_be_created(launcher):
    _, env = launcher
    localappdata = Path(env['LOCALAPPDATA'])
    localappdata.parent.mkdir(parents=True)
    localappdata.write_text('not a directory', encoding='utf-8')
    result = _launch(launcher)
    assert result.returncode != 0
    assert b'[ERROR]' in result.stdout + result.stderr
    assert not _calls(env)


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
