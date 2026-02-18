"""
shiny_scan – Visual and memory-based shiny detection system.

Two detection strategies:
  1. **Memory-based** (primary): Read the encountered Pokémon's PID, TID,
     and SID from emulator memory and compute shininess directly.
  2. **Visual** (fallback / verification): Compare the on-screen sprite
     palette against reference normal and shiny palettes stored in
     ``sprites/``.

The memory-based method is frame-perfect and instant.  The visual method
serves as an independent cross-check and can work even when memory
addresses are unknown (e.g. ROM hacks).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from modules.config import SPRITES_DIR, SHINY_PALETTE_THRESHOLD, SPRITE_MATCH_THRESHOLD

logger = logging.getLogger(__name__)


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class SpriteRef:
    """Reference sprite data for a single species."""
    species: str
    normal_path: Path
    shiny_path: Path
    normal_palette: Optional[np.ndarray] = None
    shiny_palette: Optional[np.ndarray] = None


@dataclass
class ScanResult:
    """Result of a shiny scan."""
    is_shiny: bool
    method: str  # "memory" | "visual" | "both"
    confidence: float  # 0.0 – 1.0
    species: str = ""
    details: str = ""


# ── Palette utilities ────────────────────────────────────────────────────────

def extract_palette(image: np.ndarray, max_colors: int = 16) -> np.ndarray:
    """
    Extract the dominant palette from a sprite image.

    GBA sprites use 16-color palettes.  We quantize the image to
    *max_colors* and return the sorted RGB values as an (N, 3) array.
    """
    if image is None or image.size == 0:
        return np.zeros((0, 3), dtype=np.uint8)

    # Flatten to list of pixels, ignore fully transparent pixels
    if image.ndim == 3 and image.shape[2] == 4:
        mask = image[:, :, 3] > 0
        pixels = image[mask][:, :3]
    elif image.ndim == 3:
        pixels = image.reshape(-1, image.shape[2])
    else:
        pixels = image.reshape(-1, 1)

    if len(pixels) == 0:
        return np.zeros((0, 3), dtype=np.uint8)

    # Simple quantization: unique colors sorted by frequency
    unique, counts = np.unique(pixels, axis=0, return_counts=True)
    order = np.argsort(-counts)
    palette = unique[order][:max_colors]
    return palette.astype(np.uint8)


def palette_similarity(pal_a: np.ndarray, pal_b: np.ndarray) -> float:
    """
    Compute a similarity score (0–1) between two palettes.

    Uses the mean per-channel distance between the closest color pairs.
    """
    if pal_a.size == 0 or pal_b.size == 0:
        return 0.0

    # Ensure both are float for distance computation
    a = pal_a.astype(np.float32)
    b = pal_b.astype(np.float32)

    total_dist = 0.0
    matched = 0
    for color in a:
        dists = np.linalg.norm(b - color, axis=1)
        total_dist += float(np.min(dists))
        matched += 1

    if matched == 0:
        return 0.0

    # Normalize: max possible distance per channel is ~441 (sqrt(3*255^2))
    avg_dist = total_dist / matched
    similarity = max(0.0, 1.0 - avg_dist / 441.0)
    return similarity


# ── Sprite reference loader ──────────────────────────────────────────────────

class SpriteDatabase:
    """Loads and caches reference sprites from the sprites/ directory."""

    def __init__(self, sprites_dir: Path = SPRITES_DIR) -> None:
        self.sprites_dir = sprites_dir
        self._cache: Dict[str, SpriteRef] = {}

    def load_species(self, species: str) -> Optional[SpriteRef]:
        """Load normal + shiny reference sprites for a species."""
        if species in self._cache:
            return self._cache[species]

        normal_path = self.sprites_dir / "normal" / f"{species.lower()}.png"
        shiny_path = self.sprites_dir / "shiny" / f"{species.lower()}.png"

        if not normal_path.exists() or not shiny_path.exists():
            logger.warning(
                "Missing sprite references for %s (need %s and %s)",
                species, normal_path, shiny_path,
            )
            return None

        try:
            import cv2
            normal_img = cv2.imread(str(normal_path), cv2.IMREAD_UNCHANGED)
            shiny_img = cv2.imread(str(shiny_path), cv2.IMREAD_UNCHANGED)

            ref = SpriteRef(
                species=species,
                normal_path=normal_path,
                shiny_path=shiny_path,
                normal_palette=extract_palette(normal_img),
                shiny_palette=extract_palette(shiny_img),
            )
            self._cache[species] = ref
            return ref
        except ImportError:
            logger.error("opencv-python is required for visual shiny detection.")
            return None

    def load_all(self) -> int:
        """Pre-load all species that have both normal and shiny sprites."""
        normal_dir = self.sprites_dir / "normal"
        if not normal_dir.exists():
            return 0
        count = 0
        for png in normal_dir.glob("*.png"):
            species = png.stem
            if self.load_species(species) is not None:
                count += 1
        return count

    @property
    def loaded_species(self) -> List[str]:
        return list(self._cache.keys())


# ── Shiny scanner ────────────────────────────────────────────────────────────

class ShinyScanner:
    """
    Combines memory-based and visual shiny detection.

    Usage::

        scanner = ShinyScanner()
        result = scanner.check_memory(pid=0xABCD1234, tid=12345, sid=54321)
        if result.is_shiny:
            ...
    """

    def __init__(self, sprites_dir: Path = SPRITES_DIR) -> None:
        self.sprite_db = SpriteDatabase(sprites_dir)

    # ── Memory-based detection ───────────────────────────────────────────

    @staticmethod
    def check_memory(
        personality_value: int,
        tid: int,
        sid: int,
    ) -> ScanResult:
        """
        Determine shininess using the standard Gen 3 formula:

            shiny = (TID ^ SID ^ PID_high ^ PID_low) < 8
        """
        pid_high = (personality_value >> 16) & 0xFFFF
        pid_low = personality_value & 0xFFFF
        shiny_value = tid ^ sid ^ pid_high ^ pid_low
        is_shiny = shiny_value < 8

        return ScanResult(
            is_shiny=is_shiny,
            method="memory",
            confidence=1.0,
            details=f"SV={shiny_value} ({'shiny' if is_shiny else 'not shiny'})",
        )

    # ── Visual detection ─────────────────────────────────────────────────

    def check_visual(
        self,
        screen_sprite: np.ndarray,
        species: str,
    ) -> ScanResult:
        """
        Compare an on-screen sprite's palette against reference palettes.

        Returns a ScanResult indicating whether the sprite matches the
        shiny palette more closely than the normal palette.
        """
        ref = self.sprite_db.load_species(species)
        if ref is None or ref.normal_palette is None or ref.shiny_palette is None:
            return ScanResult(
                is_shiny=False,
                method="visual",
                confidence=0.0,
                species=species,
                details="No reference sprites available.",
            )

        screen_palette = extract_palette(screen_sprite)
        if screen_palette.size == 0:
            return ScanResult(
                is_shiny=False,
                method="visual",
                confidence=0.0,
                species=species,
                details="Could not extract palette from screen sprite.",
            )

        sim_normal = palette_similarity(screen_palette, ref.normal_palette)
        sim_shiny = palette_similarity(screen_palette, ref.shiny_palette)

        is_shiny = sim_shiny > sim_normal and sim_shiny >= SHINY_PALETTE_THRESHOLD
        confidence = sim_shiny if is_shiny else (1.0 - sim_normal)

        return ScanResult(
            is_shiny=is_shiny,
            method="visual",
            confidence=confidence,
            species=species,
            details=(
                f"normal_sim={sim_normal:.3f}, shiny_sim={sim_shiny:.3f}, "
                f"threshold={SHINY_PALETTE_THRESHOLD}"
            ),
        )

    # ── Combined check ───────────────────────────────────────────────────

    def check_combined(
        self,
        personality_value: int,
        tid: int,
        sid: int,
        screen_sprite: Optional[np.ndarray] = None,
        species: str = "",
    ) -> ScanResult:
        """
        Run both memory and visual checks.  Memory result takes priority;
        visual serves as confirmation.
        """
        mem_result = self.check_memory(personality_value, tid, sid)

        if screen_sprite is not None and species:
            vis_result = self.check_visual(screen_sprite, species)
            if mem_result.is_shiny and vis_result.is_shiny:
                return ScanResult(
                    is_shiny=True,
                    method="both",
                    confidence=1.0,
                    species=species,
                    details=f"Memory: {mem_result.details} | Visual: {vis_result.details}",
                )
            if mem_result.is_shiny and not vis_result.is_shiny:
                logger.warning(
                    "Memory says shiny but visual disagrees for %s (visual conf=%.2f). "
                    "Trusting memory.",
                    species, vis_result.confidence,
                )

        return ScanResult(
            is_shiny=mem_result.is_shiny,
            method="memory",
            confidence=mem_result.confidence,
            species=species,
            details=mem_result.details,
        )


# ── Template matching (bonus utility) ────────────────────────────────────────

def template_match_species(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = SPRITE_MATCH_THRESHOLD,
) -> Tuple[bool, float, Tuple[int, int]]:
    """
    Use OpenCV template matching to locate a sprite on screen.

    Returns (found, confidence, (x, y)).
    """
    try:
        import cv2
    except ImportError:
        return False, 0.0, (0, 0)

    if screen is None or template is None:
        return False, 0.0, (0, 0)

    # Convert to grayscale for matching
    if screen.ndim == 3:
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    else:
        screen_gray = screen

    if template.ndim == 3:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    else:
        template_gray = template

    result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    return max_val >= threshold, float(max_val), max_loc
