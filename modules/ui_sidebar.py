"""
modules/ui_sidebar.py
─────────────────────
Builds the left sidebar of the main App window.
Keeps all sidebar widget construction out of app.py.

Public API:
    build_sidebar(app, parent)  – called once from App._build_sidebar()
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from modules.config import ENCOUNTER_AREAS, SAVE_DIR
from modules.app_utils import (
    C as _C_DEFAULT,
    BOT_MODES,
    detect_rom_in_dir,
    detect_game_version_from_path,
    save_settings,
)

if TYPE_CHECKING:
    from app import App  # only for type hints, no circular import at runtime

logger = logging.getLogger(__name__)


# ── Collapsible section helper ────────────────────────────────────────────────

def make_collapsible_section(parent, title: str, C: dict, expanded: bool = True):
    """
    Create a collapsible sidebar section.
    Returns the inner body frame to pack widgets into.
    Click the header row to toggle visibility.
    """
    state = {"open": expanded}

    header = ctk.CTkFrame(parent, fg_color=C["bg_input"], corner_radius=6)
    header.pack(fill="x", padx=10, pady=(6, 0))

    arrow = ctk.CTkLabel(header, text="▼" if expanded else "▶",
                         font=ctk.CTkFont(size=11), text_color=C["accent"], width=18)
    arrow.pack(side="left", padx=(8, 2), pady=5)
    ctk.CTkLabel(header, text=title,
                 font=ctk.CTkFont(size=12, weight="bold"),
                 text_color=C["text"]).pack(side="left", pady=5)

    body = ctk.CTkFrame(parent, fg_color="transparent")
    if expanded:
        body.pack(fill="x", padx=4, pady=(0, 2))

    def _toggle(e=None):
        if state["open"]:
            body.pack_forget()
            arrow.configure(text="▶")
        else:
            body.pack(fill="x", padx=4, pady=(0, 2))
            arrow.configure(text="▼")
        state["open"] = not state["open"]

    header.bind("<Button-1>", _toggle)
    for w in header.winfo_children():
        w.bind("<Button-1>", _toggle)

    return body


# ── Main entry point ──────────────────────────────────────────────────────────

def build_sidebar(app: "App", parent):
    """
    Populate the scrollable sidebar frame.
    Attaches all control variables directly onto `app` (e.g. app._rom_var)
    so the rest of app.py can read them exactly as before.
    """
    C = app.C
    _saved_rom = app.settings.get("rom_path", "")
    if not _saved_rom or not Path(_saved_rom).exists():
        from modules.config import EMULATOR_DIR
        _found = detect_rom_in_dir(EMULATOR_DIR)
        if _found:
            _saved_rom = str(_found)
            ver = detect_game_version_from_path(_found)
            app.settings["game_version"] = ver
            logger.info("Auto-detected ROM: %s  version: %s", _found.name, ver)
        if _saved_rom:
            app.settings["rom_path"] = _saved_rom
            save_settings(app.settings)

    # ════════════════════════════════════════════════════════════════════
    #  ACTION BUTTONS  (always visible)
    # ════════════════════════════════════════════════════════════════════
    bf = ctk.CTkFrame(parent, fg_color="transparent")
    bf.pack(fill="x", padx=12, pady=(12, 4))

    app._start_btn = ctk.CTkButton(
        bf, text="▶  START HUNTING",
        font=ctk.CTkFont(size=14, weight="bold"),
        fg_color=C["green"], hover_color="#16a34a",
        text_color="#000000", height=44,
        command=app._start_all,
    )
    app._start_btn.pack(fill="x", pady=(0, 6))

    sub = ctk.CTkFrame(bf, fg_color="transparent")
    sub.pack(fill="x")
    app._stop_btn = ctk.CTkButton(
        sub, text="Stop All",
        fg_color=C["red"], hover_color="#dc2626",
        text_color="#ffffff", height=32,
        command=app._stop_all, state="disabled",
    )
    app._stop_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
    app._pause_btn = ctk.CTkButton(
        sub, text="Pause All",
        fg_color=C["yellow"], hover_color="#ca8a04",
        text_color="#000000", height=32,
        command=app._pause_all, state="disabled",
    )
    app._pause_btn.pack(side="right", expand=True, fill="x", padx=(3, 0))

    # ════════════════════════════════════════════════════════════════════
    #  LIVE STATS  (always visible)
    # ════════════════════════════════════════════════════════════════════
    sf = ctk.CTkFrame(parent, fg_color=C["bg_input"], corner_radius=8)
    sf.pack(fill="x", padx=12, pady=(6, 4))

    r1 = ctk.CTkFrame(sf, fg_color="transparent")
    r1.pack(fill="x", padx=10, pady=(6, 0))
    app._stat_enc = ctk.CTkLabel(r1, text="Enc: 0",
                                  font=ctk.CTkFont(size=12), text_color=C["text"])
    app._stat_enc.pack(side="left")
    app._stat_shiny = ctk.CTkLabel(r1, text="  ✨ 0 shinies",
                                    font=ctk.CTkFont(size=12, weight="bold"),
                                    text_color=C["gold"])
    app._stat_shiny.pack(side="left")

    r2 = ctk.CTkFrame(sf, fg_color="transparent")
    r2.pack(fill="x", padx=10)
    app._stat_enc_rate = ctk.CTkLabel(r2, text="Enc/hr: 0",
                                       font=ctk.CTkFont(size=11), text_color=C["text"])
    app._stat_enc_rate.pack(side="left")
    app._stat_probability = ctk.CTkLabel(r2, text="  Chance: 0%",
                                          font=ctk.CTkFont(size=11), text_color=C["accent"])
    app._stat_probability.pack(side="left")

    r3 = ctk.CTkFrame(sf, fg_color="transparent")
    r3.pack(fill="x", padx=10, pady=(0, 6))
    app._stat_fps = ctk.CTkLabel(r3, text="FPS: 0",
                                  font=ctk.CTkFont(size=11), text_color=C["text_dim"])
    app._stat_fps.pack(side="left")
    app._stat_time = ctk.CTkLabel(r3, text="  Up: 0:00:00",
                                   font=ctk.CTkFont(size=11), text_color=C["text_dim"])
    app._stat_time.pack(side="left")

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: ROM & GAME  (expanded)
    # ════════════════════════════════════════════════════════════════════
    sec_rom = make_collapsible_section(parent, "ROM & GAME", C, expanded=True)

    app._rom_var = ctk.StringVar(value=_saved_rom)
    rf = ctk.CTkFrame(sec_rom, fg_color="transparent")
    rf.pack(fill="x", padx=12, pady=(6, 2))
    ctk.CTkEntry(rf, textvariable=app._rom_var,
                 placeholder_text="Select ROM...",
                 fg_color=C["bg_input"], border_color=C["border"],
                 ).pack(side="left", fill="x", expand=True)
    ctk.CTkButton(rf, text="…", width=34,
                  fg_color=C["accent"], hover_color=C["accent_h"],
                  command=app._browse_rom,
                  ).pack(side="right", padx=(4, 0))

    app._rom_status = ctk.CTkLabel(sec_rom, text="",
                                    font=ctk.CTkFont(size=11), text_color=C["text_dim"])
    app._rom_status.pack(anchor="w", padx=12, pady=(0, 2))
    app._validate_rom_display()

    app._game_version_var = ctk.StringVar(value=app.settings.get("game_version", "firered"))
    ctk.CTkOptionMenu(sec_rom, variable=app._game_version_var,
                      values=["firered", "leafgreen", "emerald", "ruby", "sapphire"],
                      fg_color=C["bg_input"], button_color=C["accent"],
                      button_hover_color=C["accent_h"],
                      dropdown_fg_color=C["bg_card"], width=200,
                      ).pack(anchor="w", padx=12, pady=(0, 8))

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: INSTANCES & SPEED  (expanded)
    # ════════════════════════════════════════════════════════════════════
    sec_inst = make_collapsible_section(parent, "INSTANCES & SPEED", C, expanded=True)

    if_ = ctk.CTkFrame(sec_inst, fg_color="transparent")
    if_.pack(fill="x", padx=12, pady=(6, 2))
    app._inst_var = ctk.IntVar(value=app.settings.get("max_instances", 1))
    app._inst_slider = ctk.CTkSlider(
        if_, from_=1, to=max(1, app.hw["suggested_max"]),
        number_of_steps=max(1, app.hw["suggested_max"] - 1),
        variable=app._inst_var,
        fg_color=C["border"], progress_color=C["accent"],
        button_color=C["accent"], button_hover_color=C["accent_h"],
        command=lambda v: app._inst_label.configure(
            text=f"{int(v)} / {app.hw['suggested_max']}"),
    )
    app._inst_slider.pack(side="left", fill="x", expand=True)
    app._inst_label = ctk.CTkLabel(
        if_, text=f"{app._inst_var.get()} / {app.hw['suggested_max']}",
        font=ctk.CTkFont(size=11), text_color=C["text_dim"], width=56)
    app._inst_label.pack(side="right", padx=(6, 0))

    spd = ctk.CTkFrame(sec_inst, fg_color="transparent")
    spd.pack(fill="x", padx=12, pady=(2, 2))
    ctk.CTkLabel(spd, text="Speed:", font=ctk.CTkFont(size=11),
                 text_color=C["text_dim"]).pack(side="left", padx=(0, 6))
    app._speed_var = ctk.IntVar(value=app.settings.get("speed_multiplier", 0))
    for lbl, val in [("1x", 1), ("2x", 2), ("4x", 4), ("Max", 0)]:
        ctk.CTkRadioButton(spd, text=lbl, variable=app._speed_var, value=val,
                           font=ctk.CTkFont(size=11), text_color=C["text"],
                           fg_color=C["accent"], hover_color=C["accent_h"],
                           border_color=C["border"], width=46,
                           ).pack(side="left", padx=(0, 3))

    app._video_var = ctk.BooleanVar(value=app.settings.get("video_enabled", False))
    ctk.CTkCheckBox(sec_inst, text="Screen preview (reduces speed)",
                    variable=app._video_var,
                    font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                    fg_color=C["accent"], hover_color=C["accent_h"],
                    border_color=C["border"],
                    ).pack(anchor="w", padx=12, pady=(2, 8))

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: BOT MODE  (expanded)
    # ════════════════════════════════════════════════════════════════════
    sec_mode = make_collapsible_section(parent, "BOT MODE", C, expanded=True)

    app._mode_var = ctk.StringVar(value=app.settings.get("bot_mode", "manual"))
    app._mode_buttons: dict = {}

    def _refresh_mode_buttons():
        sel = app._mode_var.get()
        for k, b in app._mode_buttons.items():
            if k == sel:
                b.configure(fg_color=C["accent"], text_color="#fff",
                            border_color=C["accent"])
            else:
                b.configure(fg_color=C["bg_dark"], text_color=C["text"],
                            border_color=C["border"])

    def _make_toggle(key):
        def _t():
            app._mode_var.set(key)
            _refresh_mode_buttons()
        return _t

    for key, info in BOT_MODES.items():
        ready = info["status"] == "Ready"
        btn = ctk.CTkButton(
            sec_mode, text=info["label"],
            font=ctk.CTkFont(size=11),
            fg_color=C["accent"] if app._mode_var.get() == key else C["bg_dark"],
            text_color="#fff" if app._mode_var.get() == key else C["text"],
            hover_color=C["accent_h"], border_width=1,
            border_color=C["accent"] if app._mode_var.get() == key else C["border"],
            height=26, anchor="w",
            command=_make_toggle(key) if ready else None,
            state="normal" if ready else "disabled",
        )
        btn.pack(fill="x", padx=12, pady=1)
        app._mode_buttons[key] = btn
    ctk.CTkFrame(sec_mode, fg_color="transparent", height=6).pack()

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: TARGET AREA  (collapsed – most users won't touch this)
    # ════════════════════════════════════════════════════════════════════
    sec_area = make_collapsible_section(parent, "TARGET AREA", C, expanded=False)

    ctk.CTkLabel(sec_area,
                 text="Set to 'none' unless your bot mode needs a specific area.",
                 font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                 wraplength=260, justify="left",
                 ).pack(anchor="w", padx=12, pady=(6, 2))

    _area_values = ["none"] + list(ENCOUNTER_AREAS.keys())
    app._area_var = ctk.StringVar(value=app.settings.get("target_area", "none"))
    ctk.CTkOptionMenu(sec_area, variable=app._area_var,
                      values=_area_values,
                      fg_color=C["bg_input"], button_color=C["accent"],
                      button_hover_color=C["accent_h"],
                      dropdown_fg_color=C["bg_card"], width=220,
                      ).pack(anchor="w", padx=12, pady=(0, 8))

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: LIVING DEX  (collapsed)
    # ════════════════════════════════════════════════════════════════════
    sec_dex = make_collapsible_section(parent, "LIVING DEX", C, expanded=False)

    dex_f = ctk.CTkFrame(sec_dex, fg_color=C["bg_input"], corner_radius=8)
    dex_f.pack(fill="x", padx=12, pady=(6, 8))

    app._dex_progress_label = ctk.CTkLabel(
        dex_f, text="0 / 386 (0%)",
        font=ctk.CTkFont(size=12, weight="bold"), text_color=C["gold"])
    app._dex_progress_label.pack(anchor="w", padx=12, pady=(8, 2))

    app._dex_bar = ctk.CTkProgressBar(dex_f, height=10,
                                       fg_color=C["border"], progress_color=C["gold"])
    app._dex_bar.pack(fill="x", padx=12, pady=(0, 4))
    app._dex_bar.set(0)

    app._dex_detail = ctk.CTkLabel(dex_f, text="Base: 0  |  Evolved: 0  |  Final: 0",
                                    font=ctk.CTkFont(size=10), text_color=C["text_dim"])
    app._dex_detail.pack(anchor="w", padx=12, pady=(0, 4))

    app._legit_label = ctk.CTkLabel(dex_f, text="Legitimacy: CLEAN",
                                     font=ctk.CTkFont(size=10, weight="bold"),
                                     text_color=C["green"])
    app._legit_label.pack(anchor="w", padx=12, pady=(0, 8))

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: CHEATS & EXPORT  (collapsed)
    # ════════════════════════════════════════════════════════════════════
    sec_misc = make_collapsible_section(parent, "CHEATS & EXPORT", C, expanded=False)

    cheat_f = ctk.CTkFrame(sec_misc, fg_color="transparent")
    cheat_f.pack(fill="x", padx=12, pady=(6, 2))
    presets = [
        ("Hunting",   app._apply_hunting_cheats),
        ("Breeding",  app._apply_breeding_cheats),
        ("Evolution", app._apply_evolution_cheats),
        ("Fishing",   app._apply_fishing_cheats),
    ]
    for i, (lbl, cmd) in enumerate(presets):
        ctk.CTkButton(cheat_f, text=lbl, height=26,
                      font=ctk.CTkFont(size=11),
                      fg_color=C["accent"], hover_color=C["accent_h"],
                      command=cmd,
                      ).grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="ew")
    cheat_f.grid_columnconfigure(0, weight=1)
    cheat_f.grid_columnconfigure(1, weight=1)

    app._cheat_status = ctk.CTkLabel(sec_misc, text="No cheats active",
                                      font=ctk.CTkFont(size=10), text_color=C["text_dim"])
    app._cheat_status.pack(anchor="w", padx=12, pady=(2, 4))

    exp_f = ctk.CTkFrame(sec_misc, fg_color="transparent")
    exp_f.pack(fill="x", padx=12, pady=(2, 4))
    ctk.CTkButton(exp_f, text="Export CSV", width=90, height=26,
                  font=ctk.CTkFont(size=11),
                  fg_color=C["bg_input"], hover_color=C["accent"],
                  border_width=1, border_color=C["border"],
                  command=app._export_csv,
                  ).pack(side="left", padx=(0, 4))
    ctk.CTkButton(exp_f, text="Export JSON", width=90, height=26,
                  font=ctk.CTkFont(size=11),
                  fg_color=C["bg_input"], hover_color=C["accent"],
                  border_width=1, border_color=C["border"],
                  command=app._export_json,
                  ).pack(side="left")

    app._export_status = ctk.CTkLabel(sec_misc, text="",
                                       font=ctk.CTkFont(size=10), text_color=C["text_dim"])
    app._export_status.pack(anchor="w", padx=12, pady=(0, 4))

    # ════════════════════════════════════════════════════════════════════
    #  SECTION: NOTIFICATIONS  (collapsed)
    # ════════════════════════════════════════════════════════════════════
    sec_notif = make_collapsible_section(parent, "NOTIFICATIONS", C, expanded=False)

    notif_f = ctk.CTkFrame(sec_notif, fg_color=C["bg_input"], corner_radius=8)
    notif_f.pack(fill="x", padx=12, pady=(6, 8))

    app._notif_sound_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(notif_f, text="Sound on shiny",
                    variable=app._notif_sound_var,
                    font=ctk.CTkFont(size=11), text_color=C["text"],
                    fg_color=C["accent"], hover_color=C["accent_h"],
                    border_color=C["border"],
                    command=app._update_notif_settings,
                    ).pack(anchor="w", padx=12, pady=(8, 2))

    app._notif_discord_var = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(notif_f, text="Discord webhook",
                    variable=app._notif_discord_var,
                    font=ctk.CTkFont(size=11), text_color=C["text"],
                    fg_color=C["accent"], hover_color=C["accent_h"],
                    border_color=C["border"],
                    command=app._update_notif_settings,
                    ).pack(anchor="w", padx=12, pady=(0, 8))
