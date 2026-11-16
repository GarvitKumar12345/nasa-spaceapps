"""Adapted educational generator from reference/blinkir; all values are synthetic arbitrary units.
Not an instrument response, calibrated photometry or actual observed epochs.
"""
import hashlib,json
from pathlib import Path
import numpy as np
BENCHMARK_TARGETS=json.loads(Path(__file__).with_name("presets.json").read_text())
SPHEREX_BANDS=[{'band': 1, 'name': 'Band 1 (0.75-1.09 um)', 'min_um': 0.75, 'max_um': 1.09, 'r_power': 39}, {'band': 2, 'name': 'Band 2 (1.10-1.62 um)', 'min_um': 1.1, 'max_um': 1.62, 'r_power': 41}, {'band': 3, 'name': 'Band 3 (1.63-2.41 um)', 'min_um': 1.63, 'max_um': 2.41, 'r_power': 41}, {'band': 4, 'name': 'Band 4 (2.42-3.82 um)', 'min_um': 2.42, 'max_um': 3.82, 'r_power': 35}, {'band': 5, 'name': 'Band 5 (3.83-4.41 um)', 'min_um': 3.83, 'max_um': 4.41, 'r_power': 112}, {'band': 6, 'name': 'Band 6 (4.42-5.00 um)', 'min_um': 4.42, 'max_um': 5.0, 'r_power': 128}]
def _gaussian_2d(size: int, x0: float, y0: float, sigma: float, amp: float) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    return amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2.0 * sigma ** 2))


def _synthesize_102_spectrum(target_id: str) -> list:
    wavelengths = np.linspace(0.76, 4.98, 102)
    channels = []

    for lam in wavelengths:
        band = 1
        for b in SPHEREX_BANDS:
            if b["min_um"] <= lam <= b["max_um"]:
                band = b["band"]
                break

        if target_id in ("WISE_0855", "Epsilon_Indi_B"):
            continuum = 0.35 + 1.85 * ((lam - 0.75) / 4.25) ** 2.2
            h2o_dip = 0.68 * np.exp(-((lam - 3.02) / 0.16) ** 2)
            ch4_dip = 0.82 * np.exp(-((lam - 3.32) / 0.14) ** 2)
            co_dip = 0.32 * np.exp(-((lam - 4.65) / 0.10) ** 2)
            flux = max(0.04, continuum * (1.0 - h2o_dip) * (1.0 - ch4_dip) * (1.0 - co_dip))
            bg_star_flux = 1.45 * ((lam / 1.5) ** -1.6)
        elif target_id == "Barnards_Star":
            continuum = 4.2 * ((lam / 1.0) ** -1.55)
            h2o_14 = 0.22 * np.exp(-((lam - 1.40) / 0.08) ** 2)
            h2o_19 = 0.25 * np.exp(-((lam - 1.90) / 0.10) ** 2)
            flux = continuum * (1.0 - h2o_14) * (1.0 - h2o_19)
            bg_star_flux = 1.5 * ((lam / 1.5) ** -1.7)
        elif target_id == "RW_Aurigae":
            star = 2.4 * ((lam / 1.0) ** -1.4)
            dust_excess = 1.95 * np.exp(-((lam - 4.1) / 1.15) ** 2)
            flux = star + dust_excess
            bg_star_flux = 1.3 * ((lam / 1.5) ** -1.7)
        else:
            continuum = 3.8 * ((lam / 1.2) ** -1.2)
            h2o_27 = 0.45 * np.exp(-((lam - 2.72) / 0.18) ** 2)
            sio_40 = 0.28 * np.exp(-((lam - 4.05) / 0.12) ** 2)
            flux = continuum * (1.0 - h2o_27) * (1.0 - sio_40)
            bg_star_flux = 1.4 * ((lam / 1.5) ** -1.7)

        rng = np.random.default_rng(int(lam * 10000) + len(target_id))
        noise = rng.normal(0.0, 0.025 * max(flux, 0.2))
        channels.append({
            "wavelength_um": round(float(lam), 4),
            "model_value": round(max(0.01, float(flux + noise)), 4),
            "background_value": round(float(bg_star_flux), 4),
            "band": band,
        })
    return channels


def build_simulation(target_id: str) -> dict:
    size = 64
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(target_id.encode()).digest()[:4], "little"))

    bg_noise_1 = rng.normal(0.0, 0.035, (size, size))
    bg_noise_2 = rng.normal(0.0, 0.035, (size, size))

    stationary_field = np.zeros((size, size))
    star_coords = [(12, 14, 1.9), (49, 16, 2.5), (18, 50, 1.4), (52, 46, 2.1), (38, 11, 1.1), (10, 34, 1.6)]
    for sx, sy, samp in star_coords:
        stationary_field += _gaussian_2d(size, sx, sy, sigma=1.45, amp=samp)

    cx, cy = 32.0, 32.0
    if target_id == "WISE_0855":
        pos1 = (cx + 2.2, cy - 0.3)
        pos2 = (cx - 2.4, cy + 0.4)
        amp1, amp2 = 2.6, 2.7
    elif target_id == "Barnards_Star":
        pos1 = (cx + 0.4, cy - 2.8)
        pos2 = (cx - 0.5, cy + 3.1)
        amp1, amp2 = 4.5, 4.5
    elif target_id == "Epsilon_Indi_B":
        pos1 = (cx - 1.6, cy + 1.1)
        pos2 = (cx + 1.8, cy - 1.2)
        amp1, amp2 = 3.1, 3.1
    elif target_id == "RW_Aurigae":
        pos1 = (cx, cy)
        pos2 = (cx + 0.05, cy - 0.05)
        amp1, amp2 = 2.1, 4.4
    else:
        pos1 = (cx, cy)
        pos2 = (cx - 0.04, cy + 0.04)
        amp1, amp2 = 4.6, 1.8

    epoch1 = stationary_field + _gaussian_2d(size, pos1[0], pos1[1], sigma=1.55, amp=amp1) + bg_noise_1
    epoch2 = stationary_field + _gaussian_2d(size, pos2[0], pos2[1], sigma=1.55, amp=amp2) + bg_noise_2

    return {"images": [np.round(epoch1, 4).tolist(), np.round(epoch2, 4).tolist()],
            "positions": [list(pos1),list(pos2)],
            "spectrum": [{"wavelength_um": p["wavelength_um"], "value": p["model_value"], "background_value": p["background_value"], "detector": p["band"]} for p in _synthesize_102_spectrum(target_id)]}
