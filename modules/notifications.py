"""
notifications – Shiny encounter notification system.

Provides multiple notification channels:
  - Desktop toast notifications (Windows/macOS/Linux)
  - Sound alerts (built-in beep + custom WAV)
  - Discord webhook integration
  - Console/log output

All notifications are non-blocking and failure-tolerant.
"""

from __future__ import annotations

import json
import logging
import platform
import struct
import threading
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Optional

from modules.config import ROOT_DIR

logger = logging.getLogger(__name__)

SOUNDS_DIR = ROOT_DIR / "sounds"


# ── Sound Generation ────────────────────────────────────────────────────────

def _generate_shiny_wav() -> bytes:
    """
    Generate a shiny sparkle sound effect as a WAV byte buffer.
    Two ascending tones (the classic shiny 'ding-ding' feel).
    """
    sample_rate = 22050
    duration1 = 0.15
    duration2 = 0.20
    freq1 = 1200  # Hz
    freq2 = 1600  # Hz
    volume = 0.6

    import math
    samples = []

    # Tone 1 – rising
    n1 = int(sample_rate * duration1)
    for i in range(n1):
        t = i / sample_rate
        env = 1.0 - (i / n1) * 0.3  # slight fade
        val = volume * env * math.sin(2.0 * math.pi * freq1 * t)
        samples.append(int(val * 32767))

    # Brief silence
    silence = int(sample_rate * 0.05)
    samples.extend([0] * silence)

    # Tone 2 – higher pitch, longer
    n2 = int(sample_rate * duration2)
    for i in range(n2):
        t = i / sample_rate
        env = 1.0 - (i / n2) * 0.5
        val = volume * env * math.sin(2.0 * math.pi * freq2 * t)
        samples.append(int(val * 32767))

    # Fade out tail
    tail = int(sample_rate * 0.1)
    for i in range(tail):
        t = i / sample_rate
        env = 1.0 - (i / tail)
        val = volume * env * 0.3 * math.sin(2.0 * math.pi * freq2 * t)
        samples.append(int(val * 32767))

    # Pack as WAV
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for s in samples:
            wf.writeframes(struct.pack("<h", max(-32768, min(32767, s))))
    return buf.getvalue()


def _play_wav_bytes(wav_data: bytes) -> None:
    """Play WAV audio from bytes. Platform-specific."""
    system = platform.system()
    try:
        if system == "Windows":
            import winsound
            winsound.PlaySound(wav_data, winsound.SND_MEMORY | winsound.SND_ASYNC)
        elif system == "Darwin":
            import tempfile, subprocess
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_data)
                f.flush()
                subprocess.Popen(["afplay", f.name])
        else:
            import tempfile, subprocess
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_data)
                f.flush()
                subprocess.Popen(["aplay", "-q", f.name])
    except Exception as exc:
        logger.debug("WAV playback failed: %s", exc)


def _play_fallback_beep() -> None:
    """Simple fallback beep if WAV playback isn't available."""
    system = platform.system()
    try:
        if system == "Windows":
            import winsound
            winsound.Beep(1200, 200)
            time.sleep(0.05)
            winsound.Beep(1600, 300)
        else:
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)


# Pre-generate the shiny sound on module load
_SHINY_WAV: Optional[bytes] = None
try:
    _SHINY_WAV = _generate_shiny_wav()
except Exception:
    pass


# ── Desktop Toast Notifications ─────────────────────────────────────────────

def _toast_windows(title: str, message: str) -> None:
    """Windows 10/11 toast notification via PowerShell."""
    try:
        import subprocess
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{message}</text>
    </binding>
  </visual>
  <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Gen3 Shiny Hunter").Show($toast)
"""
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception as exc:
        logger.debug("Windows toast failed: %s", exc)


def _toast_macos(title: str, message: str) -> None:
    """macOS notification via osascript."""
    try:
        import subprocess
        subprocess.Popen([
            "osascript", "-e",
            f'display notification "{message}" with title "{title}" sound name "Glass"'
        ])
    except Exception as exc:
        logger.debug("macOS toast failed: %s", exc)


def _toast_linux(title: str, message: str) -> None:
    """Linux notification via notify-send."""
    try:
        import subprocess
        subprocess.Popen(["notify-send", title, message, "--urgency=critical"])
    except Exception as exc:
        logger.debug("Linux toast failed: %s", exc)


def send_toast(title: str, message: str) -> None:
    """Send a desktop toast notification (non-blocking)."""
    system = platform.system()
    if system == "Windows":
        _toast_windows(title, message)
    elif system == "Darwin":
        _toast_macos(title, message)
    else:
        _toast_linux(title, message)


# ── Discord Webhook ─────────────────────────────────────────────────────────

def send_discord_webhook(
    webhook_url: str,
    species_id: int,
    personality_value: int,
    encounters: int,
    instance_id: str = "",
    extra_info: str = "",
) -> bool:
    """
    Send a shiny notification to a Discord channel via webhook.

    Args:
        webhook_url: Full Discord webhook URL.
        species_id: National dex number.
        personality_value: PV for identification.
        encounters: Total encounters before this shiny.
        instance_id: Which emulator instance found it.
        extra_info: Additional info (IVs, nature, etc.)

    Returns:
        True if sent successfully.
    """
    if not webhook_url:
        return False

    try:
        import urllib.request

        embed = {
            "title": f"SHINY FOUND! #{species_id:03d}",
            "color": 0xFFD700,  # Gold
            "fields": [
                {"name": "Species", "value": f"#{species_id}", "inline": True},
                {"name": "Encounters", "value": f"{encounters:,}", "inline": True},
                {"name": "Instance", "value": instance_id or "N/A", "inline": True},
                {"name": "PV", "value": f"0x{personality_value:08X}", "inline": True},
            ],
            "footer": {"text": "Gen 3 Shiny Hunter"},
        }
        if extra_info:
            embed["fields"].append(
                {"name": "Details", "value": extra_info, "inline": False})

        payload = json.dumps({
            "content": "**A shiny Pokémon was found!**",
            "embeds": [embed],
        }).encode("utf-8")

        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)

    except Exception as exc:
        logger.error("Discord webhook failed: %s", exc)
        return False


# ── Notification Manager ────────────────────────────────────────────────────

class NotificationManager:
    """
    Central manager for all notification channels.

    Configure which channels are active, then call notify_shiny()
    when a shiny is found. All notifications run in background threads.
    """

    def __init__(self):
        self.sound_enabled: bool = True
        self.toast_enabled: bool = True
        self.discord_enabled: bool = False
        self.discord_webhook_url: str = ""
        self._custom_sound_path: Optional[Path] = None

    def set_custom_sound(self, path: Path) -> None:
        """Set a custom WAV file for shiny alerts."""
        if path.exists() and path.suffix.lower() == ".wav":
            self._custom_sound_path = path
            logger.info("Custom shiny sound: %s", path)

    def notify_shiny(
        self,
        species_id: int,
        personality_value: int = 0,
        encounters: int = 0,
        instance_id: str = "",
        extra_info: str = "",
    ) -> None:
        """
        Fire all enabled notifications for a shiny encounter.
        All run in background threads to avoid blocking emulation.
        """
        title = f"SHINY #{species_id:03d} FOUND!"
        message = f"After {encounters:,} encounters (Instance {instance_id})"

        if self.sound_enabled:
            threading.Thread(
                target=self._play_sound, daemon=True
            ).start()

        if self.toast_enabled:
            threading.Thread(
                target=send_toast, args=(title, message), daemon=True
            ).start()

        if self.discord_enabled and self.discord_webhook_url:
            threading.Thread(
                target=send_discord_webhook,
                args=(self.discord_webhook_url, species_id,
                      personality_value, encounters, instance_id, extra_info),
                daemon=True,
            ).start()

        logger.info("Shiny notification sent: %s – %s", title, message)

    def _play_sound(self) -> None:
        """Play the shiny alert sound."""
        try:
            if self._custom_sound_path and self._custom_sound_path.exists():
                wav_data = self._custom_sound_path.read_bytes()
                _play_wav_bytes(wav_data)
            elif _SHINY_WAV:
                _play_wav_bytes(_SHINY_WAV)
            else:
                _play_fallback_beep()
        except Exception:
            _play_fallback_beep()

    def test_sound(self) -> None:
        """Play the shiny sound for testing."""
        threading.Thread(target=self._play_sound, daemon=True).start()

    def test_toast(self) -> None:
        """Send a test toast notification."""
        threading.Thread(
            target=send_toast,
            args=("Test Notification", "Shiny notifications are working!"),
            daemon=True,
        ).start()
