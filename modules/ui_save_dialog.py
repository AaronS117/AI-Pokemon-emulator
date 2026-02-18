"""
modules/ui_save_dialog.py
─────────────────────────
Save-file selection dialog shown before starting instances.

Public API:
    show_save_dialog(app, count, rom_p) -> dict | None
        Returns {inst_num: "existing"|"new"} or None if cancelled.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING, Optional

import customtkinter as ctk

from modules.config import SAVE_DIR
from modules.app_utils import detect_monitors

if TYPE_CHECKING:
    from app import App

logger = logging.getLogger(__name__)


def show_save_dialog(app: "App", count: int, rom_p: Path) -> Optional[dict]:
    """
    Modal dialog – one row per instance.

    Each row shows:
      • Whether a save already exists (green tick / orange warning)
      • Radio: Load existing  |  New game
      • Browse button to import a .sav from anywhere

    "New game" means the emulator will boot fresh and the bot will attempt
    the new-game intro sequence automatically, then hand control to you.

    Returns {1: "existing", 2: "new", ...} or None if the user cancels.
    """
    C = app.C

    dlg = ctk.CTkToplevel(app)
    dlg.title("Save File Setup")
    dlg.configure(fg_color=C["bg_dark"])
    dlg.grab_set()
    dlg.resizable(True, True)

    # Centre on primary monitor
    monitors = detect_monitors()
    pm = monitors[0]
    dlg_w = 560
    dlg_h = min(120 + count * 100, pm["height"] - 80)
    dlg_x = pm["x"] + (pm["width"] - dlg_w) // 2
    dlg_y = pm["y"] + (pm["height"] - dlg_h) // 2
    dlg.geometry(f"{dlg_w}x{dlg_h}+{dlg_x}+{dlg_y}")
    dlg.minsize(480, 300)

    # ── Header ────────────────────────────────────────────────────────────
    hdr = ctk.CTkFrame(dlg, fg_color=C["bg_card"], corner_radius=0)
    hdr.pack(fill="x")

    ctk.CTkLabel(hdr, text="Configure Save Files",
                 font=ctk.CTkFont(size=15, weight="bold"),
                 text_color=C["text"]).pack(side="left", padx=16, pady=10)

    ctk.CTkLabel(hdr,
                 text=f"saves/<N>/{rom_p.stem}.sav",
                 font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                 ).pack(side="right", padx=16)

    # ── Scrollable instance list ──────────────────────────────────────────
    scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
    scroll.pack(fill="both", expand=True, padx=12, pady=(8, 4))

    choices: dict[int, ctk.StringVar] = {}
    # Keep label refs so Browse can update them live
    sav_info_labels: dict[int, ctk.CTkLabel] = {}

    for n in range(1, count + 1):
        sav = SAVE_DIR / str(n) / f"{rom_p.stem}.sav"
        exists = sav.exists() and sav.stat().st_size > 0
        size_kb = round(sav.stat().st_size / 1024, 1) if sav.exists() else 0

        card = ctk.CTkFrame(scroll, fg_color=C["bg_input"], corner_radius=8)
        card.pack(fill="x", pady=4, padx=2)

        # Top row: instance label + save status
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))

        ctk.CTkLabel(top, text=f"Instance #{n}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        sav_text = (f"✅  saves/{n}/{rom_p.stem}.sav  ({size_kb} KB)"
                    if exists else
                    f"⚠️  No save at saves/{n}/{rom_p.stem}.sav")
        sav_color = "#5aba5a" if exists else "#cc8800"
        info_lbl = ctk.CTkLabel(top, text=sav_text,
                                 font=ctk.CTkFont(size=10), text_color=sav_color)
        info_lbl.pack(side="right")
        sav_info_labels[n] = info_lbl

        # Radio row
        var = ctk.StringVar(value="existing" if exists else "new")
        choices[n] = var

        radio_row = ctk.CTkFrame(card, fg_color="transparent")
        radio_row.pack(fill="x", padx=10, pady=(2, 4))

        ctk.CTkRadioButton(
            radio_row, text="Load existing save",
            variable=var, value="existing",
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"],
            state="normal" if exists else "disabled",
        ).pack(side="left", padx=(0, 16))

        ctk.CTkRadioButton(
            radio_row, text="New game",
            variable=var, value="new",
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"],
        ).pack(side="left", padx=(0, 16))

        # New-game explanation (shown inline, small)
        ctk.CTkLabel(radio_row,
                     text="(bot runs intro, then hands control to you)",
                     font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                     ).pack(side="left")

        # Browse button
        def _browse(n=n, var=var):
            path = filedialog.askopenfilename(
                title=f"Select save for Instance #{n}",
                filetypes=[("GBA Save", "*.sav"), ("All files", "*.*")],
            )
            if not path:
                return
            dest = SAVE_DIR / str(n) / f"{rom_p.stem}.sav"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            var.set("existing")
            kb = round(dest.stat().st_size / 1024, 1)
            sav_info_labels[n].configure(
                text=f"✅  saves/{n}/{rom_p.stem}.sav  ({kb} KB)",
                text_color="#5aba5a",
            )
            logger.info("Instance %d: imported save %s → %s", n, path, dest)

        ctk.CTkButton(
            card, text="Browse / Import .sav…", height=26,
            font=ctk.CTkFont(size=10),
            fg_color=C["bg_dark"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=_browse,
        ).pack(anchor="e", padx=10, pady=(0, 8))

    # ── Footer buttons ────────────────────────────────────────────────────
    footer = ctk.CTkFrame(dlg, fg_color=C["bg_card"], corner_radius=0)
    footer.pack(fill="x", side="bottom")

    result: list = [None]

    def _ok():
        result[0] = {n: v.get() for n, v in choices.items()}
        dlg.destroy()

    def _cancel():
        dlg.destroy()

    ctk.CTkButton(footer, text="Cancel", width=100, height=36,
                  font=ctk.CTkFont(size=13),
                  fg_color=C["bg_dark"], hover_color=C["red"],
                  border_width=1, border_color=C["border"],
                  text_color=C["text"],
                  command=_cancel,
                  ).pack(side="right", padx=(6, 14), pady=10)

    ctk.CTkButton(footer, text="▶  Start", width=120, height=36,
                  font=ctk.CTkFont(size=13, weight="bold"),
                  fg_color=C["green"], hover_color="#16a34a", text_color="#000",
                  command=_ok,
                  ).pack(side="right", padx=(0, 6), pady=10)

    ctk.CTkLabel(footer,
                 text="Tip: 'New game' will auto-play the intro then pause for you.",
                 font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                 ).pack(side="left", padx=14)

    app.wait_window(dlg)
    return result[0]
