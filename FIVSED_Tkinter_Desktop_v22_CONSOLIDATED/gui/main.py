from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Optional

# Support both the recommended package launch (`python -m gui.main`) and
# direct script launch (`python gui/main.py`) during development/testing.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from backend.components import get_component_status
from backend.config import config
from backend.hardware_reader import hardware_reader
from backend.pi_status import get_pi_status
from backend.stm32_engine import stm32_engine
from backend.stm32_link import stm32_link
from backend.storage import storage


WINDOW_WIDTH = 480 if os.name != "nt" else 800
WINDOW_HEIGHT = 800 if os.name != "nt" else 480
REFRESH_MS = max(2000, min(5000, int(config.serial.poll_interval_seconds * 1000)))

BG = "#ffffff"
PANEL = "#f5f7fa"
PANEL_2 = "#ffffff"
BORDER = "#8a959f"
TEXT = "#111111"
MUTED = "#4a4f54"
CARD_TEXT = "#111111"
CARD_MUTED = "#4a4f54"
CARD_BORDER = "#8a959f"
CYAN = "#005f73"
GREEN = "#116b3a"
RED = "#a61b1b"
AMBER = "#8a5a00"
BLUE = "#0b4f9c"
ACCENT = "#e8eef3"



class FIVSEDDesktopApp:
    """Native Tkinter FIVSED operator console.

    The desktop UI talks to the backend modules directly; it does not launch a
    browser and it does not calculate integrity hashes itself. STM32 remains the
    security authority.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FIVSED — Firmware Integrity Verification and Security Event Detection")
        # The physical Raspberry Pi HDMI panel is 800×480. Raspberry Pi firmware/DRM rotates
        # the display 90° LEFT so the X desktop is presented as a 480×800 portrait surface.
        # Set FIVSED_FULLSCREEN=0 when a bordered development window is preferred.
        self._fullscreen = os.name != "nt" and os.environ.get("FIVSED_FULLSCREEN", "1") != "0"
        try:
            self.root.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass

        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(420, 640)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if self._fullscreen:
            # Remove window-manager decorations as well as enabling fullscreen.
            self.root.overrideredirect(True)
            self.root.attributes("-fullscreen", True)
            self.root.after(100, self._apply_fullscreen_geometry)

        self.targets: list[dict[str, Any]] = []
        self.selected_target: Optional[dict[str, Any]] = None
        self.active_scan_id: Optional[str] = None
        self._refresh_running = False
        self._closing = False
        self.current_page = "Overview"

        self._configure_style()
        self._build_shell()
        self._show_page("Overview")
        self.root.after(50, self._initial_refresh)

    # ------------------------------------------------------------------ UI setup
    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "FIVSED.Treeview",
            background=PANEL_2,
            foreground=CARD_TEXT,
            fieldbackground=PANEL_2,
            bordercolor=CARD_BORDER,
            rowheight=24,
            font=("TkDefaultFont", 8),
        )
        style.configure(
            "FIVSED.Treeview.Heading",
            background="#e9eef2",
            foreground=TEXT,
            relief="flat",
            font=("TkDefaultFont", 8, "bold"),
            padding=(4, 4),
        )
        style.map(
            "FIVSED.Treeview",
            background=[("selected", "#dce9f2"), ("focus", PANEL_2)],
            foreground=[("selected", TEXT)],
        )
        style.configure("FIVSED.TButton", background=ACCENT, foreground=TEXT, padding=(7, 4), borderwidth=1, relief="solid")
        style.map("FIVSED.TButton", background=[("active", "#d9e3ea"), ("disabled", "#eef1f3")], foreground=[("disabled", "#8a8f94")])
        style.configure("FIVSED.Horizontal.TProgressbar", background="#4f88a8", troughcolor="#e6ebef", bordercolor="#e6ebef", lightcolor="#4f88a8", darkcolor="#4f88a8")

    def _build_shell(self) -> None:
        self.header = tk.Frame(self.root, bg=BG, height=60, highlightbackground=CARD_BORDER, highlightthickness=1)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        brand = tk.Label(self.header, text="FIVSED", bg=BG, fg=TEXT, font=("TkDefaultFont", 17, "bold"))
        brand.pack(side="left", padx=(12, 10), pady=5)

        status_box = tk.Frame(self.header, bg=BG)
        status_box.pack(side="right", padx=10, pady=5, fill="x", expand=True)
        self.pi_var = getattr(self, "pi_var", tk.StringVar(value="PI: CHECKING"))
        self.stm_var = getattr(self, "stm_var", tk.StringVar(value="STM32: CHECKING"))
        self.esp_var = getattr(self, "esp_var", tk.StringVar(value="ESP32: CHECKING"))
        top_row = tk.Frame(status_box, bg=BG)
        top_row.pack(fill="x", expand=True, anchor="e")
        self._status_label(top_row, self.pi_var, TEXT).pack(side="left", padx=3)
        self._status_label(top_row, self.stm_var, TEXT).pack(side="left", padx=3)
        self._status_label(top_row, self.esp_var, TEXT).pack(side="left", padx=3)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        # Horizontal navigation for the 480×800 portrait appliance layout.
        self.nav = tk.Frame(body, bg=BG, height=46, highlightbackground=CARD_BORDER, highlightthickness=1)
        self.nav.pack(side="top", fill="x")
        self.nav.pack_propagate(False)

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="top", fill="both", expand=True, padx=6, pady=5)

        self.page_buttons: dict[str, tk.Button] = {}
        for label in ("Overview", "Targets", "Scan", "History", "System", "Logs"):
            btn = tk.Button(
                self.nav,
                text=label.upper(),
                command=lambda name=label: self._show_page(name),
                anchor="center",
                bg=BG,
                fg=TEXT,
                activebackground=ACCENT,
                activeforeground=TEXT,
                relief="flat",
                borderwidth=0,
                font=("TkDefaultFont", 9, "bold"),
            )
            btn.pack(side="left", fill="both", expand=True, padx=2, pady=4)
            self.page_buttons[label] = btn


        self.statusbar = tk.Label(self.root, text="Initializing FIVSED desktop console…", bg=BG, fg=MUTED, anchor="w", padx=7, font=("TkDefaultFont", 9), highlightbackground=CARD_BORDER, highlightthickness=1)
        self.statusbar.pack(fill="x", side="bottom", ipady=2)

        self.frames: dict[str, tk.Frame] = {}
        self._build_overview()
        self._build_targets()
        self._build_scan()
        self._build_history()
        self._build_system()
        self._build_logs()

    def _status_label(self, parent: tk.Misc, variable: tk.StringVar, fg: str) -> tk.Label:
        return tk.Label(parent, textvariable=variable, bg=BG, fg=fg, font=("TkDefaultFont", 8, "bold"))

    def _new_page(self, name: str) -> tk.Frame:
        frame = tk.Frame(self.content, bg=BG)
        self.frames[name] = frame
        return frame

    def _title(self, parent: tk.Misc, title: str, subtitle: str = "") -> None:
        title_row = tk.Frame(parent, bg=BG)
        title_row.pack(fill="x")
        tk.Label(title_row, text=title, bg=BG, fg=TEXT, font=("TkDefaultFont", 13, "bold")).pack(side="left", anchor="w")
        if subtitle:
            tk.Label(parent, text=subtitle, bg=BG, fg=MUTED, font=("TkDefaultFont", 8), wraplength=440, justify="left").pack(anchor="w", pady=(1, 5))

    def _card(self, parent: tk.Misc, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=CARD_BORDER, highlightthickness=1)
        tk.Label(card, text=title.upper(), bg=PANEL, fg=CARD_MUTED, font=("TkDefaultFont", 7, "bold")).pack(anchor="w", padx=8, pady=(5, 2))
        return card

    # --------------------------------------------------------------- Overview page
    # --------------------------------------------------------------- Overview page
    def _build_overview(self) -> None:
        frame = self._new_page("Overview")
        self._title(frame, "FIRMWARE INTEGRITY", "Native Raspberry Pi console — security decisions originate from STM32.")

        status_card = self._card(frame, "Integrity status")
        status_card.pack(fill="x", pady=(0, 6))
        self.overview_status = tk.StringVar(value="NO SCAN RESULT")
        self.overview_detail = tk.StringVar(value="Select a detected target to begin an authorized firmware scan.")
        tk.Label(status_card, textvariable=self.overview_status, bg=PANEL, fg=CARD_TEXT, font=("TkDefaultFont", 14, "bold")).pack(anchor="w", padx=8, pady=(3, 1))
        tk.Label(status_card, textvariable=self.overview_detail, bg=PANEL, fg=CARD_TEXT, wraplength=440, justify="left", font=("TkDefaultFont", 9)).pack(anchor="w", padx=8, pady=(0, 7))

        target_card = self._card(frame, "Selected target")
        target_card.pack(fill="x", pady=(0, 6))
        self.ov_target = tk.StringVar(value="Target: N/A")
        self.ov_size = tk.StringVar(value="Firmware size: N/A")
        self.ov_duration = tk.StringVar(value="Duration: N/A")
        self.ov_authority = tk.StringVar(value="Decision authority: STM32")
        for var in (self.ov_target, self.ov_size, self.ov_duration, self.ov_authority):
            tk.Label(target_card, textvariable=var, bg=PANEL, fg=CARD_TEXT, font=("TkDefaultFont", 8), anchor="w").pack(fill="x", padx=8, pady=1)
        tk.Button(target_card, text="OPEN TARGETS", command=lambda: self._show_page("Targets"), bg=ACCENT, fg=TEXT, activebackground="#d9e3ea", activeforeground=TEXT, relief="solid", borderwidth=1, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=8, pady=(5, 7))

        flow = self._card(frame, "Verification pipeline")
        flow.pack(fill="x", pady=(0, 6))
        self.flow_var = tk.StringVar(value="TARGET DISCOVERY → FIRMWARE ACQUISITION → STM32 SHA-256 → STM32 VERIFICATION → RESULT")
        tk.Label(flow, textvariable=self.flow_var, bg=PANEL, fg=CYAN, wraplength=440, justify="left", font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=8, pady=7)

        note = self._card(frame, "Trust boundary")
        note.pack(fill="x")
        tk.Label(note, text="Raspberry Pi displays and records the STM32 response. It never calculates the production integrity decision. Unsupported or failed acquisition is shown as an error, never as PASS.", bg=PANEL, fg=CARD_TEXT, wraplength=440, justify="left", font=("TkDefaultFont", 9)).pack(anchor="w", padx=8, pady=(3, 7))


    # ---------------------------------------------------------------- Targets page
    def _build_targets(self) -> None:
        frame = self._new_page("Targets")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_rowconfigure(2, minsize=295)

        top = tk.Frame(frame, bg=BG)
        top.grid(row=0, column=0, sticky="ew")
        self._title(top, "TARGET DEVICES", "Only devices reported as connected by runtime discovery are shown.")
        tk.Button(top, text="REFRESH", command=self.request_refresh, bg=ACCENT, fg=TEXT, activebackground="#d9e3ea", activeforeground=TEXT, relief="solid", borderwidth=1, font=("TkDefaultFont", 8, "bold")).pack(side="right", pady=(0, 5))

        table_card = self._card(frame, "Connected devices")
        table_card.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        table_wrap = tk.Frame(table_card, bg=PANEL_2)
        table_wrap.pack(fill="both", expand=True, padx=5, pady=4)

        columns = ("name", "type", "status", "capability")
        self.target_tree = ttk.Treeview(table_wrap, columns=columns, show="headings", style="FIVSED.Treeview", selectmode="browse")
        widths = {"name": 145, "type": 55, "status": 70, "capability": 150}
        headings = {"name": "DEVICE", "type": "TYPE", "status": "STATUS", "capability": "FIRMWARE ACQUISITION"}
        for col in columns:
            self.target_tree.heading(col, text=headings[col])
            self.target_tree.column(col, width=widths[col], minwidth=45, anchor="w", stretch=(col == "capability"))
        scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.target_tree.yview)
        self.target_tree.configure(yscrollcommand=scroll.set)
        self.target_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.target_tree.bind("<<TreeviewSelect>>", self._on_target_selected)

        self.no_targets_label = tk.Label(table_wrap, text="NO TARGET DEVICES DETECTED\n\nConnect an authorized target device.", bg=PANEL_2, fg=CARD_MUTED, font=("TkDefaultFont", 10, "bold"))

        detail = self._card(frame, "Target detail")
        detail.grid(row=2, column=0, sticky="nsew")
        detail.grid_propagate(False)

        self.target_detail_vars = {key: tk.StringVar(value="N/A") for key in (
            "name", "manufacturer", "model", "type", "vid", "pid", "serial",
            "logical_target_id", "physical_uid", "bus", "interface", "method",
            "capability", "access", "jedec", "size", "bios_vendor", "bios_version",
            "bios_date", "uefi_version", "architecture", "cpu", "sku", "asset_tag",
            "uuid", "build_id", "reference_state",
        )}
        grid = tk.Frame(detail, bg=PANEL)
        grid.pack(fill="x", padx=7, pady=(2, 1))
        entries = [
            ("name", "Device"), ("manufacturer", "Manufacturer"),
            ("model", "Model"), ("type", "Type"),
            ("serial", "Serial"), ("logical_target_id", "Logical ID"),
            ("physical_uid", "Physical UID"), ("bus", "Bus"),
            ("interface", "Interface"), ("method", "Acquisition"),
            ("capability", "Capability"), ("access", "Access"),
            ("jedec", "JEDEC"), ("size", "Firmware size"),
            ("bios_vendor", "BIOS vendor"), ("bios_version", "BIOS version"),
            ("bios_date", "BIOS date"), ("uefi_version", "UEFI"),
            ("architecture", "Architecture"), ("cpu", "CPU"),
            ("sku", "SKU"), ("asset_tag", "Asset tag"),
            ("uuid", "UUID"), ("build_id", "Build ID"),
            ("reference_state", "Reference"),
        ]
        for i, (key, label) in enumerate(entries):
            row, col = divmod(i, 2)
            tk.Label(grid, text=f"{label}:", bg=PANEL, fg=CARD_MUTED, font=("TkDefaultFont", 7, "bold")).grid(row=row, column=col*2, sticky="nw", padx=(0, 3), pady=1)
            tk.Label(grid, textvariable=self.target_detail_vars[key], bg=PANEL, fg=CARD_TEXT, font=("TkDefaultFont", 9), wraplength=145, justify="left").grid(row=row, column=col*2+1, sticky="nw", padx=(0, 7), pady=1)
            grid.grid_columnconfigure(col*2+1, weight=1, minsize=75)

        action = tk.Frame(detail, bg=PANEL)
        action.pack(fill="x", padx=7, pady=(3, 4))
        self.target_scan_button = tk.Button(action, text="SCAN FIRMWARE", command=self.scan_selected, bg="#e7f2eb", fg=GREEN, activebackground="#d8e8dc", activeforeground=GREEN, relief="solid", borderwidth=1, font=("TkDefaultFont", 8, "bold"), state="disabled")
        self.target_scan_button.pack(side="left")
        self.target_hint_var = tk.StringVar(value="Select a connected device.")
        tk.Label(action, textvariable=self.target_hint_var, bg=PANEL, fg=CARD_MUTED, font=("TkDefaultFont", 8), wraplength=500, justify="left").pack(side="left", padx=7)


    # ------------------------------------------------------------------- Scan page
    def _build_scan(self) -> None:
        frame = self._new_page("Scan")
        self._title(frame, "FIRMWARE SCAN", "Live state from the real acquisition / STM32 scan pipeline.")

        meta = self._card(frame, "Scan session")
        meta.pack(fill="x", pady=(0, 6))
        vars_ = [
            ("scan_target_var", "Target: N/A"), ("scan_iface_var", "Interface: N/A"),
            ("scan_status_var", "Status: IDLE"), ("scan_result_var", "Result: N/A"),
            ("scan_size_var", "Firmware size: N/A"), ("scan_duration_var", "Duration: N/A"),
        ]
        self.scan_target_var = tk.StringVar(value=vars_[0][1]); self.scan_iface_var = tk.StringVar(value=vars_[1][1])
        self.scan_status_var = tk.StringVar(value=vars_[2][1]); self.scan_result_var = tk.StringVar(value=vars_[3][1])
        self.scan_size_var = tk.StringVar(value=vars_[4][1]); self.scan_duration_var = tk.StringVar(value=vars_[5][1])
        meta_grid = tk.Frame(meta, bg=PANEL); meta_grid.pack(fill="x", padx=8, pady=(2, 6))
        allv = [self.scan_target_var, self.scan_iface_var, self.scan_status_var, self.scan_result_var, self.scan_size_var, self.scan_duration_var]
        for i, var in enumerate(allv):
            r,c=divmod(i,2)
            tk.Label(meta_grid, textvariable=var, bg=PANEL, fg=CARD_TEXT, font=("TkDefaultFont", 8), anchor="w").grid(row=r,column=c,sticky="ew",padx=(0,8),pady=2)
            meta_grid.grid_columnconfigure(c, weight=1)

        progress_card = self._card(frame, "Progress")
        progress_card.pack(fill="x", pady=(0, 6))
        self.scan_stage_var = tk.StringVar(value="IDLE")
        self.scan_bytes_var = tk.StringVar(value="0 / 0 bytes")
        self.scan_progress = ttk.Progressbar(progress_card, style="FIVSED.Horizontal.TProgressbar", mode="determinate", maximum=100, value=0)
        self.scan_progress.pack(fill="x", padx=8, pady=(5, 4))
        row = tk.Frame(progress_card, bg=PANEL); row.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(row, textvariable=self.scan_stage_var, bg=PANEL, fg=CYAN, font=("TkDefaultFont", 8, "bold"), wraplength=290, justify="left").pack(side="left")
        tk.Label(row, textvariable=self.scan_bytes_var, bg=PANEL, fg=CARD_MUTED, font=("TkDefaultFont", 9)).pack(side="right")

        self.scan_steps = tk.StringVar(value="TARGET SELECTED → ACQUIRING FIRMWARE → STREAMING TO STM32 → STM32 CALCULATING SHA-256 → VERIFYING REFERENCE → RESULT RECEIVED")
        tk.Label(frame, textvariable=self.scan_steps, bg=BG, fg=MUTED, wraplength=440, justify="left", font=("TkDefaultFont", 9)).pack(fill="x", pady=(0, 6))

        result_card = self._card(frame, "Integrity result")
        result_card.pack(fill="both", expand=True)
        self.result_title_var = tk.StringVar(value="NO RESULT")
        self.result_reason_var = tk.StringVar(value="Start a scan from the Targets page.")
        self.result_title_label = tk.Label(result_card, textvariable=self.result_title_var, bg=PANEL, fg=CARD_TEXT, font=("TkDefaultFont", 14, "bold"))
        self.result_title_label.pack(anchor="w", padx=8, pady=(5, 1))
        tk.Label(result_card, textvariable=self.result_reason_var, bg=PANEL, fg=CARD_TEXT, wraplength=440, justify="left", font=("TkDefaultFont", 9)).pack(anchor="w", padx=8, pady=(0, 5))


    # ---------------------------------------------------------------- History page
    def _build_history(self) -> None:
        frame = self._new_page("History")
        top = tk.Frame(frame, bg=BG); top.pack(fill="x")
        self._title(top, "SCAN HISTORY", "Only completed scan events stored locally from the FIVSED runtime are shown.")
        tk.Button(top, text="REFRESH", command=self.refresh_history, bg=ACCENT, fg=TEXT, activebackground="#d9e3ea", activeforeground=TEXT, relief="solid", borderwidth=1, font=("TkDefaultFont", 8, "bold")).pack(side="right", pady=(0,5))
        card = self._card(frame, "Audit records"); card.pack(fill="both", expand=True)
        wrap = tk.Frame(card, bg=PANEL); wrap.pack(fill="both", expand=True, padx=5, pady=5)
        cols=("time","target","size","result","duration","stm")
        self.history_tree=ttk.Treeview(wrap,columns=cols,show="headings",style="FIVSED.Treeview",selectmode="browse")
        heads={"time":"TIME","target":"TARGET","size":"SIZE","result":"RESULT","duration":"DURATION","stm":"STM32"}
        widths={"time":105,"target":85,"size":55,"result":92,"duration":60,"stm":55}
        for col in cols:
            self.history_tree.heading(col,text=heads[col]); self.history_tree.column(col,width=widths[col],minwidth=40,anchor="w",stretch=False)
        # Touch-friendly vertical scrollbar: keep it visible beside the history list
        # so additional reports can always be reached on the 480x800 panel.
        self.history_vscroll=tk.Scrollbar(
            wrap,
            orient="vertical",
            command=self.history_tree.yview,
            width=18,
            bg="#d7dfe5",
            troughcolor="#ffffff",
            activebackground="#9ba8b2",
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.history_tree.configure(yscrollcommand=self.history_vscroll.set)
        self.history_tree.pack(side="left",fill="both",expand=True)
        self.history_vscroll.pack(side="right",fill="y")

        def _history_wheel(event):
            delta = -1 if getattr(event, "delta", 0) > 0 else 1
            self.history_tree.yview_scroll(delta, "units")
            return "break"
        self.history_tree.bind("<MouseWheel>", _history_wheel)
        self.history_tree.bind("<Button-4>", lambda _e: self.history_tree.yview_scroll(-3, "units"))
        self.history_tree.bind("<Button-5>", lambda _e: self.history_tree.yview_scroll(3, "units"))


    # ---------------------------------------------------------------- System page
    def _build_system(self) -> None:
        frame=self._new_page("System")
        top=tk.Frame(frame,bg=BG); top.pack(fill="x")
        self._title(top,"SYSTEM","Live Raspberry Pi / Windows host information. No platform values are hard-coded.")
        tk.Button(top,text="REFRESH",command=self.refresh_system,bg=ACCENT,fg=TEXT,activebackground="#d9e3ea",activeforeground=TEXT,relief="solid",borderwidth=1,font=("TkDefaultFont",8,"bold")).pack(side="right",pady=(0,5))
        card=self._card(frame,"Host status"); card.pack(fill="both",expand=True)
        self.system_text=tk.Text(card,bg=PANEL_2,fg=CARD_TEXT,insertbackground=CARD_TEXT,selectbackground="#dce9f2",selectforeground=CARD_TEXT,relief="solid",borderwidth=1,highlightthickness=0,font=("Courier",10),wrap="none")
        self.system_text.pack(fill="both",expand=True,padx=6,pady=6); self.system_text.configure(state="disabled")


    # ------------------------------------------------------------------ Logs page
    def _build_logs(self) -> None:
        frame=self._new_page("Logs")
        top=tk.Frame(frame,bg=BG); top.pack(fill="x")
        self._title(top,"EVENT LOG","Runtime observations, acquisition events, STM32 results and communication faults.")
        tk.Button(top,text="REFRESH",command=self.refresh_logs,bg=ACCENT,fg=TEXT,activebackground="#d9e3ea",activeforeground=TEXT,relief="solid",borderwidth=1,font=("TkDefaultFont",8,"bold")).pack(side="right",pady=(0,5))
        card=self._card(frame,"Live log"); card.pack(fill="both",expand=True)
        wrap=tk.Frame(card,bg=PANEL_2)
        wrap.pack(fill="both",expand=True,padx=6,pady=6)
        self.logs_text=tk.Text(wrap,bg=PANEL_2,fg=CARD_TEXT,insertbackground=CARD_TEXT,selectbackground="#dce9f2",selectforeground=CARD_TEXT,relief="solid",borderwidth=1,highlightthickness=0,font=("Courier",10),wrap="none")
        self.logs_vscroll=ttk.Scrollbar(wrap,orient="vertical",command=self.logs_text.yview)
        self.logs_hscroll=ttk.Scrollbar(wrap,orient="horizontal",command=self.logs_text.xview)
        self.logs_text.configure(yscrollcommand=self.logs_vscroll.set,xscrollcommand=self.logs_hscroll.set)
        self.logs_text.grid(row=0,column=0,sticky="nsew")
        self.logs_vscroll.grid(row=0,column=1,sticky="ns")
        self.logs_hscroll.grid(row=1,column=0,sticky="ew")
        wrap.grid_rowconfigure(0,weight=1)
        wrap.grid_columnconfigure(0,weight=1)
        self.logs_text.configure(state="disabled")


    def _show_page(self, name: str) -> None:
        self.current_page = name
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[name].pack(fill="both", expand=True)
        for button_name, btn in self.page_buttons.items():
            active = button_name == name
            btn.configure(bg=ACCENT if active else BG, fg=TEXT)
        if name == "History":
            self.refresh_history()
        elif name == "Logs":
            self.refresh_logs()
        elif name == "System":
            self.refresh_system()

    # -------------------------------------------------------------- Refresh logic
    def _initial_refresh(self) -> None:
        self.request_refresh()
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._closing:
            return
        self.root.after(REFRESH_MS, self._poll_tick)

    def _poll_tick(self) -> None:
        self.request_refresh()
        if self.active_scan_id:
            self._poll_scan()
        self._schedule_poll()

    def request_refresh(self) -> None:
        if self._refresh_running or self._closing:
            return
        self._refresh_running = True
        self.statusbar.configure(text="Refreshing real hardware discovery…")
        threading.Thread(target=self._refresh_worker, daemon=True, name="fivsed-gui-refresh").start()

    def _refresh_worker(self) -> None:
        try:
            targets = hardware_reader.detect_connected_targets()
            components = get_component_status()
            pi = get_pi_status()
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self._refresh_failed(e))
            return
        self.root.after(0, lambda: self._apply_refresh(targets, components, pi))

    def _refresh_failed(self, reason: str) -> None:
        self._refresh_running = False
        if self._closing:
            return
        self.statusbar.configure(text=f"Hardware refresh error: {reason}")
        self._update_component_header(None, None, None)

    def _apply_refresh(self, targets: list[dict[str, Any]], components: dict[str, Any], pi: dict[str, Any]) -> None:
        self._refresh_running = False
        if self._closing:
            return
        previous_ids = {item.get("id") for item in self.targets}
        current_ids = {item.get("id") for item in targets}
        self.targets = targets
        self._render_target_tree()
        self._update_component_header(components, pi, targets)

        if previous_ids != current_ids:
            self.statusbar.configure(text=f"Detected {len(targets)} connected device(s).")
        else:
            self.statusbar.configure(text=f"Discovery refreshed at {time.strftime('%H:%M:%S')}. {len(targets)} connected device(s).")
        self._update_selected_target_from_refresh()

    def _update_component_header(self, components: Optional[dict[str, Any]], pi: Optional[dict[str, Any]], targets: Optional[list[dict[str, Any]]]) -> None:
        if components:
            pi = components.get("raspberry_pi", {})
            stm = components.get("stm32", {})
            esp = components.get("esp32", {})
            self._set_status_var(self.pi_var, "PI", bool(pi.get("connected")))
            self._set_status_var(self.stm_var, "STM32", bool(stm.get("connected")))
            self._set_status_var(self.esp_var, "ESP32", bool(esp.get("connected")))
        else:
            self.pi_var.set("PI: UNKNOWN")
            self.stm_var.set("STM32: UNKNOWN")
            self.esp_var.set("ESP32: UNKNOWN")

    def _set_status_var(self, var: tk.StringVar, name: str, connected: bool) -> None:
        var.set(f"{name}: {'CONNECTED' if connected else 'DISCONNECTED'}")

    def _render_target_tree(self) -> None:
        for item in self.target_tree.get_children():
            self.target_tree.delete(item)
        for target in self.targets:
            tid = str(target.get("id", ""))
            capability = str(target.get("capability") or target.get("acquisition_method") or "ACQUISITION_UNSUPPORTED")
            self.target_tree.insert("", "end", iid=tid, values=(
                target.get("name", "N/A"),
                target.get("type", "N/A"),
                target.get("status", "CONNECTED"),
                capability,
            ))
        if self.targets:
            self.no_targets_label.place_forget()
        else:
            self.no_targets_label.place(relx=0.5, rely=0.5, anchor="center")

    def _update_selected_target_from_refresh(self) -> None:
        if not self.selected_target:
            return
        tid = self.selected_target.get("id")
        match = next((item for item in self.targets if item.get("id") == tid), None)
        if match is None:
            self.selected_target = None
            self._clear_target_detail()
            return
        self.selected_target = match
        self._display_target_detail(match)

    # --------------------------------------------------------------- Target select
    def _on_target_selected(self, _event: tk.Event) -> None:
        selection = self.target_tree.selection()
        if not selection:
            return
        tid = selection[0]
        target = next((item for item in self.targets if item.get("id") == tid), None)
        if target is None:
            return
        self.selected_target = target
        self._display_target_detail(target)
        self._show_page("Targets")

    def _display_target_detail(self, target: dict[str, Any]) -> None:
        mapping = {
            "name": target.get("friendly_name") or target.get("name"),
            "manufacturer": target.get("manufacturer"),
            "model": target.get("model"),
            "type": target.get("type"),
            "vid": target.get("vid"),
            "pid": target.get("pid"),
            "serial": target.get("serial"),
            "logical_target_id": target.get("logical_target_id"),
            "physical_uid": target.get("physical_uid"),
            "bus": target.get("bus"),
            "interface": target.get("interface"),
            "method": target.get("acquisition_method"),
            "capability": target.get("capability"),
            "access": target.get("firmware_access"),
            "jedec": target.get("jedec"),
            "size": self._format_bytes(target.get("firmware_size")),
            "bios_vendor": target.get("bios_vendor"),
            "bios_version": target.get("bios_version"),
            "bios_date": target.get("bios_date"),
            "uefi_version": target.get("uefi_version"),
            "architecture": target.get("architecture"),
            "cpu": target.get("cpu"),
            "sku": target.get("sku"),
            "asset_tag": target.get("asset_tag"),
            "uuid": target.get("uuid"),
            "build_id": target.get("build_id"),
            "reference_state": "STORED IN STM32" if target.get("registered") else "NOT REGISTERED",
        }
        for key, value in mapping.items():
            self.target_detail_vars[key].set(str(value if value not in (None, "") else "N/A"))

        acquisition_supported = target.get("status") == "CONNECTED" and target.get("capability") in {"ACQUISITION_SUPPORTED", "CAPABILITY_PROBE"}
        stm32_available = bool(stm32_link.connected)
        scan_ready = acquisition_supported and stm32_available
        scan_running = self.active_scan_id is not None
        self.target_scan_button.configure(state="normal" if scan_ready and not scan_running else "disabled")
        if target.get("status") != "CONNECTED":
            hint = "Target is disconnected."
        elif not stm32_available:
            hint = "STM32 security authority is not connected. Connect the STM32 USB CDC link before scanning; target metadata can still be viewed."
        elif scan_ready and target.get("registered"):
            hint = "Trusted reference is stored inside STM32. SCAN FIRMWARE will compare the new measurement with the stored reference."
        elif scan_ready and target.get("capability") == "CAPABILITY_PROBE":
            hint = "Supported acquisition provider will probe the real firmware interface on scan. For a new target, use the physical STM32 REGISTER action before first provisioning."
        elif scan_ready:
            hint = "New target detected. Use the physical STM32 REGISTER action before first provisioning, then scan to verify."
        elif target.get("firmware_access") == "ACCESS_PROTECTED":
            hint = "Firmware access is protected; no bypass is attempted."
        else:
            hint = "Device detected; firmware acquisition is not supported for this target."
        self.target_hint_var.set(hint)

    def _clear_target_detail(self) -> None:
        for var in self.target_detail_vars.values():
            var.set("N/A")
        self.target_scan_button.configure(state="disabled")
        self.target_hint_var.set("Select a connected device.")

    # ---------------------------------------------------------------- Scan control
    def scan_selected(self) -> None:
        if not self.selected_target:
            return
        if self.active_scan_id:
            return
        target_id = str(self.selected_target.get("id", ""))
        current = next((item for item in self.targets if item.get("id") == target_id), None)
        if current is None or current.get("status") != "CONNECTED":
            messagebox.showwarning("Target unavailable", "The selected target is no longer connected.")
            self.request_refresh()
            return

        self.active_scan_id = None
        self._reset_scan_view(current)
        self._show_page("Scan")
        self.statusbar.configure(text="Starting real firmware acquisition…")
        self.target_scan_button.configure(state="disabled")
        threading.Thread(target=self._start_scan_worker, args=(dict(current),), daemon=True, name="fivsed-gui-scan-start").start()

    def _start_scan_worker(self, target: dict[str, Any]) -> None:
        try:
            scan = stm32_engine.start(target)
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self._scan_start_failed(e))
            return
        self.root.after(0, lambda s=scan: self._scan_started(s))

    def _scan_start_failed(self, reason: str) -> None:
        if self._closing:
            return
        self.active_scan_id = None
        self.result_title_var.set("FIRMWARE ACQUISITION ERROR")
        self.result_reason_var.set(reason)
        self.scan_status_var.set("Status: ERROR")
        self.scan_result_var.set("Result: READ_ERROR")
        self.scan_stage_var.set("ERROR")
        self.flow_var.set("TARGET SELECTED → FIRMWARE ACQUISITION ERROR")
        self.statusbar.configure(text=f"Scan could not start: {reason}")
        self._refresh_target_scan_button()

    def _scan_started(self, scan: dict[str, Any]) -> None:
        self.active_scan_id = scan.get("scan_id")
        self._apply_scan(scan)
        self._poll_scan()

    def _poll_scan(self) -> None:
        scan_id = self.active_scan_id
        if not scan_id or self._closing:
            return
        scan = stm32_engine.get(scan_id)
        if scan:
            self._apply_scan(scan)
            if scan.get("status") == "SCANNING":
                self.root.after(250, self._poll_scan)
            else:
                self.active_scan_id = None
                self._refresh_target_scan_button()
                self._apply_final_result(scan)
                self.request_refresh()

    def _apply_scan(self, scan: dict[str, Any]) -> None:
        self.scan_target_var.set(f"Target: {scan.get('target_name', 'N/A')}")
        self.scan_iface_var.set(f"Interface: {scan.get('interface', 'N/A')}")
        self.scan_status_var.set(f"Status: {scan.get('status', 'N/A')}")
        self.scan_result_var.set(f"Result: {scan.get('result') or 'SCANNING'}")
        self.scan_size_var.set(f"Firmware size: {self._format_bytes(scan.get('total_bytes') or scan.get('firmware_size'))}")
        self.scan_duration_var.set(f"Duration: {self._format_duration(scan.get('duration_ms'))}")
        self.scan_stage_var.set(str(scan.get("stage") or "SCANNING"))
        done = int(scan.get("bytes_processed") or 0)
        total = int(scan.get("total_bytes") or 0)
        self.scan_bytes_var.set(f"{self._format_bytes(done)} / {self._format_bytes(total)}")
        if total > 0:
            self.scan_progress["value"] = max(0, min(100, done * 100.0 / total))
        else:
            self.scan_progress["value"] = 0
        self.flow_var.set(self._flow_for_stage(str(scan.get("stage") or "SCANNING")))
        if scan.get("status") == "SCANNING":
            self.result_title_var.set("SCANNING…")
            self.result_title_label.configure(fg=CYAN)
            self.result_reason_var.set("Waiting for the authoritative STM32 verification response.")

    def _apply_final_result(self, scan: dict[str, Any]) -> None:
        result = str(scan.get("result") or "READ_ERROR")
        reason = str(scan.get("reason") or "")
        title, fg, detail = self._result_presentation(result, reason)
        self.result_title_var.set(title)
        self.result_reason_var.set(detail)
        self.scan_progress["value"] = 100 if result in {"MATCH", "HASH_MISMATCH", "NEW_TARGET_REGISTERED"} and (scan.get("total_bytes") or 0) else self.scan_progress["value"]
        self.statusbar.configure(text=f"STM32 result: {result}")
        self._set_status_visual(result, fg)
        self._show_page("Scan")
        self.refresh_history()
        self.refresh_logs()

    def _result_presentation(self, result: str, reason: str) -> tuple[str, str, str]:
        if result == "MATCH":
            return "INTEGRITY VERIFIED", GREEN, "Firmware measurement matches the STM32 trusted reference. Decision authority: STM32."
        if result == "HASH_MISMATCH":
            return "HASH MISMATCH", RED, "Firmware measurement differs from the trusted reference. TAMPER DETECTED is an integrity alert; it does not identify who or why. Decision authority: STM32."
        if result == "NEW_TARGET_REGISTERED":
            return "NEW TARGET REGISTERED", BLUE, "Trusted reference was stored in STM32 internal flash during controlled physical provisioning. The reference value is not displayed by FIVSED."
        if result == "FIRMWARE_ACCESS_PROTECTED":
            return "FIRMWARE ACCESS PROTECTED", AMBER, reason or "The target prevents firmware acquisition through the supported interface."
        if result == "FIRMWARE_READ_UNSUPPORTED":
            return "FIRMWARE ACQUISITION NOT SUPPORTED", AMBER, reason or "No authorized firmware acquisition provider is available for this target."
        return "FIRMWARE ACQUISITION ERROR", AMBER, reason or "The firmware could not be acquired or the STM32 communication failed."

    def _set_status_visual(self, _result: str, fg: str) -> None:
        # Header remains neutral; the result card carries the decision-specific visual state.
        try:
            self.result_title_label.configure(fg=fg)
        except tk.TclError:
            pass

    def _flow_for_stage(self, stage: str) -> str:
        stages = [
            "TARGET_SELECTED", "ACQUIRING_FIRMWARE", "STREAMING_TO_STM32", "STM32_CALCULATING_SHA256", "VERIFYING_REFERENCE", "RESULT_RECEIVED"
        ]
        if stage not in stages:
            if stage.startswith("FIRMWARE_ACQUISITION"):
                return "TARGET SELECTED → FIRMWARE ACQUISITION NOT SUPPORTED"
            return f"TARGET SELECTED → {stage}"
        index = stages.index(stage)
        labels = ["TARGET SELECTED", "ACQUIRING FIRMWARE", "STREAMING TO STM32", "STM32 CALCULATING SHA-256", "VERIFYING REFERENCE", "RESULT RECEIVED"]
        return "  →  ".join(labels[: index + 1])

    def _reset_scan_view(self, target: dict[str, Any]) -> None:
        self.scan_target_var.set(f"Target: {target.get('name', 'N/A')}")
        self.scan_iface_var.set(f"Interface: {target.get('interface', 'N/A')}")
        self.scan_status_var.set("Status: STARTING")
        self.scan_result_var.set("Result: N/A")
        self.scan_size_var.set(f"Firmware size: {self._format_bytes(target.get('firmware_size'))}")
        self.scan_duration_var.set("Duration: N/A")
        self.scan_stage_var.set("TARGET_SELECTED")
        self.scan_bytes_var.set("0 / 0 bytes")
        self.scan_progress["value"] = 0
        self.result_title_var.set("SCANNING…")
        self.result_reason_var.set("Target selected. The application will acquire real firmware bytes and forward them to the STM32.")
        self.flow_var.set("TARGET SELECTED → ACQUIRING FIRMWARE → STREAMING TO STM32 → STM32 CALCULATING SHA-256 → VERIFYING REFERENCE → RESULT RECEIVED")

    def _refresh_target_scan_button(self) -> None:
        if self.selected_target:
            self._display_target_detail(self.selected_target)

    # --------------------------------------------------------------- Data pages
    def refresh_history(self) -> None:
        records = storage.get_history(50)
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for record in records:
            self.history_tree.insert("", "end", values=(
                record.get("created_at") or record.get("timestamp") or "N/A",
                record.get("target_name") or record.get("target_id") or "N/A",
                self._format_bytes(record.get("firmware_size")),
                record.get("result") or "N/A",
                self._format_duration(record.get("duration_ms")),
                record.get("stm32_status") or "N/A",
            ))

    def refresh_logs(self) -> None:
        logs = storage.get_logs(100)
        self.logs_text.configure(state="normal")
        self.logs_text.delete("1.0", "end")
        if logs:
            for item in logs:
                line = f"{item.get('timestamp', 'N/A')} | {item.get('level', 'INFO'):9} | {item.get('module', 'SYSTEM'):16} | {item.get('message', '')}\n"
                self.logs_text.insert("end", line)
        else:
            self.logs_text.insert("end", "No events recorded.\n")
        self.logs_text.configure(state="disabled")

    def refresh_system(self) -> None:
        threading.Thread(target=self._system_worker, daemon=True, name="fivsed-gui-system").start()

    def _system_worker(self) -> None:
        try:
            info = get_pi_status()
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self._write_system(f"Unable to read system information: {e}"))
            return
        lines = [
            f"PLATFORM             {info.get('platform', 'N/A')}",
            f"HOSTNAME             {info.get('hostname', 'N/A')}",
            f"MODEL                {info.get('model', 'N/A')}",
            f"OS                   {info.get('os', 'N/A')}",
            f"KERNEL               {info.get('kernel', 'N/A')}",
            f"ARCHITECTURE         {info.get('architecture', 'N/A')}",
            f"CPU                  {info.get('cpu', 'N/A')}",
            f"CPU COUNT            {info.get('cpu_count', 'N/A')}",
            f"CPU LOAD             {self._format_number(info.get('cpu_load_percent'), '%')}",
            f"MEMORY TOTAL         {self._format_number(info.get('memory_total_mb'), ' MB')}",
            f"MEMORY AVAILABLE     {self._format_number(info.get('memory_available_mb'), ' MB')}",
            f"DISK TOTAL           {self._format_number(info.get('disk_total_gb'), ' GB')}",
            f"DISK FREE            {self._format_number(info.get('disk_free_gb'), ' GB')}",
            f"TEMPERATURE          {self._format_number(info.get('temperature_c'), ' °C')}",
            f"UPTIME               {info.get('uptime', 'N/A')}",
            "",
            f"SERIAL INTERFACES    {', '.join(info.get('serial_interfaces') or []) or 'N/A'}",
            f"SPI INTERFACES       {', '.join(info.get('spi_interfaces') or []) or 'N/A'}",
        ]
        self.root.after(0, lambda t="\n".join(lines): self._write_system(t))

    def _write_system(self, text: str) -> None:
        if self._closing:
            return
        self.system_text.configure(state="normal")
        self.system_text.delete("1.0", "end")
        self.system_text.insert("end", text)
        self.system_text.configure(state="disabled")

    # ---------------------------------------------------------------- Utilities
    @staticmethod
    def _format_bytes(value: Any) -> str:
        if value in (None, "", "N/A"):
            return "N/A"
        try:
            n = int(value)
        except (TypeError, ValueError):
            return str(value)
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KiB"
        if n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.2f} MiB"
        return f"{n / (1024 * 1024 * 1024):.2f} GiB"

    @staticmethod
    def _format_duration(ms: Any) -> str:
        if ms in (None, "", "N/A"):
            return "N/A"
        try:
            value = int(ms)
        except (TypeError, ValueError):
            return str(ms)
        if value < 1000:
            return f"{value} ms"
        return f"{value / 1000.0:.2f} s"

    @staticmethod
    def _format_number(value: Any, suffix: str) -> str:
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.1f}{suffix}"
        except (TypeError, ValueError):
            return f"{value}{suffix}"

    def _apply_fullscreen_geometry(self) -> None:
        if self._closing:
            return
        try:
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()
            # Raspberry Pi appliance target: 90° counter-clockwise display rotation -> 480×800.
            self.root.overrideredirect(True)
            self.root.geometry(f"{width}x{height}+0+0")
            self.root.attributes("-fullscreen", True)
        except tk.TclError:
            pass

    def close(self) -> None:
        self._closing = True
        try:
            stm32_link.close()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        raise SystemExit(
            "FIVSED Tkinter desktop requires a graphical display (DISPLAY). "
            "Install a lightweight desktop/X server on Raspberry Pi OS Lite or run it from an existing desktop session."
        )
    root = tk.Tk()
    FIVSEDDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
