"""
modules/ui_instance_card.py
───────────────────────────
Creates and updates the per-instance Toplevel windows.

Public API:
    create_card(app, inst_id, state)
    update_card(app, inst_id, state)
    create_inst_row(app, inst_id, state)
    focus_instance_window(app, inst_id)
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk
from PIL import Image, ImageTk

from modules.app_utils import C as _C_UNUSED, BOT_MODES, detect_monitors

if TYPE_CHECKING:
    from app import App, InstanceState


def create_inst_row(app: "App", inst_id: int, state: "InstanceState"):
    """Compact status row in the main-window scroll frame."""
    C = app.C

    row_frame = ctk.CTkFrame(
        app._scroll_frame, fg_color=C["bg_input"],
        corner_radius=6, border_width=1, border_color=C["border"],
    )
    row_frame.pack(fill="x", pady=3)

    status_lbl = ctk.CTkLabel(
        row_frame, text="BOOTING", width=72,
        font=ctk.CTkFont(size=11, weight="bold"), text_color=C["yellow"],
    )
    status_lbl.pack(side="left", padx=(8, 0), pady=5)

    mode_name = BOT_MODES.get(state.bot_mode, {}).get("label", state.bot_mode)
    ctk.CTkLabel(
        row_frame,
        text=f"Instance #{inst_id}  |  TID:{state.tid}  SID:{state.sid}  |  {mode_name}",
        font=ctk.CTkFont(size=11), text_color=C["text_dim"],
    ).pack(side="left", padx=8)

    metrics_lbl = ctk.CTkLabel(
        row_frame, text="Enc: 0  |  FPS: 0",
        font=ctk.CTkFont(size=11), text_color=C["text"],
    )
    metrics_lbl.pack(side="right", padx=8)

    ctk.CTkButton(
        row_frame, text="Focus", width=70, height=22,
        font=ctk.CTkFont(size=10),
        fg_color=C["bg_dark"], hover_color=C["accent"],
        border_width=1, border_color=C["border"],
        command=lambda: focus_instance_window(app, inst_id),
    ).pack(side="right", padx=(0, 8))

    app._inst_rows[inst_id] = {
        "frame": row_frame,
        "status": status_lbl,
        "metrics": metrics_lbl,
    }


def focus_instance_window(app: "App", inst_id: int):
    w = app._instance_widgets.get(inst_id)
    if w:
        try:
            win = w["win"]
            win.deiconify()
            win.lift()
            win.focus_set()
        except Exception:
            pass


def create_card(app: "App", inst_id: int, state: "InstanceState"):
    """Open a dedicated Toplevel window for this emulator instance."""
    C = app.C

    create_inst_row(app, inst_id, state)

    # DPI-aware sizing
    monitors = detect_monitors()
    primary = monitors[0]
    win_w = max(320, min(520, primary["width"] // 5))
    screen_scale = (win_w - 20) / 240
    screen_h = int(160 * screen_scale)
    win_h = screen_h + 130

    col = (inst_id - 1) % 4
    row_n = (inst_id - 1) // 4
    x_off = primary["x"] + 20 + col * (win_w + 20)
    y_off = primary["y"] + 60 + row_n * (win_h + 30)

    win = ctk.CTkToplevel(app)
    mode_label = BOT_MODES.get(state.bot_mode, {}).get("label", state.bot_mode)
    win.title(f"Instance #{inst_id}  –  {mode_label}")
    win.geometry(f"{win_w}x{win_h}+{x_off}+{y_off}")
    win.configure(fg_color=C["bg_dark"])
    win.resizable(True, True)
    win.minsize(280, 300)

    def _on_close():
        state.request_stop()
        try:
            win.after(200, win.destroy)
        except Exception:
            pass
    win.protocol("WM_DELETE_WINDOW", _on_close)

    # ── Title bar ────────────────────────────────────────────────────────
    title_row = ctk.CTkFrame(win, fg_color=C["bg_input"], corner_radius=0)
    title_row.pack(fill="x")

    status_label = ctk.CTkLabel(
        title_row, text="BOOTING", width=72,
        font=ctk.CTkFont(size=11, weight="bold"), text_color=C["yellow"],
    )
    status_label.pack(side="left", padx=(8, 0), pady=5)

    info_label = ctk.CTkLabel(
        title_row, text=f"#{inst_id}  TID:{state.tid}  SID:{state.sid}",
        font=ctk.CTkFont(size=10), text_color=C["text_dim"],
    )
    info_label.pack(side="left", padx=4)

    btn_box = ctk.CTkFrame(title_row, fg_color="transparent")
    btn_box.pack(side="right", padx=4)

    pause_btn = ctk.CTkButton(
        btn_box, text="Pause", width=46, height=22,
        font=ctk.CTkFont(size=10),
        fg_color=C["yellow"], hover_color="#ca8a04", text_color="#000",
        command=lambda: state.request_pause(),
    )
    pause_btn.pack(side="left", padx=2)

    stop_btn = ctk.CTkButton(
        btn_box, text="Stop", width=46, height=22,
        font=ctk.CTkFont(size=10),
        fg_color=C["red"], hover_color="#dc2626", text_color="#fff",
        command=lambda: state.request_stop(),
    )
    stop_btn.pack(side="left", padx=2)

    # ── Manual / Bot toggle row ───────────────────────────────────────────
    ctrl_row = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0)
    ctrl_row.pack(fill="x")

    ctrl_btn_ref = [None]

    # Bot mode dropdown – only the "Ready" modes
    _ready_modes = {k: v["label"] for k, v in BOT_MODES.items() if v["status"] == "Ready" and k != "manual"}
    _mode_keys   = list(_ready_modes.keys())
    _mode_labels = list(_ready_modes.values())
    _init_bot_mode = state.bot_mode if state.bot_mode in _ready_modes else (_mode_keys[0] if _mode_keys else "encounter_farm")
    _mode_var = ctk.StringVar(value=BOT_MODES.get(_init_bot_mode, {}).get("label", _init_bot_mode))

    def _label_to_key(label: str) -> str:
        for k, v in BOT_MODES.items():
            if v["label"] == label:
                return k
        return "encounter_farm"

    def _set_manual(on: bool):
        state.manual_control = on
        if on:
            state.status = "manual"
            manual_btn.configure(fg_color=C["accent"], text_color="#fff",
                                 border_color=C["accent"])
            bot_btn.configure(fg_color=C["bg_dark"], text_color=C["text_dim"],
                              border_color=C["border"])
            _show_input_overlay(False)
            win.focus_set()
        else:
            # Switch to whichever mode is selected in the dropdown
            chosen = _label_to_key(_mode_var.get())
            state.bot_mode = chosen
            state.manual_control = False
            state.status = "running"
            bot_btn.configure(fg_color=C["accent"], text_color="#fff",
                              border_color=C["accent"])
            manual_btn.configure(fg_color=C["bg_dark"], text_color=C["text_dim"],
                                 border_color=C["border"])
            _show_input_overlay(True)

    _init_manual = state.manual_control or state.bot_mode == "manual"

    manual_btn = ctk.CTkButton(
        ctrl_row, text="🕹 Manual", height=26,
        font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=C["accent"] if _init_manual else C["bg_dark"],
        text_color="#fff" if _init_manual else C["text_dim"],
        hover_color=C["accent_h"], border_width=1,
        border_color=C["accent"] if _init_manual else C["border"],
        command=lambda: _set_manual(True),
    )
    manual_btn.pack(side="left", padx=(6, 2), pady=4)

    bot_btn = ctk.CTkButton(
        ctrl_row, text="🤖 Bot", height=26,
        font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=C["bg_dark"] if _init_manual else C["accent"],
        text_color=C["text_dim"] if _init_manual else "#fff",
        hover_color=C["accent_h"], border_width=1,
        border_color=C["border"] if _init_manual else C["accent"],
        command=lambda: _set_manual(False),
    )
    bot_btn.pack(side="left", padx=(2, 4), pady=4)

    # Mode picker – visible so user can choose which bot mode to resume
    ctk.CTkOptionMenu(
        ctrl_row, variable=_mode_var,
        values=_mode_labels,
        fg_color=C["bg_dark"], button_color=C["accent"],
        button_hover_color=C["accent_h"],
        dropdown_fg_color=C["bg_card"],
        text_color=C["text"], font=ctk.CTkFont(size=10),
        height=26, dynamic_resizing=True,
    ).pack(side="left", fill="x", expand=True, padx=(0, 6), pady=4)

    ctrl_btn_ref[0] = manual_btn
    _ctrl_pair = {"manual": manual_btn, "bot": bot_btn}

    # ── Save path bar ─────────────────────────────────────────────────────
    save_row = ctk.CTkFrame(win, fg_color="#0d1a0d", corner_radius=0)
    save_row.pack(fill="x")
    save_label = ctk.CTkLabel(
        save_row, text="💾  Save: detecting...",
        font=ctk.CTkFont(size=10), text_color="#5a9a5a", anchor="w",
    )
    save_label.pack(fill="x", padx=8, pady=2)

    # ── Screen area ───────────────────────────────────────────────────────
    screen_frame = ctk.CTkFrame(win, fg_color=C["bg_dark"])
    screen_frame.pack(fill="both", expand=True, pady=(2, 0))

    screen_label = ctk.CTkLabel(screen_frame, text="", fg_color=C["bg_dark"])
    screen_label.pack(fill="both", expand=True)

    placeholder = ctk.CTkLabel(
        screen_frame,
        text="Booting…\n\nWaiting for first frame.",
        font=ctk.CTkFont(size=11), text_color=C["text_dim"],
        fg_color="#111111",
    )
    placeholder.pack(fill="both", expand=True)
    placeholder_ref = [placeholder]

    # ── Input-locked overlay (shown until user clicks Manual) ─────────────
    _input_locked = [not _init_manual]  # True = keyboard blocked

    # Semi-transparent glass overlay – fg_color="transparent" lets the game
    # frame show through; the text floats over it.
    input_overlay = ctk.CTkLabel(
        screen_frame,
        text="🔒 Manual  to take control",
        font=ctk.CTkFont(size=11, weight="bold"),
        text_color="#cccccc",
        fg_color="transparent",
        corner_radius=0,
        anchor="s",
    )
    if _input_locked[0]:
        input_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _show_input_overlay(show: bool):
        _input_locked[0] = show
        if show:
            input_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            input_overlay.lift()
        else:
            input_overlay.place_forget()

    # ── Keyboard bindings ─────────────────────────────────────────────────
    _keybinds = app.settings.get("keybinds", {
        "a": "a", "s": "b", "Return": "start", "BackSpace": "select",
        "Up": "up", "Down": "down", "Left": "left", "Right": "right",
        "q": "l", "w": "r",
    })

    def _on_key(event):
        if not state.manual_control:
            return
        btn = _keybinds.get(event.keysym)
        if btn:
            state.send_input(btn)

    win.bind("<KeyPress>", _on_key)
    # Clicking the overlay activates manual mode
    input_overlay.bind("<Button-1>", lambda e: _set_manual(True))
    screen_label.bind("<Button-1>", lambda e: win.focus_set() if state.manual_control else None)

    # ── Metrics bar ───────────────────────────────────────────────────────
    metrics_row = ctk.CTkFrame(win, fg_color=C["bg_input"], corner_radius=0)
    metrics_row.pack(fill="x", side="bottom")

    enc_label = ctk.CTkLabel(metrics_row, text="Enc: 0",
                              font=ctk.CTkFont(size=10), text_color=C["text"], width=80)
    enc_label.pack(side="left", padx=(6, 0), pady=3)

    fps_label = ctk.CTkLabel(metrics_row, text="FPS: 0",
                              font=ctk.CTkFont(size=10), text_color=C["text"], width=80)
    fps_label.pack(side="left")

    frame_label = ctk.CTkLabel(metrics_row, text="Frames: 0",
                                font=ctk.CTkFont(size=10), text_color=C["text_dim"], width=100)
    frame_label.pack(side="left")

    progress = ctk.CTkProgressBar(metrics_row, width=50, height=5,
                                   fg_color=C["border"], progress_color=C["accent"])
    progress.pack(side="right", padx=6)
    progress.set(0)

    app._instance_widgets[inst_id] = {
        "win": win,
        "status": status_label,
        "info": info_label,
        "save_label": save_label,
        "screen": screen_label,
        "placeholder": placeholder_ref,
        "enc": enc_label,
        "fps": fps_label,
        "frames": frame_label,
        "ctrl_btn_ref": ctrl_btn_ref,
        "ctrl_pair": _ctrl_pair,
        "progress": progress,
        "pause": pause_btn,
        "stop": stop_btn,
    }


# ── STATUS MAP (shared) ───────────────────────────────────────────────────────
_STATUS_MAP = {
    "running":     ("RUNNING",  None),   # colour filled from C at call time
    "booting":     ("BOOTING",  None),
    "paused":      ("PAUSED",   None),
    "manual":      ("MANUAL",   None),
    "shiny_found": ("SHINY!",   None),
    "stopped":     ("STOPPED",  None),
    "error":       ("ERROR",    None),
    "idle":        ("IDLE",     None),
    "completed":   ("DONE",     None),
}


def update_card(app: "App", inst_id: int, state: "InstanceState"):
    w = app._instance_widgets.get(inst_id)
    if not w:
        return
    win = w.get("win")
    if win is None:
        return
    try:
        _update_card_inner(app, inst_id, state, w, win)
    except Exception:
        pass  # TclError if Toplevel destroyed mid-refresh


def _update_card_inner(app: "App", inst_id: int, state: "InstanceState", w: dict, win):
    C = app.C

    status_colors = {
        "running": C["green"], "booting": C["yellow"], "paused": C["yellow"],
        "manual": C["accent"], "shiny_found": C["gold"], "stopped": C["red"],
        "error": C["red"], "idle": C["text_dim"], "completed": C["green"],
    }
    status_texts = {
        "running": "RUNNING", "booting": "BOOTING", "paused": "PAUSED",
        "manual": "MANUAL", "shiny_found": "SHINY!", "stopped": "STOPPED",
        "error": "ERROR", "idle": "IDLE", "completed": "DONE",
    }
    text = status_texts.get(state.status, "...")
    color = status_colors.get(state.status, C["text_dim"])
    w["status"].configure(text=text, text_color=color)

    mode_label = BOT_MODES.get(state.bot_mode, {}).get("label", state.bot_mode)
    win.title(f"[{text}] Instance #{inst_id} – {mode_label}")

    if state.status == "error" and state.error:
        w["frames"].configure(text=state.error[:60], text_color=C["red"])
    else:
        w["frames"].configure(
            text=f"F:{state.frame_count:,}  {state.fps:.1f}fps",
            text_color=C["text_dim"])

    w["enc"].configure(text=f"Enc: {state.encounters:,}")
    w["fps"].configure(text=f"FPS: {state.fps:.1f}")

    speed_str = f"{state.speed_multiplier}x" if state.speed_multiplier > 0 else "max"
    info_text = f"#{inst_id}  TID:{state.tid}  SID:{state.sid}  spd:{speed_str}"
    if state.cpu_core >= 0:
        info_text += f"  Core:{state.cpu_core}"
    w["info"].configure(text=info_text)

    if state.status == "running":
        w["progress"].set((state.frame_count % 1000) / 1000)
        w["progress"].configure(progress_color=C["accent"])
    elif state.status == "shiny_found":
        w["progress"].set(1.0)
        w["progress"].configure(progress_color=C["gold"])
    elif state.status == "error":
        w["progress"].set(1.0)
        w["progress"].configure(progress_color=C["red"])

    w["pause"].configure(text="Resume" if state.is_paused else "Pause")
    if state.status in ("stopped", "shiny_found", "error"):
        w["pause"].configure(state="disabled")
        w["stop"].configure(state="disabled")

    # Sync Manual/Bot buttons
    ctrl_pair = w.get("ctrl_pair")
    if ctrl_pair:
        try:
            if state.manual_control:
                ctrl_pair["manual"].configure(fg_color=C["accent"], text_color="#fff",
                                              border_color=C["accent"])
                ctrl_pair["bot"].configure(fg_color=C["bg_dark"], text_color=C["text_dim"],
                                           border_color=C["border"])
            else:
                ctrl_pair["bot"].configure(fg_color=C["accent"], text_color="#fff",
                                           border_color=C["accent"])
                ctrl_pair["manual"].configure(fg_color=C["bg_dark"], text_color=C["text_dim"],
                                              border_color=C["border"])
        except Exception:
            pass

    # Save path label
    save_lbl = w.get("save_label")
    if save_lbl and state.save_path:
        try:
            p = Path(state.save_path)
            has_data = p.exists() and p.stat().st_size > 0
            save_lbl.configure(
                text=f"💾  saves/{p.parent.name}/{p.name}",
                text_color="#5aba5a" if has_data else "#aa6a00",
            )
        except Exception:
            pass

    # Screenshot
    if state.last_screenshot is not None:
        try:
            ph_ref = w.get("placeholder")
            if ph_ref and ph_ref[0] is not None:
                ph_ref[0].pack_forget()
                ph_ref[0] = None

            try:
                ww = w["win"].winfo_width()
                wh = w["win"].winfo_height()
            except Exception:
                ww, wh = 320, 330
            avail_w = max(240, ww - 4)
            avail_h = max(160, wh - 130)
            scale = min(avail_w / 240, avail_h / 160)
            img = state.last_screenshot.resize(
                (int(240 * scale), int(160 * scale)), Image.NEAREST)
            photo = ctk.CTkImage(light_image=img, dark_image=img,
                                 size=(int(240 * scale), int(160 * scale)))
            app._photo_cache[inst_id] = photo
            w["screen"].configure(image=photo, text="")
        except Exception:
            pass

    if state.status == "shiny_found":
        try:
            win.configure(fg_color=C["gold"])
        except Exception:
            pass
