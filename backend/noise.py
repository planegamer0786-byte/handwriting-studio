"""
noise.py — Injects per-glyph and per-line human variability into rendered text.

The pipeline applies transforms in this strict order:
  1. baseline_jitter      — vertical position variance
  2. size_variance        — subtle per-character scale variation
  3. rotation_jitter      — slight tilt per glyph
  4. ink_pressure         — opacity / darkness variation
  5. pen_speed_blur       — directional motion blur on fast strokes

All randomness is seeded so documents are reproducible.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageFilter, ImageEnhance


@dataclass
class NoiseConfig:
    """Extracted from StyleSettings for convenience."""
    baseline_jitter: float      = 2.5   # px σ
    pressure_variance: float    = 0.15  # opacity σ
    rotation_jitter: float      = 1.2   # degrees σ
    size_variance: float        = 0.04  # fraction of font size σ
    word_spacing_variance: float= 0.15  # fraction of base spacing σ
    enable_blur: bool           = True
    seed: int                   = 42


class HumanVariabilityEngine:
    """
    Applies the full noise pipeline to a glyph (PIL Image RGBA patch).
    Call process() for each character rendered; call next_word() at word
    boundaries to reset correlations.
    """

    def __init__(self, cfg: NoiseConfig):
        self.cfg = cfg
        self._rng = random.Random(cfg.seed)

        # Correlated state that changes slowly (simulates pen inertia)
        self._baseline_phase: float = self._rng.uniform(0, math.tau)
        self._pressure_level: float = self._rng.gauss(1.0, cfg.pressure_variance * 0.5)
        self._pressure_level = max(0.75, min(1.0, self._pressure_level))
        self._speed_scalar: float   = self._rng.uniform(0.5, 1.0)

        self._char_idx: int  = 0
        self._word_idx: int  = 0
        self._word_char: int = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def next_word(self) -> None:
        """Call at each word boundary to update correlated state."""
        self._word_idx += 1
        self._word_char = 0
        # Pressure drifts between words
        self._pressure_level += self._rng.gauss(0, self.cfg.pressure_variance * 0.3)
        self._pressure_level = max(0.72, min(1.0, self._pressure_level))
        # Writing speed varies per word
        self._speed_scalar = self._rng.gauss(0.65, 0.18)
        self._speed_scalar = max(0.3, min(1.0, self._speed_scalar))

    def baseline_offset(self) -> int:
        """
        Returns vertical offset (px) for the current character.
        Uses a slow sine wave + fast harmonic + true noise so neighbours
        are correlated (not independently random, which looks robotic).
        """
        if self.cfg.baseline_jitter == 0:
            self._char_idx += 1
            return 0
        phase = self._char_idx / 3.0
        offset = (
            self.cfg.baseline_jitter * 0.6 * math.sin(phase + self._baseline_phase)
            + self.cfg.baseline_jitter * 0.3 * math.sin(phase * 4.7)
            + self._rng.gauss(0, self.cfg.baseline_jitter * 0.15)
        )
        self._char_idx += 1
        self._word_char += 1
        return int(round(offset))

    def word_spacing_offset(self, base_spacing: int) -> int:
        """Returns adjusted word spacing in px."""
        if self.cfg.word_spacing_variance == 0:
            return base_spacing
        return max(
            int(base_spacing * 0.5),
            int(self._rng.gauss(base_spacing, base_spacing * self.cfg.word_spacing_variance))
        )

    def apply_glyph_transforms(
        self,
        glyph: Image.Image,
        is_heading: bool = False,
    ) -> Image.Image:
        """
        Apply rotation, size variance, pressure, and blur to a glyph patch.
        Returns a new RGBA image (may be slightly larger due to rotation expand).
        """
        if glyph.mode != "RGBA":
            glyph = glyph.convert("RGBA")

        # Headings: greatly reduced noise (writers are more careful)
        jitter_scale = 0.25 if is_heading else 1.0

        glyph = self._apply_rotation(glyph, jitter_scale)
        glyph = self._apply_pressure(glyph, jitter_scale)
        if self.cfg.enable_blur and not is_heading:
            glyph = self._apply_speed_blur(glyph)

        return glyph

    # ── Private transforms ────────────────────────────────────────────────────

    def _apply_rotation(self, glyph: Image.Image, scale: float) -> Image.Image:
        σ = self.cfg.rotation_jitter * scale
        if σ < 0.01:
            return glyph
        angle = self._rng.gauss(0, σ)
        if abs(angle) < 0.1:
            return glyph
        return glyph.rotate(angle, expand=True, resample=Image.BICUBIC)

    def _apply_pressure(self, glyph: Image.Image, scale: float) -> Image.Image:
        """Darken or lighten the glyph to simulate ink pressure."""
        if self.cfg.pressure_variance == 0:
            return glyph
        pressure = self._pressure_level
        if scale < 1.0:
            pressure = max(0.88, pressure + (1.0 - pressure) * (1.0 - scale))

        r, g, b, a = glyph.split()
        # Scale alpha channel by pressure (less pressure = more transparent)
        a = a.point(lambda p: int(p * pressure))
        return Image.merge("RGBA", (r, g, b, a))

    def _apply_speed_blur(self, glyph: Image.Image) -> Image.Image:
        """Apply slight motion blur when writing speed is high."""
        if self._speed_scalar < 0.6:
            return glyph
        # Simple box blur weighted by speed; kernel 3px max
        blur_radius = (self._speed_scalar - 0.6) / 0.4 * 1.5
        if blur_radius < 0.3:
            return glyph
        return glyph.filter(ImageFilter.GaussianBlur(radius=blur_radius * 0.4))


def make_noise_config(settings, seed: int = 42) -> NoiseConfig:
    """Factory: extract NoiseConfig from StyleSettings, respecting noise_level."""
    level_scale = {
        "none":   0.0,
        "low":    0.4,
        "medium": 1.0,
        "high":   1.8,
    }[settings.noise_level]

    return NoiseConfig(
        baseline_jitter       = settings.baseline_jitter * level_scale,
        pressure_variance     = settings.pressure_variance * level_scale,
        rotation_jitter       = settings.rotation_jitter * level_scale,
        size_variance         = 0.04 * level_scale,
        word_spacing_variance = settings.word_spacing_variance * level_scale,
        enable_blur           = settings.noise_level in ("medium", "high"),
        seed                  = seed,
    )
