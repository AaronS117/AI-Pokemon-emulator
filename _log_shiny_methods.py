"""
Temporary file – paste these two methods into app.py before _open_settings.
Delete this file after merging.
"""

# ─────────────────────────────────────────────────────────────────────
#  LOG WINDOW
# ─────────────────────────────────────────────────────────────────────

def _open_log_window(self):
    """Open a floating live log window showing all app/AI/bot activity."""
    if hasattr(self, "_log_win"):
        try:
            if self._log_win.winfo_exists():
                self._log_win.lift()
                self._log_win.focus_set()
                return
        except Exception:
            pass

    win = ctk.CTkToplevel(self)
    win.title("Live Log – Gen 3 Shiny Hunter")
    win.geometry("900x560+60+60")
    win.configure(fg_color=C["bg_dark"])
    self._log_win = win

    # ── Toolbar ──────────────────────────────────────────────────────
    toolbar = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=40)
    toolbar.pack(fill="x")
    toolbar.pack_propagate(False)

    ctk.CTkLabel(toolbar, text="LIVE LOG",
                 font=ctk.CTkFont(size=13, weight="bold"),
                 text_color=C["accent"]).pack(side="left", padx=12)

    # Level filter
    _level_var = ctk.StringVar(value="ALL")
    ctk.CTkLabel(toolbar, text="Level:", font=ctk.CTkFont(size=11),
                 text_color=C["text_dim"]).pack(side="left", padx=(12, 4))
    ctk.CTkOptionMenu(toolbar, variable=_level_var,
                      values=["ALL", "DEBUG", "INFO", "WARNING", "ERROR"],
                      width=90, height=26,
                      fg_color=C["bg_input"], button_color=C["accent"],
                      button_hover_color=C["accent_h"],
                      dropdown_fg_color=C["bg_card"],
                      font=ctk.CTkFont(size=11)).pack(side="left")

    # Search
    _search_var = ctk.StringVar()
    ctk.CTkLabel(toolbar, text="Filter:", font=ctk.CTkFont(size=11),
                 text_color=C["text_dim"]).pack(side="left", padx=(12, 4))
    ctk.CTkEntry(toolbar, textvariable=_search_var, width=160, height=26,
                 fg_color=C["bg_input"], border_color=C["border"],
                 font=ctk.CTkFont(size=11)).pack(side="left")

    # Auto-scroll toggle
    _autoscroll = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(toolbar, text="Auto-scroll", variable=_autoscroll,
                    font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                    fg_color=C["accent"], hover_color=C["accent_h"],
                    border_color=C["border"], width=20).pack(side="left", padx=12)

    # Clear button
    def _clear_log():
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.configure(state="disabled")

    ctk.CTkButton(toolbar, text="Clear", width=60, height=26,
                  font=ctk.CTkFont(size=11),
                  fg_color=C["bg_dark"], hover_color=C["red"],
                  border_width=1, border_color=C["border"],
                  command=_clear_log).pack(side="right", padx=8)

    # Export button
    def _export_log():
        import tkinter.filedialog as fd
        path = fd.asksaveasfilename(
            title="Export Log", defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            txt.configure(state="normal")
            content = txt.get("1.0", "end")
            txt.configure(state="disabled")
            Path(path).write_text(content, encoding="utf-8")

    ctk.CTkButton(toolbar, text="Export", width=65, height=26,
                  font=ctk.CTkFont(size=11),
                  fg_color=C["bg_dark"], hover_color=C["accent"],
                  border_width=1, border_color=C["border"],
                  command=_export_log).pack(side="right", padx=(0, 4))

    # ── Text area ─────────────────────────────────────────────────────
    txt = ctk.CTkTextbox(win, fg_color="#0a0a0a", text_color=C["text"],
                         font=ctk.CTkFont(family="Courier New", size=11),
                         wrap="word", state="disabled")
    txt.pack(fill="both", expand=True, padx=0, pady=0)

    # Color tags
    txt.tag_config("DEBUG",   foreground="#6b7280")
    txt.tag_config("INFO",    foreground="#e2e8f0")
    txt.tag_config("WARNING", foreground="#eab308")
    txt.tag_config("ERROR",   foreground="#ef4444")
    txt.tag_config("CRITICAL",foreground="#ff0000")
    txt.tag_config("SHINY",   foreground="#fbbf24")
    txt.tag_config("WORKER",  foreground="#7c3aed")
    txt.tag_config("AI",      foreground="#22c55e")

    # ── Status bar ────────────────────────────────────────────────────
    status_bar = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=24)
    status_bar.pack(fill="x", side="bottom")
    status_bar.pack_propagate(False)
    _line_count_lbl = ctk.CTkLabel(status_bar, text="0 lines",
                                   font=ctk.CTkFont(size=10),
                                   text_color=C["text_dim"])
    _line_count_lbl.pack(side="right", padx=8)
    _queue_lbl = ctk.CTkLabel(status_bar, text="Queue: 0",
                              font=ctk.CTkFont(size=10),
                              text_color=C["text_dim"])
    _queue_lbl.pack(side="left", padx=8)

    _line_count = [0]

    def _get_tag(line: str) -> str:
        if "[DEBUG   ]" in line:
            return "DEBUG"
        if "[WARNING ]" in line or "[WARNING]" in line:
            return "WARNING"
        if "[ERROR   ]" in line or "[ERROR]" in line or "[CRITICAL]" in line:
            return "ERROR"
        if "worker." in line or "Worker" in line:
            return "WORKER"
        if "ai." in line or "AI" in line:
            return "AI"
        if "SHINY" in line or "shiny" in line:
            return "SHINY"
        return "INFO"

    MAX_LINES = 2000

    def _poll_log():
        if not win.winfo_exists():
            return
        level_filter = _level_var.get()
        search_filter = _search_var.get().lower()
        batch = []
        try:
            for _ in range(200):  # drain up to 200 per tick
                batch.append(_log_queue.get_nowait())
        except queue.Empty:
            pass

        if batch:
            txt.configure(state="normal")
            for line in batch:
                # Level filter
                if level_filter != "ALL":
                    if f"[{level_filter}" not in line and f"[{level_filter.ljust(8)}]" not in line:
                        continue
                # Search filter
                if search_filter and search_filter not in line.lower():
                    continue
                tag = _get_tag(line)
                txt.insert("end", line + "\n", tag)
                _line_count[0] += 1

            # Trim to MAX_LINES
            if _line_count[0] > MAX_LINES:
                txt.delete("1.0", f"{_line_count[0] - MAX_LINES}.0")
                _line_count[0] = MAX_LINES

            txt.configure(state="disabled")
            if _autoscroll.get():
                txt.see("end")
            _line_count_lbl.configure(text=f"{_line_count[0]:,} lines")

        _queue_lbl.configure(text=f"Queue: {_log_queue.qsize()}")
        win.after(100, _poll_log)

    _poll_log()
    logger.info("Log window opened")


# ─────────────────────────────────────────────────────────────────────
#  SHINY MATH WINDOW
# ─────────────────────────────────────────────────────────────────────

def _open_shiny_math(self):
    """Show shiny/perfect IV math for all running instances."""
    win = ctk.CTkToplevel(self)
    win.title("Shiny & Perfect IV Math")
    win.geometry("720x580")
    win.configure(fg_color=C["bg_dark"])
    win.resizable(True, True)

    ctk.CTkLabel(win, text="SHINY & PERFECT IV CALCULATOR",
                 font=ctk.CTkFont(size=15, weight="bold"),
                 text_color=C["accent"]).pack(anchor="w", padx=16, pady=(12, 4))

    ctk.CTkLabel(win,
                 text="Gen 3 shiny formula:  (TID XOR SID XOR PID_high16 XOR PID_low16) < 8\n"
                      "Perfect IVs come from specific PIDs — shown below per instance.",
                 font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                 justify="left").pack(anchor="w", padx=16, pady=(0, 8))

    scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg_dark"])
    scroll.pack(fill="both", expand=True, padx=8, pady=8)

    from modules.tid_engine import TrainerID as _TID

    if not self.instances:
        ctk.CTkLabel(scroll, text="No instances running yet.\nStart instances to see their shiny math.",
                     font=ctk.CTkFont(size=13), text_color=C["text_dim"],
                     justify="center").pack(pady=40)
        return

    for iid, state in self.instances.items():
        tid_obj = _TID(seed=state.seed, tid=state.tid, sid=state.sid)
        xor_val = state.tid ^ state.sid

        card = ctk.CTkFrame(scroll, fg_color=C["bg_card"],
                            corner_radius=8, border_width=1, border_color=C["border"])
        card.pack(fill="x", pady=4, padx=4)

        # Header
        hdr = ctk.CTkFrame(card, fg_color=C["bg_input"], corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr,
                     text=f"Instance #{iid}  |  seed=0x{state.seed:04X}  TID={state.tid:05d}  SID={state.sid:05d}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=12, pady=6)
        ctk.CTkLabel(hdr,
                     text=f"TID^SID = 0x{xor_val:04X}",
                     font=ctk.CTkFont(size=11),
                     text_color=C["accent"]).pack(side="right", padx=12)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=8)

        # Formula explanation
        ctk.CTkLabel(body,
                     text=f"Shiny condition:  (0x{state.tid:04X} ^ 0x{state.sid:04X} ^ PID>>16 ^ PID&0xFFFF) < 8",
                     font=ctk.CTkFont(family="Courier New", size=11),
                     text_color=C["text_dim"]).pack(anchor="w")

        # Probability
        prob_1_in = 8192
        ctk.CTkLabel(body,
                     text=f"Base shiny odds: 1 in {prob_1_in:,}  ({100/prob_1_in:.4f}%)",
                     font=ctk.CTkFont(size=11), text_color=C["yellow"]).pack(anchor="w", pady=(4, 0))

        # Scan first 64K PIDs for shiny ones and show first 16
        shiny_pids = []
        for pv in range(0, 0x10000):
            full_pv = (pv << 16) | pv  # simplified scan
            if tid_obj.is_shiny_pid(full_pv):
                shiny_pids.append(f"0x{full_pv:08X}")
            if len(shiny_pids) >= 16:
                break

        ctk.CTkLabel(body,
                     text=f"Sample shiny PIDs (first 16 found in low range):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(8, 2))

        pid_grid = ctk.CTkFrame(body, fg_color="transparent")
        pid_grid.pack(anchor="w")
        for i, pid_str in enumerate(shiny_pids):
            ctk.CTkLabel(pid_grid, text=pid_str,
                         font=ctk.CTkFont(family="Courier New", size=10),
                         text_color=C["gold"],
                         width=110).grid(row=i // 4, column=i % 4, padx=4, pady=1, sticky="w")

        # Perfect IV note
        ctk.CTkLabel(body,
                     text="Perfect IVs (31/31/31/31/31/31) require specific PID+nature combos.\n"
                          "Use PokeFinder with your TID/SID to find target frames.",
                     font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                     justify="left").pack(anchor="w", pady=(8, 0))

    # Copy TID/SID button
    def _copy_all():
        lines = []
        for iid, state in self.instances.items():
            lines.append(f"Instance {iid}: TID={state.tid} SID={state.sid} seed=0x{state.seed:04X}")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))

    ctk.CTkButton(win, text="Copy all TID/SID to clipboard", width=220, height=30,
                  font=ctk.CTkFont(size=12),
                  fg_color=C["accent"], hover_color=C["accent_h"],
                  command=_copy_all).pack(pady=8)
