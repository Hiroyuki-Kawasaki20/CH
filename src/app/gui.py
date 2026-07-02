# -*- coding: utf-8 -*-
"""
CHかんばんセット — メインGUIアプリケーション

引取作業者が1人のため:
- メイン工程: 1人で入車時間順に処理可能な山
- リリーフ工程: メインで間に合わない山
"""

import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
from pathlib import Path
from datetime import datetime, timedelta
import os
import sys
import json

import pandas as pd
import numpy as np

# パス設定（srcの親ディレクトリをsys.pathに追加）
_SRC_DIR = Path(__file__).resolve().parents[1]
if str(_SRC_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR.parent))

from src.models.constants import (
    DEFAULT_HEIGHT_CAP, DEFAULT_MIXING_KEY,
    BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL,
    PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW, PROC_MAIN_LABEL, PROC_RELIEF_LABEL, PROC_OVERFLOW_LABEL,
    COLOR_MAIN, COLOR_RELIEF, COLOR_OVERFLOW, COLOR_VIOLATION,
    VIRTUAL_YAMA_NO, is_virtual_yama,
)
from src.services.data_loader import (
    load_data, DataManager,
    get_master_path, load_pickup_time_master_xlsx, save_pickup_time_master_xlsx,
    parse_ukeire_ch_excel, load_config, save_config, get_export_dir,
    set_flag_value_to_checkbox_mark, checkbox_mark_to_set_flag_value,
)
from src.services.sorter import (
    run_pipeline, build_all_mountain_details, create_battery_change_mountain,
    compute_basic_groups, compute_mixed_groups, compute_dest_by_mountain,
)
from src.services.process_assigner import (
    compute_proc_details, assign_processes_by_arrival_time,
    compute_proc_summary,
    _time_to_seconds, _seconds_to_hhmm, _to_operational_timeline_secs,
    _calc_work_end_with_breaks, ARRIVAL_BUFFER_SECS,
)
from src.services.scheduler import (
    cluster_by_store,
    _mountain_context,
    insert_virtual_mountain_into_lane,
    aggregate_proc_details_to_mountains,
)
from src.services.exporter import (
    build_spo_export_df, export_spo_xlsx,
    attach_pickup_start_time, export_kanban_xlsx,
    append_to_spo_history,
)
from src.utils.normalizer import _normalize_dest_name, _ZEN2HAN_DIGIT_COLON

# ===== CustomTkinter 設定 =====
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CHかんばんセット — 仕分け・セットボード")
        self.geometry("1500x920")

        # データ読み込み
        df_shipments, df_places = load_data()
        self.data_mgr = DataManager(df_shipments, df_places)

        # フィールド初期化
        self.height_cap = tk.IntVar(value=DEFAULT_HEIGHT_CAP)
        self.mixing_key = tk.StringVar(value=DEFAULT_MIXING_KEY)
        self.selections = []
        self.filtered = pd.DataFrame()
        self.expanded = pd.DataFrame()
        self.group_results = {}
        self.group_details = {}
        self.size1_mixed_summary = None
        self.size1_mixed_details = None
        self.proc_details = pd.DataFrame()
        self.proc_details_display = pd.DataFrame()
        self.proc_summary = pd.DataFrame()
        self.mountain_proc = pd.DataFrame()
        self.mountain_proc_map = {}
        self.mountain_start_times = {}
        self.all_mountain_details = pd.DataFrame()
        self.all_mountain_details_display = pd.DataFrame()
        self.auto_export_csv = True
        self.auto_reload_shipments = True
        self.auto_reload_minute = tk.IntVar(value=15)
        self.auto_reload_minute_str = tk.StringVar(value="15")
        # ===== バッテリー交換フラグ（デフォルトOFF） =====
        self.enable_battery_change = tk.BooleanVar(value=False)
        self._receipt_section_expanded = False
        self._last_auto_reload_success_at = ""
        self._auto_reload_after_id = None
        self.export_dir = str(get_export_dir())
        self.master_data = pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"])
        self.lane_end_times_memory = {}
        self.selected_shift = tk.StringVar(value="1直")
        self.last_run_shift = None
        self.late_relief_warnings = []
        self._route_display_to_internal = {}  # "KVC-B7" -> "KVC" のマッピング
        self._load_auto_reload_settings()

        # UI構築
        self.build_ui()
        self.reapply_treeview_tags()
        self.refresh_routes()
        self.bind("<Return>", lambda e: self.run())
        self.bind("<KP_Enter>", lambda e: self.run())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 入車時間マスタを遅延読込
        self.after(200, self._initial_load_master)
        if self.auto_reload_shipments:
            self._schedule_auto_reload()

    def _load_auto_reload_settings(self):
        """自動再読込の分設定を設定ファイルから読み込む。"""
        try:
            config = load_config()
            minute = int(config.get("auto_reload_minute", 15))
            if minute < 0 or minute > 59:
                minute = 15
        except Exception:
            minute = 15
        self.auto_reload_minute.set(minute)
        self.auto_reload_minute_str.set(f"{minute:02d}")
        # バッテリー交換チェックは「毎回OFF開始」仕様のため、
        # 設定ファイルからは復元しない。

    def _save_auto_reload_settings(self):
        """自動再読込の分設定を設定ファイルへ保存する。"""
        try:
            config = load_config()
            config["auto_reload_minute"] = int(self.auto_reload_minute.get())
            # バッテリー交換チェックは一時操作のため永続化しない。
            save_config(config)
        except Exception:
            pass

    def _on_close(self):
        """終了時に予約済みタイマーを解放して安全に閉じる。"""
        try:
            self._save_master_silent()
        except Exception:
            pass
        try:
            if self._auto_reload_after_id is not None:
                self.after_cancel(self._auto_reload_after_id)
                self._auto_reload_after_id = None
        except Exception:
            pass
        self.destroy()

    def _schedule_auto_reload(self):
        """設定された分の次時刻にCSV再読込を実行するタイマーを予約。"""
        now = datetime.now()
        reload_minute = int(self.auto_reload_minute.get())
        next_run = now.replace(minute=reload_minute, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(hours=1)
        delay_ms = max(1000, int((next_run - now).total_seconds() * 1000))
        self._auto_reload_after_id = self.after(delay_ms, self._run_scheduled_reload)

    def _run_scheduled_reload(self):
        """予約時刻にCSVを自動再読込し、次回予約を設定。"""
        self._auto_reload_after_id = None
        try:
            self.reload_shipments_data(show_message=False)
        finally:
            if self.auto_reload_shipments:
                self._schedule_auto_reload()

    def _on_auto_reload_minute_changed(self, minute_text: str):
        """自動再読込分が変更されたら保存し、次回予約を更新する。"""
        try:
            minute = int(str(minute_text).strip())
            if minute < 0 or minute > 59:
                raise ValueError("minute out of range")
        except Exception:
            minute = 15
        self.auto_reload_minute.set(minute)
        self.auto_reload_minute_str.set(f"{minute:02d}")
        self._save_auto_reload_settings()
        try:
            if self._auto_reload_after_id is not None:
                self.after_cancel(self._auto_reload_after_id)
                self._auto_reload_after_id = None
        except Exception:
            pass
        if self.auto_reload_shipments:
            self._schedule_auto_reload()

    def reapply_treeview_tags(self):
        try:
            self.kb_summary.tag_configure("proc_main", background="#DBEAFE", foreground="#1E3A5F")
            self.kb_summary.tag_configure("proc_relief", background="#FCE7F3", foreground="#831843")
        except Exception:
            pass

    def _update_status(self):
        try:
            now_str = datetime.now().strftime("%H:%M")
            mountain_num = len(self.mountain_proc) if self.mountain_proc is not None and not self.mountain_proc.empty else 0
            p_main = sum(1 for v in self.mountain_proc_map.values() if str(v) == PROC_MAIN)
            p_relief = sum(1 for v in self.mountain_proc_map.values() if str(v) == PROC_RELIEF)
            auto_reload_part = f" | 自動再読込: {self._last_auto_reload_success_at}" if self._last_auto_reload_success_at else ""
            self.status_bar.configure(
                text=f"前回実行: {now_str} | 山数: {mountain_num} | メイン: {p_main}山  リリーフ: {p_relief}山{auto_reload_part}"
            )
        except Exception:
            pass

    def build_ui(self):
        C_BG = "#F5F7FA"
        C_SIDEBAR = "#FFFFFF"
        C_ACCENT = "#4361EE"
        C_ACCENT_HOVER = "#3A56D4"
        C_SUCCESS = "#2EC4B6"
        C_SUCCESS_HOVER = "#25A89C"
        C_DANGER = "#E63946"
        C_DANGER_HOVER = "#CF2F3C"
        C_WARN = "#F4A261"
        C_WARN_HOVER = "#E08C4A"
        C_NEUTRAL = "#8D99AE"
        C_NEUTRAL_HOVER = "#7A8598"
        C_INFO = "#457B9D"
        C_INFO_HOVER = "#3A6B8A"
        C_STATUS = "#2B2D42"
        C_STEP1 = "#4361EE"
        C_STEP2 = "#457B9D"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("Meiryo UI", 10), rowheight=28,
                        background="white", fieldbackground="white", foreground="#2B2D42")
        style.configure("Treeview.Heading", font=("Meiryo UI", 10, "bold"),
                        background="#E8EDF2", foreground="#2B2D42", relief="flat")
        style.map("Treeview.Heading", background=[("active", "#D6DCE5")])
        style.map("Treeview", background=[("selected", "#D0E2F4")], foreground=[("selected", "#1A1A2E")])

        # セットボード専用スタイル（視認性重視）
        style.configure("SetboardLane.Treeview", font=("Meiryo UI", 12), rowheight=34,
                background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#1F2A44")
        style.configure("SetboardLane.Treeview.Heading", font=("Meiryo UI", 12, "bold"),
                background="#D8DEE6", foreground="#10203A", relief="flat")
        style.configure("SetboardDetail.Treeview", font=("Meiryo UI", 13), rowheight=40,
                background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#1F2A44")
        style.configure("SetboardDetail.Treeview.Heading", font=("Meiryo UI", 12, "bold"),
                background="#D8DEE6", foreground="#10203A", relief="flat")

        self.configure(fg_color=C_BG)
        self._tab_font = ctk.CTkFont(family="Meiryo UI", size=15, weight="bold")
        self._label_font = ctk.CTkFont(family="Meiryo UI", size=11)
        self._label_bold = ctk.CTkFont(family="Meiryo UI", size=11, weight="bold")
        self._step_font = ctk.CTkFont(family="Meiryo UI", size=10, weight="bold")
        self._btn_font = ctk.CTkFont(family="Meiryo UI", size=12)
        self._run_font = ctk.CTkFont(family="Meiryo UI", size=14, weight="bold")

        # ステータスバー
        self.status_bar = ctk.CTkLabel(
            self, text="前回実行: なし | 山数: - | メイン: - リリーフ: -",
            fg_color=C_STATUS, text_color="#EDF2F4", font=self._label_font, anchor="w",
        )
        self.status_bar.pack(side="bottom", fill="x", ipady=5)

        # 左ペイン
        left = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=12, width=260)
        left.pack(side="left", fill="both", padx=(8, 4), pady=8)
        left.pack_propagate(False)
        self.left_sidebar = left

        left_top = ctk.CTkFrame(left, fg_color="transparent")
        left_top.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))

        # ① 便名選択
        ctk.CTkLabel(left_top, text="  ① 便名を選ぶ", fg_color=C_STEP1, text_color="white",
                 font=ctk.CTkFont(family="Meiryo UI", size=13, weight="bold"),
                 anchor="w", corner_radius=6, height=30).pack(fill="x", pady=(0, 4))
        route_frame = ctk.CTkFrame(left_top, fg_color="transparent")
        route_frame.pack(fill="x", pady=(0, 6))
        route_sb = tk.Scrollbar(route_frame, orient="vertical")
        self.route_list = tk.Listbox(route_frame, selectmode="extended", exportselection=False,
                                     font=("Meiryo UI", 13), height=8,
                                     bg="white", fg="#2B2D42",
                                     selectbackground=C_ACCENT, selectforeground="white",
                                     relief="flat", highlightthickness=1, highlightcolor="#D6DCE5",
                                     highlightbackground="#D6DCE5", yscrollcommand=route_sb.set)
        route_sb.configure(command=self.route_list.yview)
        self.route_list.pack(side="left", fill="both", expand=True)
        route_sb.pack(side="right", fill="y")
        self.route_list.bind("<<ListboxSelect>>", lambda e: self.refresh_candidates())

        self.summary_mode = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(left_top, text="便番号だけで選択する（受入を省略）",
                        variable=self.summary_mode, command=self._on_summary_mode_changed,
                        font=self._label_font, fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                        ).pack(anchor="w", pady=(2, 6))

        # 受入リスト（折りたたみ可能）
        receipt_header = ctk.CTkFrame(left_top, fg_color="transparent")
        receipt_header.pack(fill="x", pady=(0, 2))
        self.receipt_toggle_btn = ctk.CTkButton(
            receipt_header,
            text="受入（まとめOFF時に選択） ▼",
            command=self._toggle_receipt_section,
            fg_color="transparent",
            text_color=C_NEUTRAL,
            hover_color="#E9EEF7",
            anchor="w",
            height=24,
            corner_radius=6,
            font=self._label_font,
        )
        self.receipt_toggle_btn.pack(side="left", fill="x", expand=True)

        self.receipt_section = ctk.CTkFrame(left_top, fg_color="transparent")
        receipt_frame = ctk.CTkFrame(self.receipt_section, fg_color="transparent")
        receipt_frame.pack(fill="x", pady=(0, 6))
        receipt_sb = tk.Scrollbar(receipt_frame, orient="vertical")
        self.receipt_list = tk.Listbox(receipt_frame, selectmode="extended", exportselection=False,
                                       font=("Meiryo UI", 10), height=3,
                                       bg="white", fg="#2B2D42",
                                       selectbackground=C_ACCENT, selectforeground="white",
                                       relief="flat", highlightthickness=1, highlightcolor="#D6DCE5",
                                       highlightbackground="#D6DCE5", yscrollcommand=receipt_sb.set)
        receipt_sb.configure(command=self.receipt_list.yview)
        self.receipt_list.pack(side="left", fill="both", expand=True)
        receipt_sb.pack(side="right", fill="y")
        self.receipt_list.bind("<<ListboxSelect>>", lambda e: self.refresh_orders_for_receipt())

        # ② オーダー選択
        order_header = ctk.CTkFrame(left_top, fg_color="transparent")
        order_header.pack(fill="x", pady=(6, 4))
        ctk.CTkLabel(order_header, text="  ② オーダーを選ぶ", fg_color=C_STEP2, text_color="white",
                 font=ctk.CTkFont(family="Meiryo UI", size=13, weight="bold"),
                 anchor="w", corner_radius=6, height=30
                     ).pack(side="left", fill="x", expand=True)
        self._order_count_label = ctk.CTkLabel(
            order_header, text="0 件", fg_color=C_INFO, text_color="white",
            font=ctk.CTkFont(family="Meiryo UI", size=10), corner_radius=10, width=46, height=28)
        self._order_count_label.pack(side="right", padx=(4, 0))

        order_frame = ctk.CTkFrame(left_top, fg_color="transparent")
        order_frame.pack(fill="both", expand=True, pady=(0, 6))
        order_sb = tk.Scrollbar(order_frame, orient="vertical")
        self.order_list = tk.Listbox(order_frame, selectmode="extended", exportselection=False,
                                     font=("Meiryo UI", 13), bg="white", fg="#2B2D42",
                                     selectbackground=C_ACCENT, selectforeground="white",
                                     relief="flat", highlightthickness=1, highlightcolor="#D6DCE5",
                                     highlightbackground="#D6DCE5", yscrollcommand=order_sb.set)
        order_sb.configure(command=self.order_list.yview)
        self.order_list.pack(side="left", fill="both", expand=True)
        order_sb.pack(side="right", fill="y")
        self.order_list.bind("<Double-Button-1>", lambda e: self.add_selection())
        self._on_summary_mode_changed()

        # ③ バッテリー交換オプション
        battery_frame = ctk.CTkFrame(left_top, fg_color="transparent")
        battery_frame.pack(fill="x", pady=(6, 0))
        ctk.CTkCheckBox(
            battery_frame,
            text="🔋 バッテリー交換を実施（メイン工程に差し込む）",
            variable=self.enable_battery_change,
            command=self._on_battery_change_toggled,
            font=self._label_bold,
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER,
        ).pack(anchor="w", pady=(0, 6))

        shift_frame = ctk.CTkFrame(left_top, fg_color="transparent")
        shift_frame.pack(fill="x", pady=(2, 6))
        ctk.CTkLabel(shift_frame, text="直選択", font=self._label_bold).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            shift_frame,
            text="1直",
            variable=self.selected_shift,
            value="1直",
            font=self._label_font,
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            shift_frame,
            text="2直",
            variable=self.selected_shift,
            value="2直",
            font=self._label_font,
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER,
        ).pack(side="left")

        # 下部エリア（実行/操作ボタン）
        left_bottom = ctk.CTkFrame(left, fg_color="transparent", height=120)
        left_bottom.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        left_bottom.pack_propagate(False)

        self.progress_bar = ctk.CTkProgressBar(left_bottom, mode="indeterminate", progress_color=C_SUCCESS)
        ctk.CTkButton(left_bottom, text="▶  仕分け＆セット実行", command=self.run,
                      fg_color=C_SUCCESS, hover_color=C_SUCCESS_HOVER,
                      font=self._run_font, height=48, corner_radius=10,
                      ).pack(side="bottom", fill="x", pady=(6, 0))

        btns = ctk.CTkFrame(left_bottom, fg_color="transparent")
        btns.pack(side="bottom", fill="x", pady=(4, 0))
        auto_reload_cfg = ctk.CTkFrame(left_bottom, fg_color="transparent")
        auto_reload_cfg.pack(side="bottom", fill="x", pady=(2, 2))
        ctk.CTkLabel(auto_reload_cfg, text="自動再読込", font=self._label_font,
                     text_color=C_NEUTRAL).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(auto_reload_cfg, text="毎時", font=self._label_font,
                     text_color=C_NEUTRAL).pack(side="left")
        ctk.CTkOptionMenu(
            auto_reload_cfg,
            values=[f"{i:02d}" for i in range(60)],
            variable=self.auto_reload_minute_str,
            command=self._on_auto_reload_minute_changed,
            width=76,
            height=28,
            font=self._btn_font,
            fg_color=C_INFO,
            button_color=C_INFO,
            button_hover_color=C_INFO_HOVER,
            dropdown_font=self._label_font,
        ).pack(side="left", padx=4)
        ctk.CTkLabel(auto_reload_cfg, text="分", font=self._label_font,
                     text_color=C_NEUTRAL).pack(side="left", padx=(2, 0))
        ctk.CTkButton(btns, text="CSV再読込", command=self.reload_shipments_data, width=88,
                  fg_color=C_WARN, hover_color=C_WARN_HOVER, font=self._btn_font,
                  corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="引継クリア", command=self.clear_lane_time_carryover, width=86,
              fg_color=C_NEUTRAL, hover_color=C_NEUTRAL_HOVER, font=self._btn_font,
              corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="追加", command=self.add_selection, width=60,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER, font=self._btn_font,
                      corner_radius=8).pack(side="left", padx=2)

        # 右ペイン: タブ
        self.notebook = ctk.CTkTabview(self, corner_radius=12,
                                        fg_color="#FFFFFF",
                                        segmented_button_fg_color="#D4D9E8",
                                        segmented_button_selected_color=C_ACCENT,
                                        segmented_button_selected_hover_color=C_ACCENT_HOVER,
                                        segmented_button_unselected_color="#D4D9E8",
                        segmented_button_unselected_hover_color="#BDC4D6",
                        command=self._on_main_tab_changed)
        self.notebook.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        for tab_name in ["セットボード", "入車時間設定", "選択管理"]:
            self.notebook.add(tab_name)
        self.notebook._segmented_button.configure(
            font=self._tab_font,
            height=40,
            text_color="#2B2D42",
            text_color_disabled="#8D99AE",
        )

        # ===== セットボードタブ =====
        tab_sb = self.notebook.tab("セットボード")
        self._build_setboard_tab(tab_sb)

        # ===== 入車時間設定タブ =====
        tab_master = self.notebook.tab("入車時間設定")
        self._build_master_tab(tab_master)

        # ===== 選択管理タブ =====
        tab_selection = self.notebook.tab("選択管理")
        self._build_selection_tab(tab_selection)

        # 初期表示はセットボード想定: 左ペインを隠してメイン領域を最大化
        self.after(0, self._on_main_tab_changed)

    def _on_main_tab_changed(self, *_):
        """タブ切替時に左ペイン表示を切替える。"""
        try:
            current_tab = str(self.notebook.get())
        except Exception:
            current_tab = ""
        self._set_selection_layout_mode(current_tab == "選択管理")

    def _set_selection_layout_mode(self, show_left_sidebar: bool):
        """選択管理タブでは左ペインを表示、他タブでは非表示にする。"""
        if show_left_sidebar:
            # 画面幅の約半分を左ペインへ割り当て
            win_w = int(self.winfo_width()) if self.winfo_width() > 0 else 1500
            sidebar_w = max(480, int(win_w * 0.46))
            self.left_sidebar.configure(width=sidebar_w)

            self.left_sidebar.pack_forget()
            self.notebook.pack_forget()
            self.left_sidebar.pack(side="left", fill="both", padx=(8, 4), pady=8)
            self.notebook.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)
        else:
            self.left_sidebar.pack_forget()
            self.notebook.pack_forget()
            self.notebook.pack(side="left", fill="both", expand=True, padx=(8, 8), pady=8)

    def _build_setboard_tab(self, tab):
        """セットボード: メイン/リリーフ/あふれの3レーン表示"""
        header_frame = ctk.CTkFrame(tab, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(header_frame, text="📋 セットボード（メイン / リリーフ / あふれ）",
                     font=ctk.CTkFont(family="Meiryo UI", size=14, weight="bold"),
                     anchor="w").pack(side="left")

        lanes_frame = ctk.CTkFrame(tab, fg_color="transparent")
        lanes_frame.pack(fill="both", expand=True, padx=10, pady=5)
        lanes_frame.columnconfigure(0, weight=1)
        lanes_frame.columnconfigure(1, weight=1)
        lanes_frame.columnconfigure(2, weight=1)

        # メインレーン
        main_frame = ctk.CTkFrame(lanes_frame, fg_color=COLOR_MAIN, corner_radius=10)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(main_frame, text="1工程",
                     font=ctk.CTkFont(family="Meiryo UI", size=13, weight="bold"),
                     text_color="#1E3A5F").pack(pady=(8, 4))
        self._sb_lane_columns = (
            "区分", "開始時間", "納入先", "ストア", "オーダー", "引取工数",
            "受入"
        )
        self.sb_main_tree = ttk.Treeview(
            main_frame,
            columns=self._sb_lane_columns,
            show="headings", height=18, style="SetboardLane.Treeview")
        for c in self.sb_main_tree["columns"]:
            self.sb_main_tree.heading(c, text=c)
            if c == "区分":
                w = 52
            elif c == "納入先":
                w = 140
            elif c == "ストア":
                w = 120
            elif c == "オーダー":
                w = 130
            elif c == "受入":
                w = 76
            elif c == "引取工数":
                w = 86
            elif c == "開始時間":
                w = 92
            else:
                w = 90
            self.sb_main_tree.column(c, width=w, anchor="center")
        self.sb_main_tree.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.sb_main_tree.tag_configure("mtn_even_summary", background="#D6E7FB", foreground="#0F274A")
        self.sb_main_tree.tag_configure("mtn_even_detail", background="#F4F8FF", foreground="#1F2A44")
        self.sb_main_tree.tag_configure("mtn_even_detail_alt", background="#E9F1FC", foreground="#1F2A44")
        self.sb_main_tree.tag_configure("mtn_odd_summary", background="#C7DCF5", foreground="#0F274A")
        self.sb_main_tree.tag_configure("mtn_odd_detail", background="#EAF3FF", foreground="#1F2A44")
        self.sb_main_tree.tag_configure("mtn_odd_detail_alt", background="#DCEBFF", foreground="#1F2A44")
        self.sb_main_tree.tag_configure("detail_break_main", background="#FFF3C4", foreground="#1F2A44")
        self.sb_main_tree.tag_configure("mtn_even_summary_delay", background="#D6E7FB", foreground="#C62828")
        self.sb_main_tree.tag_configure("mtn_odd_summary_delay", background="#C7DCF5", foreground="#C62828")
        self.sb_main_tree.tag_configure("mtn_overflow_summary", background="#FFD6CC", foreground="#8C1D18")
        self.sb_main_tree.tag_configure("mtn_overflow_detail", background="#FFF2EE", foreground="#5A1E1A")
        self.sb_main_tree.tag_configure("mountain_sep", background="#B8CCE6", foreground="#B8CCE6")
        self.sb_main_tree.bind("<<TreeviewSelect>>", lambda e: self._on_setboard_select("main"))

        # リリーフレーン
        relief_frame = ctk.CTkFrame(lanes_frame, fg_color=COLOR_RELIEF, corner_radius=10)
        relief_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(relief_frame, text="リリーフ工程",
                     font=ctk.CTkFont(family="Meiryo UI", size=13, weight="bold"),
                     text_color="#831843").pack(pady=(8, 4))
        self.sb_relief_tree = ttk.Treeview(
            relief_frame,
            columns=self._sb_lane_columns,
            show="headings", height=18, style="SetboardLane.Treeview")
        for c in self.sb_relief_tree["columns"]:
            self.sb_relief_tree.heading(c, text=c)
            if c == "区分":
                w = 52
            elif c == "納入先":
                w = 140
            elif c == "ストア":
                w = 120
            elif c == "オーダー":
                w = 130
            elif c == "受入":
                w = 76
            elif c == "引取工数":
                w = 86
            elif c == "開始時間":
                w = 92
            else:
                w = 90
            self.sb_relief_tree.column(c, width=w, anchor="center")
        self.sb_relief_tree.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.sb_relief_tree.tag_configure("mtn_even_summary", background="#F7DCEB", foreground="#5E173D")
        self.sb_relief_tree.tag_configure("mtn_even_detail", background="#FFF7FC", foreground="#3F1E33")
        self.sb_relief_tree.tag_configure("mtn_even_detail_alt", background="#FCEEF6", foreground="#3F1E33")
        self.sb_relief_tree.tag_configure("mtn_odd_summary", background="#F0CFE1", foreground="#5E173D")
        self.sb_relief_tree.tag_configure("mtn_odd_detail", background="#FAE9F3", foreground="#3F1E33")
        self.sb_relief_tree.tag_configure("mtn_odd_detail_alt", background="#F6DFEC", foreground="#3F1E33")
        self.sb_relief_tree.tag_configure("detail_break_relief", background="#FFF3C4", foreground="#3F1E33")
        self.sb_relief_tree.tag_configure("mtn_even_summary_delay", background="#F7DCEB", foreground="#C62828")
        self.sb_relief_tree.tag_configure("mtn_odd_summary_delay", background="#F0CFE1", foreground="#C62828")
        self.sb_relief_tree.tag_configure("mtn_overflow_summary", background="#FFD6CC", foreground="#8C1D18")
        self.sb_relief_tree.tag_configure("mtn_overflow_detail", background="#FFF2EE", foreground="#5A1E1A")
        self.sb_relief_tree.tag_configure("mountain_sep", background="#E4CFE0", foreground="#E4CFE0")
        self.sb_relief_tree.bind("<<TreeviewSelect>>", lambda e: self._on_setboard_select("relief"))

        # あふれレーン
        overflow_frame = ctk.CTkFrame(lanes_frame, fg_color=COLOR_OVERFLOW, corner_radius=10)
        overflow_frame.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(overflow_frame, text="あふれ",
                     font=ctk.CTkFont(family="Meiryo UI", size=13, weight="bold"),
                     text_color="#7C4A00").pack(pady=(8, 4))
        self.sb_overflow_tree = ttk.Treeview(
            overflow_frame,
            columns=self._sb_lane_columns,
            show="headings", height=18, style="SetboardLane.Treeview")
        for c in self.sb_overflow_tree["columns"]:
            self.sb_overflow_tree.heading(c, text=c)
            if c == "区分":
                w = 52
            elif c == "納入先":
                w = 140
            elif c == "ストア":
                w = 120
            elif c == "オーダー":
                w = 130
            elif c == "受入":
                w = 76
            elif c == "引取工数":
                w = 86
            elif c == "開始時間":
                w = 92
            else:
                w = 90
            self.sb_overflow_tree.column(c, width=w, anchor="center")
        self.sb_overflow_tree.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.sb_overflow_tree.tag_configure("mtn_even_summary", background="#FFE0B2", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("mtn_even_detail", background="#FFF8E8", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("mtn_even_detail_alt", background="#FFF0D0", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("mtn_odd_summary", background="#FFD180", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("mtn_odd_detail", background="#FFF4DC", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("mtn_odd_detail_alt", background="#FFECC0", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("detail_break_overflow", background="#FFF3C4", foreground="#4E2A00")
        self.sb_overflow_tree.tag_configure("mtn_overflow_summary", background="#FFD6CC", foreground="#8C1D18")
        self.sb_overflow_tree.tag_configure("mtn_overflow_detail", background="#FFF2EE", foreground="#5A1E1A")
        self.sb_overflow_tree.tag_configure("mountain_sep", background="#F5D5A0", foreground="#F5D5A0")
        self.sb_overflow_tree.bind("<<TreeviewSelect>>", lambda e: self._on_setboard_select("overflow"))

    def _build_master_tab(self, tab):
        """入車時間設定タブ"""
        C_DANGER = "#E63946"
        C_DANGER_HOVER = "#CF2F3C"
        C_NEUTRAL = "#8D99AE"
        C_NEUTRAL_HOVER = "#7A8598"

        master_btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        master_btn_frame.pack(fill="x", padx=6, pady=6)
        ctk.CTkButton(master_btn_frame, text="マスタ保存", command=self.save_master, width=100,
                      font=self._btn_font, corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(master_btn_frame, text="行追加", command=self.add_master_row, width=80,
                      font=self._btn_font, corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(master_btn_frame, text="選択行削除", command=self.delete_master_row, width=100,
                      fg_color=C_DANGER, hover_color=C_DANGER_HOVER,
                      font=self._btn_font, corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(master_btn_frame, text="全クリア", command=self.clear_master, width=80,
                      fg_color=C_NEUTRAL, hover_color=C_NEUTRAL_HOVER,
                      font=self._btn_font, corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(master_btn_frame, text="全受入CHからインポート", command=self.import_from_ukeire_sheet,
                  fg_color="#2A9D8F", hover_color="#238478", text_color="white", width=190,
                  font=self._btn_font, corner_radius=8).pack(side="left", padx=2)
        ctk.CTkButton(master_btn_frame, text="入車時間マスタ.xlsx から直接取込", command=self.import_from_master_xlsx,
              fg_color="#1D6F42", hover_color="#165C37", text_color="white", width=250,
              font=self._btn_font, corner_radius=8).pack(side="left", padx=2)

        self.master_tree = ttk.Treeview(
            tab, columns=("OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"), show="headings", height=20)
        for c in self.master_tree["columns"]:
            self.master_tree.heading(c, text=c)
            if c == "OData_納入先":
                w = 220
            elif c == "セットありフラグ":
                w = 120
            else:
                w = 120
            self.master_tree.column(c, width=w, anchor="w")
        self.master_tree.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.master_tree.bind("<Button-1>", self.on_master_tree_click)
        self.master_tree.bind("<Double-1>", self.edit_master_row)

    def _build_selection_tab(self, tab):
        """選択管理タブ: 選択一覧の確認/削除/クリアを行う。"""
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(
            top,
            text="選択一覧（Deleteキーで削除）",
            font=ctk.CTkFont(family="Meiryo UI", size=13, weight="bold"),
            anchor="w",
        ).pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkButton(
            actions,
            text="選択削除",
            command=self.delete_selection,
            width=90,
            fg_color="#E63946",
            hover_color="#CF2F3C",
            font=self._btn_font,
            corner_radius=8,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="全クリア",
            command=self.clear_selection,
            width=90,
            fg_color="#8D99AE",
            hover_color="#7A8598",
            font=self._btn_font,
            corner_radius=8,
        ).pack(side="left", padx=(0, 4))

        list_wrap = ctk.CTkFrame(tab, fg_color="transparent")
        list_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        sel_sb = tk.Scrollbar(list_wrap, orient="vertical")
        self.sel_tree = ttk.Treeview(
            list_wrap,
            columns=("便名", "受入", "オーダー"),
            show="headings",
            height=18,
            yscrollcommand=sel_sb.set,
        )
        sel_sb.configure(command=self.sel_tree.yview)
        for c in ("便名", "受入", "オーダー"):
            self.sel_tree.heading(c, text=c)
            self.sel_tree.column(c, width=260, anchor="w")
        self.sel_tree.pack(side="left", fill="both", expand=True)
        sel_sb.pack(side="right", fill="y")
        self.sel_tree.bind("<Delete>", lambda e: self.delete_selection())

    # ===== 候補更新 =====
    def refresh_routes(self):
        self.route_list.delete(0, "end")
        self._route_display_to_internal.clear()
        routes = self.data_mgr.get_routes()
        display_routes = []

        for r in routes:
            if r == "KVC" and self.master_data is not None and not self.master_data.empty:
                # KVCの場合、master_data から "KVC-B7", "KVC-B3" を抽出
                kvc_vendors = sorted(
                    self.master_data[self.master_data["OData_納入先"].str.startswith("KVC-")]["OData_納入先"].unique().tolist()
                )
                for vendor in kvc_vendors:
                    display_routes.append(vendor)
                    # "KVC-B7" -> {"route": "KVC", "ukeire": "B7"}
                    ukeire = vendor.replace("KVC-", "").strip() if "-" in vendor else None
                    self._route_display_to_internal[vendor] = {"route": "KVC", "ukeire": ukeire}
            else:
                display_routes.append(r)
                self._route_display_to_internal[r] = {"route": r, "ukeire": None}  # 辞書化

        for r in display_routes:
            self.route_list.insert("end", r)
        self.refresh_candidates()


    def _selection_exists_in_data(self, sel: dict) -> bool:
        """選択済みレコードが再読込後データにも存在するか判定。"""
        route = str(sel.get("便名", "")).strip()
        receipt = str(sel.get("受入", "")).strip()
        order = str(sel.get("オーダー", "")).strip()
        if not route or not receipt or not order:
            return False
        mapping = self._route_display_to_internal.get(route, {"route": route, "ukeire": None})
        if isinstance(mapping, str):  # 互換性: 古い形式
            mapping = {"route": mapping, "ukeire": None}
        internal_route = mapping["route"]
        ukeire = mapping.get("ukeire")
        
        if internal_route not in set(self.data_mgr.get_routes()):
            return False
        orders = self.data_mgr.get_orders_for_route_receipt(internal_route, receipt, ukeire=ukeire)
        return order in set(orders)

    def reload_shipments_data(self, show_message: bool = True):
        """出荷情報CSV/出荷場一覧CSVを再読込して候補を最新化。"""
        try:
            old_count = len(self.selections)
            df_shipments, df_places = load_data()
            self.data_mgr = DataManager(df_shipments, df_places)

            # 既存選択は可能な限り維持し、現データにない項目のみ除外
            self.selections = [s for s in self.selections if self._selection_exists_in_data(s)]
            self.refresh_selection_tree()
            self.refresh_routes()

            removed = old_count - len(self.selections)
            if show_message:
                msg = "最新のCSVを再読込しました。"
                if removed > 0:
                    msg += f"\n現在データに存在しない選択を {removed} 件除外しました。"
                messagebox.showinfo("CSV再読込", msg)
            else:
                self._last_auto_reload_success_at = datetime.now().strftime("%H:%M")
                self._update_status()
        except Exception as e:
            if show_message:
                messagebox.showerror("CSV再読込エラー", str(e))
            else:
                print(f"[自動再読込エラー] {e}")

    def refresh_candidates(self):
        routes = [self.route_list.get(i) for i in self.route_list.curselection()] or []
        self.receipt_list.delete(0, "end")
        self.order_list.delete(0, "end")
        if not routes:
            try:
                self._order_count_label.configure(text="0 件")
            except Exception:
                pass
            return
        # 表示名から route/ukeire を抽出
        routes_with_ukeire = []
        for r in routes:
            mapping = self._route_display_to_internal.get(r, {"route": r, "ukeire": None})
            if isinstance(mapping, str):  # 互換性
                mapping = {"route": mapping, "ukeire": None}
            routes_with_ukeire.append(mapping)
        
        if not self.summary_mode.get():
            receipts_all = set()
            for route_info in routes_with_ukeire:
                receipts_all.update(self.data_mgr.get_receipts_for_route(route_info["route"], ukeire=route_info.get("ukeire")))
            for rc in sorted(receipts_all):
                self.receipt_list.insert("end", rc)
        orders_all = set()
        if self.summary_mode.get():
            for route_info in routes_with_ukeire:
                orders_all.update(self.data_mgr.get_orders_for_route(route_info["route"], ukeire=route_info.get("ukeire")))
        else:
            receipts = [self.receipt_list.get(i) for i in self.receipt_list.curselection()]
            if not receipts:
                receipts = [self.receipt_list.get(i) for i in range(self.receipt_list.size())]
            for route_info in routes_with_ukeire:
                for rc in receipts:
                    orders_all.update(self.data_mgr.get_orders_for_route_receipt(route_info["route"], rc, ukeire=route_info.get("ukeire")))
        for od in sorted(orders_all, reverse=True):
            self.order_list.insert("end", od)
        try:
            self._order_count_label.configure(text=f"{len(orders_all)} 件")
        except Exception:
            pass

    def _set_receipt_section_expanded(self, expanded: bool):
        self._receipt_section_expanded = bool(expanded)
        if self._receipt_section_expanded:
            if not self.receipt_section.winfo_ismapped():
                self.receipt_section.pack(fill="x", pady=(0, 6))
            self.receipt_toggle_btn.configure(text="受入（まとめOFF時に選択） ▲")
        else:
            if self.receipt_section.winfo_ismapped():
                self.receipt_section.pack_forget()
            self.receipt_toggle_btn.configure(text="受入（まとめOFF時に選択） ▼")

    def _toggle_receipt_section(self):
        if self.summary_mode.get():
            return
        self._set_receipt_section_expanded(not self._receipt_section_expanded)

    def _on_summary_mode_changed(self):
        if self.summary_mode.get():
            self._set_receipt_section_expanded(False)
            self.receipt_toggle_btn.configure(state="disabled")
        else:
            self._set_receipt_section_expanded(True)
            self.receipt_toggle_btn.configure(state="normal")
        # build_ui 中に呼ばれても安全なように、候補更新は部品初期化後のみ実行
        if hasattr(self, "order_list") and hasattr(self, "route_list") and hasattr(self, "receipt_list"):
            self.refresh_candidates()

    def _on_battery_change_toggled(self):
        """バッテリー交換チェックボックスが変更された時の処理。
        現在は設定ファイルへの保存のみ。"""
        try:
            self._save_auto_reload_settings()
        except Exception as e:
            print(f"[warning] Failed to save battery change setting: {e}")

    def refresh_orders_for_receipt(self):
        if self.summary_mode.get():
            return
        routes = [self.route_list.get(i) for i in self.route_list.curselection()] or []
        if not routes:
            return
        receipts = [self.receipt_list.get(i) for i in self.receipt_list.curselection()]
        if not receipts:
            return
        self.order_list.delete(0, "end")
        # 表示名から route/ukeire を抽出
        routes_with_ukeire = []
        for r in routes:
            mapping = self._route_display_to_internal.get(r, {"route": r, "ukeire": None})
            if isinstance(mapping, str):  # 互換性
                mapping = {"route": mapping, "ukeire": None}
            routes_with_ukeire.append(mapping)
        
        orders_all = set()
        for route_info in routes_with_ukeire:
            for rc in receipts:
                orders_all.update(self.data_mgr.get_orders_for_route_receipt(route_info["route"], rc, ukeire=route_info.get("ukeire")))
        for od in sorted(orders_all, reverse=True):
            self.order_list.insert("end", od)
        try:
            self._order_count_label.configure(text=f"{len(orders_all)} 件")
        except Exception:
            pass

    # ===== 選択操作 =====
    def add_selection(self):
        routes = [self.route_list.get(i) for i in self.route_list.curselection()]
        orders = [self.order_list.get(i) for i in self.order_list.curselection()]
        if not routes or not orders:
            messagebox.showinfo("追加", "便名とオーダーを選択してください。")
            return
        new_items = []
        if self.summary_mode.get():
            for display_route in routes:
                mapping = self._route_display_to_internal.get(display_route, {"route": display_route, "ukeire": None})
                if isinstance(mapping, str):  # 互換性
                    mapping = {"route": mapping, "ukeire": None}
                internal_route = mapping["route"]
                for od in orders:
                    receipts = self.data_mgr.get_receipts_for_route_order(internal_route, od, ukeire=mapping.get("ukeire"))
                    for rc in receipts:
                        new_items.append({"便名": display_route, "受入": rc, "オーダー": od})
        else:
            receipts = [self.receipt_list.get(i) for i in self.receipt_list.curselection()]
            if not receipts:
                messagebox.showinfo("追加", "受入を選択してください。")
                return
            for display_route in routes:
                mapping = self._route_display_to_internal.get(display_route, {"route": display_route, "ukeire": None})
                if isinstance(mapping, str):  # 互換性
                    mapping = {"route": mapping, "ukeire": None}
                internal_route = mapping["route"]
                for rc in receipts:
                    for od in orders:
                        new_items.append({"便名": display_route, "受入": rc, "オーダー": od})
        uniq = {(s["便名"], s["受入"], s["オーダー"]) for s in (self.selections + new_items)}
        self.selections = [{"便名": a, "受入": b, "オーダー": c} for (a, b, c) in sorted(uniq)]
        self.refresh_selection_tree()

    def delete_selection(self):
        sel_iids = list(self.sel_tree.selection())
        if not sel_iids:
            messagebox.showinfo("削除", "選択一覧で削除対象を選んでください。")
            return
        keys_to_remove = set()
        for iid in sel_iids:
            vals = self.sel_tree.item(iid, "values")
            if len(vals) >= 3:
                keys_to_remove.add((str(vals[0]).strip(), str(vals[1]).strip(), str(vals[2]).strip()))
        self.selections = [
            s for s in self.selections
            if (s["便名"].strip(), s["受入"].strip(), s["オーダー"].strip()) not in keys_to_remove
        ]
        for iid in sel_iids:
            try:
                self.sel_tree.delete(iid)
            except Exception:
                pass

    def clear_selection(self):
        self.selections = []
        self.refresh_selection_tree()

    def clear_lane_time_carryover(self):
        self.lane_end_times_memory = {}
        self.last_run_shift = None
        messagebox.showinfo("引継クリア", "工程別の引き継ぎ時刻をクリアしました。次回は初回動作になります。")

    def refresh_selection_tree(self):
        for iid in self.sel_tree.get_children():
            self.sel_tree.delete(iid)
        for s in self.selections:
            a, b, c = s["便名"].strip(), s["受入"].strip(), s["オーダー"].strip()
            self.sel_tree.insert("", "end", iid=f"{a}|{b}|{c}", values=(a, b, c))

    # ===== 実行 =====
    def run(self):
        if not self.selections:
            messagebox.showinfo("実行", "選択が空です。便名・受入・オーダーを追加してください。")
            return
        current_shift = str(self.selected_shift.get()).strip() or "1直"
        use_previous_lane_end_times = bool(self.last_run_shift == current_shift)
        lane_end_times_backup = dict(self.lane_end_times_memory)
        previous_lane_end_times = self.lane_end_times_memory if use_previous_lane_end_times else {}
        self.progress_bar.pack(fill="x", pady=(0, 4))
        self.progress_bar.start()
        self.title("実行中... CHかんばんセット")
        self.update_idletasks()
        try:
            # 便名を内部名に変換（KVC-B7 -> KVC など）
            converted_selections = []
            for s in self.selections:
                display_route = s["便名"]
                mapping = self._route_display_to_internal.get(display_route, {"route": display_route, "ukeire": None})
                if isinstance(mapping, str):  # 互換性
                    mapping = {"route": mapping, "ukeire": None}
                internal_route = mapping["route"]
                ukeire = mapping.get("ukeire")
                converted_selections.append({
                    "便名": internal_route,
                    "受入": s["受入"],
                    "オーダー": s["オーダー"],
                    "ukeire": ukeire,
                })
            
            filtered, expanded, group_results, group_details, s1_summary, s1_details, _lane_end_times = run_pipeline(
                self.data_mgr, converted_selections, self.height_cap.get(), self.mixing_key.get(),
                master_df=self.master_data,
                previous_lane_end_times=previous_lane_end_times,
                return_lane_end_times=True,
            )
        except Exception as e:
            self.progress_bar.stop()
            self.progress_bar.pack_forget()
            self.title("CHかんばんセット — 仕分け・セットボード")
            messagebox.showerror("実行エラー", str(e))
            return
        self.filtered = filtered
        self.expanded = expanded
        self.group_results = group_results
        self.group_details = group_details
        self.size1_mixed_summary = s1_summary
        self.size1_mixed_details = s1_details
        self.lane_end_times_memory = dict(previous_lane_end_times)

        # 工程割当
        assignment_ok = self.recompute_process_assignment()
        if not assignment_ok:
            self.lane_end_times_memory = lane_end_times_backup
            self.progress_bar.stop()
            self.progress_bar.pack_forget()
            self.title("CHかんばんセット — 仕分け・セットボード")
            return
        self.last_run_shift = current_shift

        # 表示はセットボード中心（不要タブは非表示）
        self.update_setboard_views()

        # SPO出力
        try:
            if self.auto_export_csv:
                self._auto_export_spo()
        except Exception as e:
            messagebox.showwarning("Excel出力", f"SPO用Excel出力でエラー: {e}")

        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.title("CHかんばんセット — 仕分け・セットボード")
        self.notebook.set("セットボード")
        self._on_main_tab_changed()
        self._update_status()
        self._show_late_relief_warning_popup()
        messagebox.showinfo("完了", "仕分け＆セット完了。セットボードで結果をご確認ください。")
        # バッテリー交換は「その日だけ使う」運用のため、
        # 出力完了後に自動でOFFへ戻す。
        self.enable_battery_change.set(False)

    def recompute_process_assignment(self):
        """工程割当: メイン/リリーフの2工程に振り分け"""
        try:
            self.late_relief_warnings = []
            self.all_mountain_details = build_all_mountain_details(
                self.group_details, self.size1_mixed_details
            )
            if self.all_mountain_details is not None and not self.all_mountain_details.empty:
                # GUI表示用は束ね前の展開明細を保持する。
                self.all_mountain_details_display = self.all_mountain_details.copy()
                # 【作業1】初回割付時に仮想山(-1)は混ぜない（この段階では-1を追加しない）
                self.proc_details_display = compute_proc_details(self.all_mountain_details_display)

                # 同一ストア内の異種HINBAN同梱を1パレットへ束ねる（エンジン投入前）。
                # DataFrame->list[dict]->DataFrame 変換時は元列順を保持する。
                base_cols = list(self.all_mountain_details.columns)
                rows = self.all_mountain_details.to_dict(orient="records")
                rows = cluster_by_store(rows)
                clustered_df = pd.DataFrame(rows)
                ordered_cols = [c for c in base_cols if c in clustered_df.columns]
                extra_cols = [c for c in clustered_df.columns if c not in ordered_cols]
                self.all_mountain_details = clustered_df.loc[:, ordered_cols + extra_cols].copy()
                # 【作業1】初回割付時に仮想山(-1)は混ぜない（この段階では-1を追加しない）
                self.proc_details = compute_proc_details(self.all_mountain_details)
            else:
                self.proc_details = compute_proc_details(self.size1_mixed_details) if (
                    self.size1_mixed_details is not None and not self.size1_mixed_details.empty
                ) else pd.DataFrame()
                self.all_mountain_details_display = self.all_mountain_details.copy()
                self.proc_details_display = self.proc_details.copy()

            # 入車時間マスタベースで工程割当
            # 画面上で編集中（未保存）の値を優先して使用する。
            master_df = self._collect_master_from_tree()
            if master_df.empty:
                try:
                    master_path = get_master_path()
                    if master_path.exists():
                        master_df = load_pickup_time_master_xlsx(master_path)
                except Exception as e:
                    print(f"入車時間マスタ読み込みエラー: {e}")

            if not master_df.empty:
                self.mountain_proc, lane_end_times = assign_processes_by_arrival_time(
                    self.proc_details,
                    master_df,
                    previous_lane_end_times=self.lane_end_times_memory,
                    return_lane_end_times=True,
                )
                self.lane_end_times_memory = dict(lane_end_times or {})
                self.late_relief_warnings = self._collect_late_relief_warnings(master_df)
                if "実開始時間" in self.mountain_proc.columns:
                    self.mountain_start_times = dict(zip(
                        self.mountain_proc["山通番"].astype(int),
                        self.mountain_proc["実開始時間"].astype(str)
                    ))
                else:
                    self.mountain_start_times = {}
            else:
                yamas = sorted(self.proc_details["山通番"].unique()) if not self.proc_details.empty else []
                self.mountain_proc = pd.DataFrame({
                    "山通番": yamas,
                    "山工程": [PROC_MAIN] * len(yamas),
                    "実開始時間": [""] * len(yamas),
                        "照合追加180秒": [False] * len(yamas),
                })
                self.lane_end_times_memory = {PROC_MAIN: 0, PROC_RELIEF: 0, PROC_OVERFLOW: 0}
                self.mountain_start_times = {}

            self.mountain_proc_map = dict(zip(self.mountain_proc["山通番"], self.mountain_proc["山工程"]))

            # [調査用] バッテリー OFF時の mountain_start_times を出力（ON時の5-5aと比較するため）
            if not self.enable_battery_change.get():
                print(
                    "[BASELINE] mountain_start_times (OFF時): "
                    f"{dict(sorted(self.mountain_start_times.items()))}"
                )

            # ===== ステップ5-1/5-2（準備のみ） =====
            # 5-1: 実行ゲート。チェックがOFFなら統合ブロックには入らない。
            # 5-2: メイン/リリーフの山リストと3つのmapを準備する（まだ入口関数は呼ばない）。
            self.virtual_insert_context = None
            self.virtual_insert_result = None
            if self.enable_battery_change.get():
                if self.proc_details is not None and not self.proc_details.empty and self.mountain_proc is not None and not self.mountain_proc.empty:
                    # 既存スケジューラと同じ計算経路を再利用して、山ごとの工数/締切/開始情報を取得する。
                    mountain_info, _prev_floor_map, work_map, deadline_map = _mountain_context(self.proc_details, master_df)
                    start_floor_map = {
                        int(m.get("山通番", 0)): int(m.get("開始時間_秒", 0) or 0)
                        for m in mountain_info
                    }

                    # 現在の工程割当（山単位）から、明細行をメイン/リリーフに分ける。
                    main_yamas = set(
                        self.mountain_proc[
                            self.mountain_proc["山工程"].astype(str) == PROC_MAIN
                        ]["山通番"].astype(int).tolist()
                    )
                    relief_yamas = set(
                        self.mountain_proc[
                            self.mountain_proc["山工程"].astype(str) == PROC_RELIEF
                        ]["山通番"].astype(int).tolist()
                    )
                    
                    # 【案2実装】明細を山ごとに集約してからスケジューラに渡す
                    # これにより、schedule_rows内での山の重複を防ぎ、
                    # 後勝ち上書きでの時刻ずれを回避する。
                    aggregated_rows = aggregate_proc_details_to_mountains(
                        self.proc_details,
                        main_yamas | relief_yamas,
                        start_time_map=self.mountain_start_times,
                    )
                    main_lane_rows = [r for r in aggregated_rows if int(r.get("山通番", 0)) in main_yamas]
                    relief_lane_rows = [r for r in aggregated_rows if int(r.get("山通番", 0)) in relief_yamas]

                    # ステップ5-3以降で使えるように準備データを保持する。
                    self.virtual_insert_context = {
                        "main_lane_rows": main_lane_rows,
                        "relief_lane_rows": relief_lane_rows,
                        "work_map": work_map,
                        "deadline_map": deadline_map,
                        "start_floor_map": start_floor_map,
                    }

                    # 動作確認用ログ（ON時のみ）。
                    print(
                        "[step5-2] prepared "
                        f"main_rows={len(main_lane_rows)}, relief_rows={len(relief_lane_rows)}, "
                        f"work_keys={len(work_map)}, deadline_keys={len(deadline_map)}, start_floor_keys={len(start_floor_map)}"
                    )

                    # 5-3: 入口関数を1回だけ呼び、戻り値を受け取る（まだ画面データへは反映しない）。
                    # virtual_row はスケジューラの時刻計算にのみ使用する。
                    # 【作業1】proc_details への-1明細注入は step5-5a（時刻確定）後に step5-5c で別途1行だけ行う。
                    battery_df = create_battery_change_mountain()
                    virtual_row = battery_df.iloc[0].to_dict() if battery_df is not None and not battery_df.empty else {}
                    result = insert_virtual_mountain_into_lane(
                        main_lane_rows=main_lane_rows,
                        relief_lane_rows=relief_lane_rows,
                        virtual_row=virtual_row,
                        work_map=work_map,
                        start_floor_map=start_floor_map,
                        deadline_map=deadline_map,
                        main_limit_end_secs=None,
                        min_gap_secs=10 * 60,
                        virtual_time_window=None,
                        lane_start_secs=None,
                    )
                    self.virtual_insert_result = result

                    # 動作確認用ログ（ON時のみ）。
                    before_main_yamas = set(int(r.get("山通番", 0)) for r in main_lane_rows)
                    before_relief_yamas = set(int(r.get("山通番", 0)) for r in relief_lane_rows)
                    after_main_yamas = set(int(r.get("山通番", 0)) for r in result.get("main_lane_rows", []))
                    after_relief_yamas = set(int(r.get("山通番", 0)) for r in result.get("relief_lane_rows", []))
                    virtual_in_main = any(is_virtual_yama(y) for y in after_main_yamas)
                    virtual_in_relief = any(is_virtual_yama(y) for y in after_relief_yamas)
                    evacuated_count = len(result.get("evacuated_existing_rows", []))
                    print(
                        "[step5-3] result "
                        f"mode={result.get('insert_mode')}, "
                        f"main_yamas_before={len(before_main_yamas)}, main_yamas_after={len(after_main_yamas)}, "
                        f"relief_yamas_before={len(before_relief_yamas)}, relief_yamas_after={len(after_relief_yamas)}, "
                        f"virtual_in_main={virtual_in_main}, virtual_in_relief={virtual_in_relief}, "
                        f"evacuated_count={evacuated_count}, main_over_limit={result.get('main_over_limit')}"
                    )

                    # [step5-4a] 山所属を反映（mountain_proc_map を更新）
                    # 戻り値の main_lane_rows / relief_lane_rows から山通番を抽出して
                    # 新しい mountain_proc_map を構築。この段階では所属の更新だけ。
                    # 時刻は後で 5-5 で更新する。
                    
                    new_mountain_proc_map = {}
                    
                    # main_lane_rows からメインに配置された山を抽出
                    for r in result.get('main_lane_rows', []):
                        yama_no = int(r.get('山通番', 0))
                        new_mountain_proc_map[yama_no] = PROC_MAIN
                    
                    # relief_lane_rows からリリーフに配置された山を抽出
                    for r in result.get('relief_lane_rows', []):
                        yama_no = int(r.get('山通番', 0))
                        new_mountain_proc_map[yama_no] = PROC_RELIEF
                    
                    # 仮想山 -1 も必ずメインに追加
                    new_mountain_proc_map[VIRTUAL_YAMA_NO] = PROC_MAIN
                    
                    # mountain_proc_map を更新前の状態を保存
                    before_proc_map_main = set(
                        int(yama_no) for yama_no in self.mountain_proc_map.keys()
                        if self.mountain_proc_map[yama_no] == PROC_MAIN
                    )
                    before_proc_map_relief = set(
                        int(yama_no) for yama_no in self.mountain_proc_map.keys()
                        if self.mountain_proc_map[yama_no] == PROC_RELIEF
                    )
                    
                    # mountain_proc_map を更新
                    self.mountain_proc_map.update(new_mountain_proc_map)
                    
                    # 更新後の状態を確認
                    after_proc_map_main = set(
                        int(yama_no) for yama_no in self.mountain_proc_map.keys()
                        if self.mountain_proc_map[yama_no] == PROC_MAIN
                    )
                    after_proc_map_relief = set(
                        int(yama_no) for yama_no in self.mountain_proc_map.keys()
                        if self.mountain_proc_map[yama_no] == PROC_RELIEF
                    )
                    
                    print(
                        "[step5-4a] mountain_proc_map updated: "
                        f"main_before={sorted(before_proc_map_main)}, main_after={sorted(after_proc_map_main)}, "
                        f"relief_before={sorted(before_proc_map_relief)}, relief_after={sorted(after_proc_map_relief)}"
                    )

                    # [step5-4b] mountain_proc を新しい所属に合わせて再構築
                    # 元のmountain_procから実開始時間・照合追加180秒などの情報を引き継ぎ、
                    # new_mountain_proc_map の順序で新しいDataFrameを作成する。
                    # 仮想山-1は元に居ないので、実開始時間は空のまま。時刻は5-5で入れる。
                    
                    new_rows = []
                    
                    # new_mountain_proc_map のすべての山（メイン・リリーフ・仮想山）をループ
                    for yama_no in sorted(new_mountain_proc_map.keys()):
                        proc = new_mountain_proc_map[yama_no]
                        
                        # 既存のmountain_procから対応する山の情報を探す
                        existing_row = self.mountain_proc[self.mountain_proc["山通番"] == yama_no]
                        
                        if not existing_row.empty:
                            # 既存の山: 元の情報を引き継ぐ（山工程は新しい所属で更新）
                            row_dict = existing_row.iloc[0].to_dict()
                            row_dict["山工程"] = proc  # 新しい所属で上書き
                            new_rows.append(row_dict)
                        else:
                            # 新規の山（仮想山-1など）: 最小限の情報で新規作成
                            new_rows.append({
                                "山通番": yama_no,
                                "山工程": proc,
                                "実開始時間": "",  # 仮想山は時刻なし（5-5で入れる）
                                "照合追加180秒": False,
                            })
                    
                    # 新しいDataFrameを作成
                    if new_rows:
                        self.mountain_proc = pd.DataFrame(new_rows)
                    else:
                        self.mountain_proc = pd.DataFrame()
                    
                    # proc_details の工程列を新しい所属に合わせて更新
                    if not self.proc_details.empty and self.mountain_proc_map:
                        self.proc_details["工程"] = self.proc_details["山通番"].map(
                            lambda y: str(self.mountain_proc_map.get(int(y), PROC_MAIN))
                        )
                    
                    # proc_details_display（表示用）の工程列も更新（事故りやすい点③対策）
                    if not self.proc_details_display.empty and self.mountain_proc_map:
                        self.proc_details_display["工程"] = self.proc_details_display["山通番"].map(
                            lambda y: str(self.mountain_proc_map.get(int(y), PROC_MAIN))
                        )
                    
                    # 確認用ログ：再構築後のmountain_procの中身を表示
                    print(
                        "[step5-4b] mountain_proc rebuilt: "
                        f"rows={len(self.mountain_proc)}, "
                        f"yama_nos={sorted(self.mountain_proc['山通番'].astype(int).tolist())}, "
                        f"procs={self.mountain_proc['山工程'].tolist()}"
                    )

                    # [step5-5a] schedule_rows から開始時刻を反映
                    # main_schedule_rows / relief_schedule_rows の start_secs を HH:MM に変換して、
                    # mountain_start_times と mountain_proc の実開始時間へ反映する。
                    # この段階では時刻だけを更新し、警告の合流は 5-5b で行う。
                    before_mountain_start_times = dict(self.mountain_start_times)
                    schedule_rows = list(result.get("main_schedule_rows", [])) + list(result.get("relief_schedule_rows", []))
                    updated_start_times = dict(self.mountain_start_times)

                    for schedule_row in schedule_rows:
                        yama_no = int(schedule_row.get("山通番", 0))
                        start_secs = schedule_row.get("start_secs")
                        if pd.isna(start_secs):
                            continue
                        start_hhmm = _seconds_to_hhmm(int(start_secs))
                        updated_start_times[yama_no] = start_hhmm

                    self.mountain_start_times = updated_start_times

                    if not self.mountain_proc.empty and "山通番" in self.mountain_proc.columns and "実開始時間" in self.mountain_proc.columns:
                        self.mountain_proc["実開始時間"] = self.mountain_proc["山通番"].map(
                            lambda y: str(self.mountain_start_times.get(int(y), ""))
                        )

                    print(
                        "[step5-5a] mountain_start_times updated: "
                        f"before={dict(sorted(before_mountain_start_times.items()))}, "
                        f"after={dict(sorted(self.mountain_start_times.items()))}, "
                        f"virtual_minus_one={self.mountain_start_times.get(VIRTUAL_YAMA_NO, '')}"
                    )

                    # [step5-5c] 表示/出力用の仮想山(-1)明細を1行だけ注入する。
                    # 【作業1の核】
                    # - step5-5a（時刻確定）の直後に実行
                    # - 注入前に既存の-1行を除去し、二重挿入を防止（常に1行保証）
                    # - 初回割付（step5前）へは混ぜず、時刻が決まった後にのみ追加
                    if self.proc_details is not None and not self.proc_details.empty:
                        self.proc_details = self._inject_single_virtual_battery_row(self.proc_details)
                    if self.proc_details_display is not None and not self.proc_details_display.empty:
                        self.proc_details_display = self._inject_single_virtual_battery_row(self.proc_details_display)

                    print(
                        "[step5-5c] injected virtual detail row "
                        f"proc_details={int(self.proc_details.get('山通番', pd.Series(dtype=float)).map(is_virtual_yama).sum())}, "
                        f"proc_details_display={int(self.proc_details_display.get('山通番', pd.Series(dtype=float)).map(is_virtual_yama).sum())}"
                    )

                else:
                    # 安全策: 元データが空の場合は準備を行わない。
                    print("[step5-2] skipped: proc_details or mountain_proc is empty")

            if not self.proc_details.empty and self.mountain_proc_map:
                self.proc_details["工程"] = self.proc_details["山通番"].map(
                    lambda y: str(self.mountain_proc_map.get(int(y), PROC_MAIN))
                )
            if not self.proc_details_display.empty and self.mountain_proc_map:
                self.proc_details_display["工程"] = self.proc_details_display["山通番"].map(
                    lambda y: str(self.mountain_proc_map.get(int(y), PROC_MAIN))
                )
            self.proc_summary = compute_proc_summary(self.proc_details, self.mountain_proc_map)
            return True
        except Exception as e:
            messagebox.showerror("工程割当エラー", f"工程の再計算に失敗しました: {e}")
            return False

    def _build_virtual_battery_row_for_df(self, base_df: pd.DataFrame) -> dict:
        """既存列構成に合わせて、表示/出力用の仮想山(-1)明細1行を作る。"""
        row = {}
        for col in base_df.columns:
            if pd.api.types.is_numeric_dtype(base_df[col]):
                row[col] = 0
            else:
                row[col] = ""

        fixed_values = {
            "山通番": VIRTUAL_YAMA_NO,
            "工程": PROC_MAIN,
            "工程内No": 1,
            "納入先": "〔バッテリー交換〕",
            "HINBAN": "BATTERY_CHANGE",
            "引取工数_秒": 600,
            "移動工数": 0,
            "高さ": 0,
        }
        for col, val in fixed_values.items():
            if col in base_df.columns:
                row[col] = val

        return row

    def _inject_single_virtual_battery_row(self, df: pd.DataFrame) -> pd.DataFrame:
        """既存-1行を除去した上で、仮想山(-1)明細を1行だけ注入する。"""
        if df is None or df.empty or "山通番" not in df.columns:
            return df

        out = df.copy()
        out = out.loc[~out["山通番"].map(is_virtual_yama)].copy()

        row = self._build_virtual_battery_row_for_df(out if not out.empty else df)
        virtual_df = pd.DataFrame([row], columns=out.columns if not out.empty else df.columns)
        return pd.concat([out, virtual_df], axis=0, ignore_index=True)

    def _collect_late_relief_warnings(self, master_df: pd.DataFrame):
        """リリーフに割り振っても締切(入車10分前)を超過する山を抽出する。"""
        warnings = []
        if self.proc_details is None or self.proc_details.empty:
            return warnings
        if self.mountain_proc is None or self.mountain_proc.empty:
            return warnings
        if master_df is None or master_df.empty:
            return warnings

        md = master_df.copy()
        md["OData_納入先"] = md["OData_納入先"].astype(str).str.strip().map(_normalize_dest_name)
        md["NONYUHIBIN"] = md["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
        md["NONYUHIBIN"] = pd.to_numeric(md["NONYUHIBIN"], errors="coerce").map(
            lambda n: f"{int(n):02d}" if pd.notna(n) else ""
        )
        md["入車時間"] = md["入車時間"].astype(str).str.strip()
        master_map = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in md.iterrows()}

        relief_rows = self.mountain_proc[self.mountain_proc["山工程"].astype(str) == PROC_RELIEF]
        if relief_rows.empty:
            return warnings

        for _, rr in relief_rows.iterrows():
            yama = int(rr["山通番"])
            sub = self.proc_details[self.proc_details["山通番"] == yama]
            if sub.empty:
                continue

            start_txt = str(rr.get("実開始時間", "")).strip()
            start_secs = _to_operational_timeline_secs(_time_to_seconds(start_txt))
            if start_secs is None:
                continue

            max_cost = pd.to_numeric(sub.get("移動工数", np.nan), errors="coerce")
            max_cost_val = float(max_cost.max()) if max_cost.notna().any() else 0.0
            pals = int(sub.shape[0])
            work_secs = int(np.round(
                max_cost_val + BASE_ONE_TIME + ((pals - 1) * MIDDLE_WORK) + (pals * BASE_PER_PAL), 0
            ))
            end_secs = _calc_work_end_with_breaks(start_secs, work_secs)

            deadline_candidates = []
            for _, drow in sub.iterrows():
                vendor = _normalize_dest_name(str(drow.get("納入先", "")).strip())
                nony = str(drow.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
                order2 = nony[-2:] if len(nony) >= 2 else ""
                if not vendor or not order2:
                    continue
                pickup = master_map.get((vendor, order2), "")
                pickup_secs = _to_operational_timeline_secs(_time_to_seconds(pickup)) if pickup else None
                if pickup_secs is None:
                    continue
                deadline_candidates.append(max(0, int(pickup_secs) - ARRIVAL_BUFFER_SECS))

            if not deadline_candidates:
                continue
            deadline_secs = min(deadline_candidates)
            if end_secs > deadline_secs:
                warnings.append({
                    "山通番": yama,
                    "開始": start_txt,
                    "締切": f"{deadline_secs // 3600:02d}:{(deadline_secs % 3600) // 60:02d}",
                })

        warnings.sort(key=lambda x: x["山通番"])
        return warnings

    def _show_late_relief_warning_popup(self):
        """あふれ工程の山がある場合は警告ポップアップを表示する。"""
        # あふれは process_assigner が PROC_OVERFLOW として判定済み
        overflow_yamas = [
            yama for yama, proc in self.mountain_proc_map.items()
            if str(proc) == PROC_OVERFLOW
        ]
        if not overflow_yamas:
            return
        lines = [
            "全割当パターンを探索しても締切(入車10分前)に間に合わない山があります。",
            f"対象山数: {len(overflow_yamas)}山（人工追加が必要）",
            "",
        ]
        for yama in sorted(overflow_yamas)[:20]:
            st = self.mountain_start_times.get(int(yama), "")
            lines.append(f"山{yama}: 開始 {st}")
        if len(overflow_yamas) > 20:
            lines.append(f"... 他 {len(overflow_yamas) - 20} 山")
        messagebox.showwarning("あふれアラート", "\n".join(lines))

    def _auto_export_spo(self):
        """SPO用Excel自動出力"""
        start_times = getattr(self, "mountain_start_times", {})
        overflow_yamas = {
            int(yama)
            for yama, proc in self.mountain_proc_map.items()
            if str(proc) == PROC_OVERFLOW
        }
        delay_map = {}
        if self.mountain_proc is not None and not self.mountain_proc.empty and "照合追加180秒" in self.mountain_proc.columns:
            delay_map = dict(zip(
                self.mountain_proc["山通番"].astype(int),
                self.mountain_proc["照合追加180秒"].fillna(False).astype(bool)
            ))
        spo_df = build_spo_export_df(
            self.proc_details,
            self.mountain_proc_map,
            start_times,
            overflow_yamas=overflow_yamas,
            inspection_delay_map=delay_map,
        )
        master_df = pd.DataFrame()
        try:
            master_path = get_master_path()
            master_df = load_pickup_time_master_xlsx(master_path)
            unmatched_path = Path(self.export_dir) / "SPOアップロード用_未ヒット一覧.csv"
            spo_df = attach_pickup_start_time(spo_df, master_df, unmatched_csv_path=unmatched_path)
        except Exception:
            pass
        if spo_df is not None and not spo_df.empty:
            spo_path = export_spo_xlsx(spo_df, out_dir=self.export_dir)
            try:
                append_to_spo_history(spo_df, out_dir=self.export_dir)
            except Exception:
                pass
            try:
                messagebox.showinfo("SPO出力", f"SPO用Excelを出力しました。\n{spo_path}")
                if os.name == "nt":
                    os.startfile(self.export_dir)
            except Exception:
                pass

    # ===== タブ更新 =====
    def update_basic_views(self):
        for iid in self.basic_summary.get_children():
            self.basic_summary.delete(iid)
        df = compute_basic_groups(self.group_details, self.group_results, self.height_cap.get())
        for _, row in df.iterrows():
            values = [row[c] for c in self.basic_summary["columns"]]
            tags = ("basic_mixed",) if str(row.get("混載", "")) == "★" else ()
            self.basic_summary.insert("", "end", values=values, tags=tags)

    def update_mix_views(self):
        for iid in self.mix_summary.get_children():
            self.mix_summary.delete(iid)
        df = compute_mixed_groups(self.size1_mixed_summary, self.size1_mixed_details, self.height_cap.get())
        for _, row in df.iterrows():
            is_mixed = bool(row.get("混載フラグ", False))
            star = "★" if is_mixed else ""
            values = [star] + [row[c] for c in self.mix_summary["columns"] if c != "混載"]
            tags = ("mixed_true",) if is_mixed else ()
            self.mix_summary.insert("", "end", values=values, tags=tags)

    def update_dest_views(self):
        for iid in self.dest_summary.get_children():
            self.dest_summary.delete(iid)
        df = compute_dest_by_mountain(self.size1_mixed_details, self.size1_mixed_summary, self.height_cap.get())
        for _, row in df.iterrows():
            values = [row[c] for c in self.dest_summary["columns"]]
            tag = ("dst_mixed",) if int(row.get("納入先数", 0)) >= 2 else ()
            self.dest_summary.insert("", "end", values=values, tags=tag)

    def update_kb_views(self):
        if not hasattr(self, "kb_summary"):
            return
        for iid in self.kb_summary.get_children():
            self.kb_summary.delete(iid)
        if self.proc_summary is None or self.proc_summary.empty:
            return
        for _, row in self.proc_summary.iterrows():
            yama = int(row.get("山通番"))
            lab = str(self.mountain_proc_map.get(yama, PROC_MAIN))
            lab_display = PROC_MAIN_LABEL if lab == PROC_MAIN else PROC_RELIEF_LABEL
            start_time = self.mountain_start_times.get(yama, "")
            vals = [
                yama, lab_display,
                row.get("メイン工程", 0),
                row.get("リリーフ工程", 0),
                row.get("合計", 0),
                start_time,
            ]
            tag = ("proc_main" if lab == PROC_MAIN else "proc_relief",)
            self.kb_summary.insert("", "end", values=vals, tags=tag)

    def update_setboard_views(self):
        """セットボードの3レーンを更新"""
        for tree in (self.sb_main_tree, self.sb_relief_tree, self.sb_overflow_tree):
            for iid in tree.get_children():
                tree.delete(iid)
        display_df = self.proc_details_display if (
            self.proc_details_display is not None and not self.proc_details_display.empty
        ) else self.proc_details
        if display_df is None or display_df.empty:
            return

        def _start_sort_key(yama_no: int):
            st = str(self.mountain_start_times.get(int(yama_no), "")).strip()
            try:
                hh, mm = st.split(":", 1)
                return (0, int(hh) * 60 + int(mm), int(yama_no))
            except Exception:
                return (1, 10**9, int(yama_no))

        yama_list = [int(y) for y in display_df["山通番"].unique()]
        yama_list = sorted(yama_list, key=_start_sort_key)
        inspection_delay_map = {}
        if self.mountain_proc is not None and not self.mountain_proc.empty and "照合追加180秒" in self.mountain_proc.columns:
            inspection_delay_map = dict(zip(
                self.mountain_proc["山通番"].astype(int),
                self.mountain_proc["照合追加180秒"].fillna(False).astype(bool)
            ))

        for yama in yama_list:
            sub = display_df[display_df["山通番"] == yama]
            pal = int(sub.shape[0])
            hsum = int(sub["高さ"].astype(float).sum()) if "高さ" in sub.columns else 0
            max_cost = float(sub["移動工数"].max()) if sub["移動工数"].notna().any() else 0.0
            # 仮想山(-1)は表示用の固定10分(600秒)を使い、通常式の台数連動から切り離す。
            if is_virtual_yama(yama):
                pick_cost = 600
            else:
                pick_cost = int(np.round(
                    max_cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0
                ))
            from src.services.sorter import get_dest_list_for_group
            dests = "/".join(get_dest_list_for_group(sub))
            start_time = self.mountain_start_times.get(int(yama), "")
            proc = self.mountain_proc_map.get(int(yama), PROC_MAIN)

            # レーン振り分け
            if proc == PROC_OVERFLOW:
                target_tree = self.sb_overflow_tree
            elif proc == PROC_MAIN:
                target_tree = self.sb_main_tree
            else:
                target_tree = self.sb_relief_tree

            parity = "even" if (int(yama) % 2 == 0) else "odd"
            is_inspection_delayed = bool(inspection_delay_map.get(int(yama), False))
            is_overflow = (proc == PROC_OVERFLOW)
            summary_tag = "mtn_overflow_summary" if is_overflow else (
                f"mtn_{parity}_summary_delay" if is_inspection_delayed else f"mtn_{parity}_summary"
            )
            detail_tag = "mtn_overflow_detail" if is_overflow else f"mtn_{parity}_detail"
            # 仮想山は固定10分表示を優先し、照合+180の表記を付けない。
            if is_virtual_yama(yama):
                pick_cost_text = "600"
            else:
                pick_cost_text = f"{pick_cost} +180" if is_inspection_delayed else str(pick_cost)
            section_label = "あふれ" if is_overflow else "山"

            target_tree.insert(
                "", "end", iid=f"sb:{proc}:{yama}",
                values=(section_label, start_time, dests, "", "", pick_cost_text, ""),
                tags=(summary_tag,)
            )

            # 山配下の各パレット明細を同時表示
            sub2 = sub.copy()
            sub2["工程内No"] = pd.to_numeric(sub2.get("工程内No", 0), errors="coerce").fillna(0).astype(int)
            # 移動工数列が存在しない山でも KeyError にならないようガード
            if "移動工数" in sub2.columns:
                sub2["移動工数"] = pd.to_numeric(sub2["移動工数"], errors="coerce")
            else:
                sub2["移動工数"] = float("nan")
            sub2["高さ"] = pd.to_numeric(sub2.get("高さ", np.nan), errors="coerce")
            sub2["_store_key"] = sub2.get("ストア", sub2.get("SYUKKASAKI", "")).astype(str).str.strip()
            sub2["_order_key"] = sub2.get("NONYUHIBIN", "").astype(str).str.strip()
            # build_groupeddata_json_for_mountain() の採番ルールと同一キーで並べる:
            # 第1キー: 移動工数 昇順（na は末尾）、第2キー: SEBANGO 昇順（なければ工程内No 昇順）
            _detail_sort_by = ["移動工数"]
            _detail_asc = [True]
            if "SEBANGO" in sub2.columns:
                _detail_sort_by.append("SEBANGO")
                _detail_asc.append(True)
            else:
                _detail_sort_by.append("工程内No")
                _detail_asc.append(True)
            sub2 = sub2.sort_values(
                by=_detail_sort_by,
                ascending=_detail_asc,
                na_position="last",
            )
            display_rows = list(sub2.iterrows())
            prev_key = None
            for idx, (_, row) in enumerate(display_rows, start=1):
                store_text = str(row.get("ストア", row.get("SYUKKASAKI", ""))).strip()
                order_text = str(row.get("NONYUHIBIN", "")).strip()
                base_detail_tag = detail_tag if (idx % 2 == 1) else f"mtn_{parity}_detail_alt"
                tags = [base_detail_tag]
                current_key = (store_text, order_text)
                if prev_key is not None and current_key != prev_key:
                    break_tag = "detail_break_overflow" if proc == PROC_OVERFLOW else (
                        "detail_break_main" if proc == PROC_MAIN else "detail_break_relief"
                    )
                    tags.append(break_tag)
                prev_key = current_key
                target_tree.insert(
                    "", "end", iid=f"sbd:{proc}:{yama}:{idx}",
                    values=(
                        f"└{idx}",
                        start_time,
                        str(row.get("納入先", row.get("OData_納入先", ""))),
                        store_text,
                        order_text,
                        "",
                        str(row.get("UKEIRE", "")),
                    ),
                    tags=tuple(tags),
                )

            sub2 = sub2.drop(columns=["_store_key", "_order_key"], errors="ignore")

            sep = tuple([""] * len(self._sb_lane_columns))
            target_tree.insert("", "end", values=sep, tags=("mountain_sep",))

    def _on_setboard_select(self, source: str):
        # 同時表示レイアウトのため、選択で他ビュー更新は行わない
        return

    # ===== 入車時間マスタ管理 =====
    def _initial_load_master(self):
        try:
            master_path = get_master_path()
            self.master_data = load_pickup_time_master_xlsx(master_path)
            self.refresh_master_tree()
            self.refresh_routes()
        except Exception as e:
            print(f"入車時間マスタ読込エラー: {e}")

    def save_master(self):
        try:
            master_df = self._collect_master_from_tree()
            if master_df.empty:
                messagebox.showwarning("マスタ保存", "保存するデータがありません。")
                return
            self.master_data = master_df.copy()
            save_pickup_time_master_xlsx(self.master_data, get_master_path())
            messagebox.showinfo("マスタ保存", f"保存しました。件数: {len(self.master_data)}件")
        except Exception as e:
            messagebox.showerror("マスタ保存エラー", str(e))

    def _save_master_silent(self):
        """ダイアログなしで入車時間マスタを保存（終了時オートセーブ用）。"""
        master_df = self._collect_master_from_tree()
        if master_df.empty:
            return
        self.master_data = master_df.copy()
        save_pickup_time_master_xlsx(self.master_data, get_master_path())

    def refresh_master_tree(self):
        for iid in self.master_tree.get_children():
            self.master_tree.delete(iid)
        if self.master_data is None or self.master_data.empty:
            return
        for i, row in self.master_data.iterrows():
            self.master_tree.insert("", "end", iid=f"m:{i}",
                                    values=(str(row.get("OData_納入先", "")),
                                            str(row.get("NONYUHIBIN", "")),
                                            str(row.get("入車時間", "")),
                                            set_flag_value_to_checkbox_mark(row.get("セットありフラグ", ""))))

    def on_master_tree_click(self, event):
        """セットありフラグ列（4列目）のクリック時のみ☑/☐をトグルする。"""
        row_id = self.master_tree.identify_row(event.y)
        col_id = self.master_tree.identify_column(event.x)
        if not row_id or col_id != "#4":
            return None

        values = list(self.master_tree.item(row_id, "values"))
        if len(values) < 4:
            return "break"
        current_mark = str(values[3]).strip()
        values[3] = "☑" if current_mark != "☑" else "☐"
        self.master_tree.item(row_id, values=tuple(values))
        return "break"

    def _collect_master_from_tree(self) -> pd.DataFrame:
        """画面上の入車時間マスタ（未保存編集を含む）をDataFrame化する。"""
        rows = []
        try:
            for iid in self.master_tree.get_children():
                values = self.master_tree.item(iid, "values")
                if len(values) < 3:
                    continue
                rows.append({
                    "OData_納入先": str(values[0]).strip(),
                    "NONYUHIBIN": str(values[1]).strip(),
                    "入車時間": str(values[2]).strip(),
                    "セットありフラグ": checkbox_mark_to_set_flag_value(values[3]) if len(values) >= 4 else "",
                })
        except Exception:
            return pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"])
        if not rows:
            return pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"])
        return pd.DataFrame(rows)

    def add_master_row(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("入車時間マスタ - 行追加")
        dialog.geometry("460x270")
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="OData_納入先:").grid(row=0, column=0, padx=14, pady=10, sticky="w")
        dest_var = tk.StringVar()
        ctk.CTkEntry(dialog, textvariable=dest_var, width=240).grid(row=0, column=1, padx=10, pady=10)
        ctk.CTkLabel(dialog, text="NONYUHIBIN:").grid(row=1, column=0, padx=14, pady=10, sticky="w")
        bin_var = tk.StringVar()
        ctk.CTkEntry(dialog, textvariable=bin_var, width=240).grid(row=1, column=1, padx=10, pady=10)
        ctk.CTkLabel(dialog, text="入車時間 (HH:MM):").grid(row=2, column=0, padx=14, pady=10, sticky="w")
        time_var = tk.StringVar()
        ctk.CTkEntry(dialog, textvariable=time_var, width=240).grid(row=2, column=1, padx=10, pady=10)
        ctk.CTkLabel(dialog, text="セットありフラグ(1/0):").grid(row=3, column=0, padx=14, pady=10, sticky="w")
        set_var = tk.StringVar(value="0")
        ctk.CTkEntry(dialog, textvariable=set_var, width=240).grid(row=3, column=1, padx=10, pady=10)

        def do_add():
            d, b, t = dest_var.get().strip(), bin_var.get().strip(), time_var.get().strip()
            f = set_var.get().strip()
            if not d or not b or not t:
                messagebox.showwarning("入力エラー", "全ての項目を入力してください。")
                return
            try:
                b = f"{int(b):02d}"
            except Exception:
                pass
            new_id = f"m:new_{len(self.master_tree.get_children())}"
            self.master_tree.insert(
                "", "end", iid=new_id,
                values=(d, b, t, set_flag_value_to_checkbox_mark(f))
            )
            dialog.destroy()

        ctk.CTkButton(dialog, text="追加", command=do_add, fg_color="#28a745").grid(row=4, column=0, columnspan=2, pady=16)

    def delete_master_row(self):
        selection = self.master_tree.selection()
        if not selection:
            messagebox.showinfo("削除", "削除する行を選択してください。")
            return
        if not messagebox.askyesno("確認", f"{len(selection)}行を削除しますか？"):
            return
        for iid in selection:
            self.master_tree.delete(iid)

    def clear_master(self):
        if not messagebox.askyesno("確認", "全てのマスタデータをクリアしますか？"):
            return
        for iid in self.master_tree.get_children():
            self.master_tree.delete(iid)
        self.master_data = pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"])

    def edit_master_row(self, event=None):
        selection = self.master_tree.selection()
        if not selection:
            return
        iid = selection[0]
        values = self.master_tree.item(iid, "values")
        if len(values) < 3:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("入車時間マスタ - 行編集")
        dialog.geometry("460x270")
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="OData_納入先:").grid(row=0, column=0, padx=14, pady=10, sticky="w")
        dest_var = tk.StringVar(value=values[0])
        ctk.CTkEntry(dialog, textvariable=dest_var, width=240).grid(row=0, column=1, padx=10, pady=10)
        ctk.CTkLabel(dialog, text="NONYUHIBIN:").grid(row=1, column=0, padx=14, pady=10, sticky="w")
        bin_var = tk.StringVar(value=values[1])
        ctk.CTkEntry(dialog, textvariable=bin_var, width=240).grid(row=1, column=1, padx=10, pady=10)
        ctk.CTkLabel(dialog, text="入車時間 (HH:MM):").grid(row=2, column=0, padx=14, pady=10, sticky="w")
        time_var = tk.StringVar(value=values[2])
        ctk.CTkEntry(dialog, textvariable=time_var, width=240).grid(row=2, column=1, padx=10, pady=10)
        ctk.CTkLabel(dialog, text="セットありフラグ(1/0):").grid(row=3, column=0, padx=14, pady=10, sticky="w")
        set_var = tk.StringVar(value=checkbox_mark_to_set_flag_value(values[3]) if len(values) >= 4 else "")
        ctk.CTkEntry(dialog, textvariable=set_var, width=240).grid(row=3, column=1, padx=10, pady=10)

        def do_update():
            d, b, t = dest_var.get().strip(), bin_var.get().strip(), time_var.get().strip()
            f = set_var.get().strip()
            if not d or not b or not t:
                messagebox.showwarning("入力エラー", "全ての項目を入力してください。")
                return
            try:
                b = f"{int(b):02d}"
            except Exception:
                pass
            self.master_tree.item(iid, values=(d, b, t, set_flag_value_to_checkbox_mark(f)))
            dialog.destroy()

        ctk.CTkButton(dialog, text="更新", command=do_update, fg_color="#0d6efd").grid(row=4, column=0, columnspan=2, pady=16)

    def import_from_ukeire_sheet(self):
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="受入データExcelを選択してください（全受入_納入便データシート）",
            filetypes=[("Excel files", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")],
            parent=self)
        if not file_path:
            return
        try:
            df = parse_ukeire_ch_excel(Path(file_path), sheet_name="全受入_納入便データ")
        except Exception as e:
            messagebox.showerror("インポートエラー", str(e))
            return

        if df.empty:
            messagebox.showwarning("インポート", "受入=CH の有効データを抽出できませんでした。")
            return

        vendor_counts = df.groupby("OData_納入先").size()
        summary_lines = [f"  {v}: {n}件" for v, n in vendor_counts.items()]
        msg = f"受入=CH で {len(df)} 件を抽出しました。\n\n【納入先別件数】\n" + "\n".join(summary_lines)
        msg += "\n\n現在のマスタを置き換えますか？"
        if not messagebox.askyesno("インポート確認", msg):
            return

        df_for_view = df.copy()
        if "セットありフラグ" not in df_for_view.columns:
            df_for_view["セットありフラグ"] = ""
        df_for_view = df_for_view[["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]]
        self.master_data = df_for_view.copy()
        self.refresh_master_tree()
        messagebox.showinfo("インポート完了", f"受入=CH の {len(df)} 件をインポートしました。")

    def import_from_master_xlsx(self):
        """入車時間マスタ.xlsx を直接読込して画面のマスタ表示を全置換する。"""
        master_path = get_master_path()
        try:
            df = load_pickup_time_master_xlsx(master_path)
        except Exception as e:
            messagebox.showerror("取込エラー", str(e))
            return

        if df.empty:
            if not messagebox.askyesno("取込確認", "マスタが空です。取込を続けますか？"):
                return

        if not messagebox.askyesno("取込確認", "既存の表示内容を取込内容で全置換します。よろしいですか？"):
            return

        self.master_data = df[["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]].copy()
        self.refresh_master_tree()

        messagebox.showinfo("取込完了", f"{master_path.name} から {len(df)} 件を取込しました。")


def main():
    try:
        app = App()
    except Exception as e:
        messagebox.showerror("起動エラー", str(e))
        return
    app.mainloop()


if __name__ == "__main__":
    main()
