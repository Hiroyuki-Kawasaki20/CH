"""共通ソース配置と利用者別設定の回帰。実設定を読まず子プロセスで検証する。"""

import pytest

from tests.unit.test_local_output_path import _run_child


def test_users_do_not_share_settings_history_or_logs(tmp_path):
    write = """
        from src.services import data_loader as dl, lane_end_times_history as history
        from src.app import gui
        import logging
        assert dl.get_config_path() == expected.parent / 'ch_kanban_settings.json'
        assert history.get_history_path() == expected.parent / 'lane_end_times_history.json'
        assert not dl.get_config_path().exists()
        assert dl.load_config() == {} and history.load_lane_end_times_history() == []
        dl.save_config({'owner': os.environ['LOCALAPPDATA'], 'unknown_key': {'keep': True}})
        assert history.save_lane_end_times_history([{'メイン': 90000}])
        gui._setup_logging()
        logging.shutdown()
        assert (expected / 'logs' / 'ch_kanban.log').exists()
    """
    for user in ('A', 'B'):
        _run_child(tmp_path, write, localappdata=user)
    for user in ('A', 'B'):
        _run_child(tmp_path, """
            from src.services import data_loader as dl, lane_end_times_history as history
            assert dl.load_config()['owner'] == os.environ['LOCALAPPDATA']
            assert dl.load_config()['unknown_key'] == {'keep': True}
            assert history.load_lane_end_times_history() == [{'メイン': 90000}]
        """, localappdata=user)


@pytest.mark.parametrize('localappdata', [None, ''])
def test_user_storage_home_fallback_has_no_import_writes(tmp_path, localappdata):
    _run_child(tmp_path, """
        from src.services import data_loader as dl, lane_end_times_history as history
        assert dl.get_config_path() == expected.parent / 'ch_kanban_settings.json'
        assert history.get_history_path() == expected.parent / 'lane_end_times_history.json'
        assert not expected.parent.exists()
    """, localappdata=localappdata)


def test_old_shared_config_and_history_are_not_adopted(tmp_path):
    _run_child(tmp_path, """
        import shutil
        # 模擬共有配置（本物のrepo内configには触れない）。
        shared = sandbox / 'shared app'
        shutil.copytree(Path(os.environ['PYTHONPATH']) / 'src', shared / 'src', ignore=shutil.ignore_patterns('__pycache__'))
        (shared / 'config').mkdir()
        for folder in (shared, shared / 'config'):
            (folder / 'ch_kanban_settings.json').write_text('{"base_dir": "other-user"}', encoding='utf-8')
            (folder / 'lane_end_times_history.json').write_text('{"history": [{"メイン": 123}]}', encoding='utf-8')
        sys.path.insert(0, str(shared))
        from src.services import data_loader as dl, lane_end_times_history as history
        assert dl.load_config() == {}
        assert history.load_lane_end_times_history() == []
    """)


def test_initial_selection_is_saved_and_reused_without_dialogs(tmp_path):
    _run_child(tmp_path, """
        from src.services import data_loader as dl
        assert dl.get_config_path() == expected.parent / 'ch_kanban_settings.json'
        source = sandbox / 'OneDrive input'
        destination = sandbox / 'OneDrive output'
        source.mkdir(); destination.mkdir()
        (source / '出荷情報_CH_最新版.csv').touch()
        (source / '出荷場一覧.csv').touch()
        dl.save_config({'unknown_key': [1, 2], 'archive_enabled': False})
        with patch.object(dl, 'select_data_folder', return_value=source) as choose_input, \
             patch.object(dl, 'select_export_folder', return_value=destination) as choose_output, \
             patch('tkinter.messagebox.showinfo'):
            assert dl.get_base_dir() == source
            assert dl.get_export_dir() == destination
            assert choose_input.call_count == choose_output.call_count == 1
        assert dl.load_config()['unknown_key'] == [1, 2]
        assert dl.load_config()['archive_enabled'] is False
        assert list(destination.iterdir()) == []  # 権限確認用のSPOファイルを作らない
    """)
    _run_child(tmp_path, """
        from src.services import data_loader as dl
        with patch.object(dl, 'select_data_folder', side_effect=AssertionError('input dialog')), \
             patch.object(dl, 'select_export_folder', side_effect=AssertionError('output dialog')), \
             patch('tkinter.messagebox.showinfo', side_effect=AssertionError('dialog')):
            assert dl.get_base_dir() == sandbox / 'OneDrive input'
            assert dl.get_export_dir() == sandbox / 'OneDrive output'
    """)


@pytest.mark.parametrize('kind', ['base', 'export', 'master'])
def test_relative_config_does_not_resolve_against_shared_app(tmp_path, kind):
    _run_child(tmp_path, f"kind = {kind!r}\n" + """
from src.services import data_loader as dl
if kind == 'master':
    try:
        dl._resolve_master_path({'master_path': '入車時間マスタ.xlsx'})
    except dl.MasterFileError:
        pass
    else:
        raise AssertionError('relative master would use the shared application directory')
else:
    get = dl.get_base_dir if kind == 'base' else dl.get_export_dir
    select = 'select_data_folder' if kind == 'base' else 'select_export_folder'
    with patch.object(dl, 'load_config', return_value={kind + '_dir': '.'}), patch.object(dl, select, return_value=None), patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.askyesno', return_value=True):
        try:
            get()
        except SystemExit:
            pass
        else:
            raise AssertionError('relative directory must require re-selection')
""")


@pytest.mark.parametrize('kind', ['base', 'export'])
def test_cancel_and_missing_folder_do_not_adopt_another_location(tmp_path, kind):
    _run_child(tmp_path, f"kind = {kind!r}\n" + """
from src.services import data_loader as dl
assert dl.get_config_path() == expected.parent / 'ch_kanban_settings.json'
key = 'base_dir' if kind == 'base' else 'export_dir'
select = 'select_data_folder' if kind == 'base' else 'select_export_folder'
get = dl.get_base_dir if kind == 'base' else dl.get_export_dir
for existing in (False, True):
    if existing:
        dl.save_config({key: str(sandbox / 'missing'), 'keep': 1})
    before = dl.get_config_path().read_bytes() if existing else None
    with patch.object(dl, select, return_value=None), patch('tkinter.messagebox.showinfo') as info, patch('tkinter.messagebox.askyesno', return_value=True):
        try:
            get()
        except SystemExit:
            pass
        else:
            raise AssertionError('cancel must stop')
        assert info.called
    if existing:
        assert dl.get_config_path().read_bytes() == before
    else:
        assert not dl.get_config_path().exists()
""")


@pytest.mark.parametrize('payload', ['{broken', '[]', 'null', '"string"', '42'])
def test_invalid_config_is_handled_as_empty(tmp_path, payload):
    _run_child(tmp_path, f"payload = {payload!r}\n" + """
from src.services import data_loader as dl
with patch.object(dl, 'get_config_path', return_value=sandbox / 'test.json'):
    dl.get_config_path().write_text(payload, encoding='utf-8')
    assert dl.load_config() == {}
""")


def test_config_replace_failure_preserves_old_file_and_cleans_unique_temp(tmp_path):
    _run_child(tmp_path, """
        from src.services import data_loader as dl
        assert dl.get_config_path() == expected.parent / 'ch_kanban_settings.json'
        dl.save_config({'old': 1})
        original = dl.get_config_path().read_bytes()
        attempts = []
        def fail(source, target):
            source, target = Path(source), Path(target)
            assert source.parent == target.parent == dl.get_config_path().parent
            assert source != target
            attempts.append(source)
            raise PermissionError('replace denied')
        with patch('os.replace', side_effect=fail):
            for _ in range(2):
                try:
                    dl.save_config({'new': 2})
                except PermissionError:
                    pass
                else:
                    raise AssertionError('save must not report success')
        assert len(set(attempts)) == 2
        assert dl.get_config_path().read_bytes() == original
        assert set(dl.get_config_path().parent.iterdir()) == {dl.get_config_path()}
    """)


def test_first_selection_save_failure_propagates(tmp_path):
    _run_child(tmp_path, """
        from src.services import data_loader as dl
        with patch.object(dl, 'load_config', return_value={}), \
             patch.object(dl, 'select_export_folder', return_value=sandbox), \
             patch.object(dl, 'save_config', side_effect=PermissionError('denied')), \
             patch('tkinter.messagebox.showinfo'):
            try:
                dl.get_export_dir()
            except PermissionError:
                pass
            else:
                raise AssertionError('failed save must not return a successful selection')
    """)


def test_shared_app_is_read_only_and_staging_is_user_local(tmp_path):
    _run_child(tmp_path, """
        from src.services import data_loader as dl, lane_end_times_history as history, spo_export
        from src.models.constants import LOCAL_OUTPUT_DIR
        assert dl.get_config_path() == expected.parent / 'ch_kanban_settings.json'
        assert Path(spo_export.DEFAULT_STAGING_DIR) == expected / '_staging'
        # _run_childの監査フックが共有ソース配下への全書込みを拒否（ACL変更なし）。
        dl.save_config({'test': True})
        assert history.save_lane_end_times_history([{'メイン': 90000}])
        import pandas as pd
        output = spo_export.export_to_spo_staged(pd.DataFrame({'test': [1]}), str(sandbox / 'export'))
        assert Path(output).parent == sandbox / 'export'
        assert not list((expected / '_staging').iterdir())
    """)


def test_master_uses_selected_base_and_never_implicit_legacy(tmp_path):
    _run_child(tmp_path, """
        from src.services import data_loader as dl
        base = sandbox / 'selected-input'
        legacy = sandbox / 'shared' / dl.MASTER_FILENAME
        legacy.parent.mkdir(); legacy.touch()
        with patch.object(dl, 'get_legacy_master_path', return_value=legacy):
            assert dl._resolve_master_path({'base_dir': str(base)}) == base / dl.MASTER_FILENAME
            explicit = sandbox / 'explicit' / 'master.xlsx'
            assert dl._resolve_master_path({'base_dir': str(base), 'master_path': str(explicit)}) == explicit
            assert dl._resolve_master_path_candidates({'base_dir': str(base)}) == [base / dl.MASTER_FILENAME]
            try:
                dl._resolve_master_path({})
            except dl.MasterFileError:
                pass
            else:
                raise AssertionError('no configured master must not use application neighbour')
    """)


def test_history_save_failure_is_not_reported_as_clear_success(tmp_path):
    _run_child(tmp_path, """
        from types import SimpleNamespace
        from src.app import gui
        app = SimpleNamespace(lane_end_times_history=[{'メイン': 123}])
        with patch.object(gui, 'save_lane_end_times_history', return_value=False), \
             patch.object(gui.messagebox, 'showerror') as error, patch.object(gui.messagebox, 'showinfo') as info:
            gui.App.clear_lane_time_carryover(app)
            assert error.called and not info.called
            assert app.lane_end_times_history == [{'メイン': 123}]
    """)


def test_missing_master_is_reported_in_gui(tmp_path):
    _run_child(tmp_path, """
        from types import SimpleNamespace
        from src.app import gui
        app = SimpleNamespace(refresh_master_tree=lambda: None, refresh_routes=lambda: None)
        missing = sandbox / 'selected-input' / '入車時間マスタ.xlsx'
        with patch.object(gui, 'get_master_path', return_value=missing), patch.object(gui.messagebox, 'showwarning') as warning:
            gui.App._initial_load_master(app)
            assert warning.called and str(missing) in warning.call_args.args[1]
    """)


def test_config_merge_and_io_failures_preserve_existing_settings(tmp_path):
    _run_child(tmp_path, """
        from src.services import data_loader as dl
        dl.save_config({'keep': 1})
        dl.save_config({'new': 2})
        assert dl.load_config() == {'keep': 1, 'new': 2}
        original = dl.get_config_path().read_bytes()
        with patch.object(Path, 'open', side_effect=PermissionError('read denied')):
            try:
                dl.load_config()
            except PermissionError:
                pass
            else:
                raise AssertionError('unreadable config must not become an empty successful load')
        try:
            dl.save_config({'bad': object()})
        except TypeError:
            pass
        else:
            raise AssertionError('serialization failure must propagate')
        assert dl.get_config_path().read_bytes() == original
        assert list(dl.get_config_path().parent.iterdir()) == [dl.get_config_path()]
    """)


def test_history_replace_failure_keeps_saved_history(tmp_path):
    _run_child(tmp_path, """
        from src.services import lane_end_times_history as history
        assert history.save_lane_end_times_history([{'メイン': 90000}])
        original = history.get_history_path().read_bytes()
        with patch('os.replace', side_effect=PermissionError('denied')):
            assert history.save_lane_end_times_history([{'メイン': 1}]) is False
        assert history.get_history_path().read_bytes() == original
        assert list(history.get_history_path().parent.iterdir()) == [history.get_history_path()]
    """)
