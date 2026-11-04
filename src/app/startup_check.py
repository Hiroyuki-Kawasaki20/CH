"""bat用の読み取り専用自己診断。GUI起動・設定読込・SPO書込みは行わない。"""

import argparse
import importlib
from pathlib import Path
import sys

from ..models.constants import CONFIG_FILENAME, LOCAL_OUTPUT_DIR
from ..utils.user_paths import get_user_data_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-python", required=True)
    args = parser.parse_args()
    print(f"sys.executable: {sys.executable}")
    print(f"Python: {sys.version}")
    if Path(sys.executable).resolve() != Path(args.expected_python).resolve():
        raise SystemExit("Unexpected Python interpreter; refusing to start.")
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("Python 3.11 is required; prepare your DIG_new environment.")
    for name in ("tkinter", "pandas", "numpy", "openpyxl", "customtkinter"):
        module = importlib.import_module(name)
        print(f"Library: {name} {getattr(module, '__version__', 'available')}")
    from ..services.lane_end_times_history import get_history_path
    from ..services.spo_export import DEFAULT_STAGING_DIR
    print(f"Settings: {get_user_data_dir() / CONFIG_FILENAME}")
    print(f"History: {get_history_path()}")
    print(f"Local output: {LOCAL_OUTPUT_DIR}")
    print(f"Staging: {DEFAULT_STAGING_DIR}")
    print("[OK] Startup diagnostics passed (no production I/O).")


if __name__ == "__main__":
    main()
