"""Evidence plots for scripts/target_astrometry.py (matplotlib, dev dependency). Colours: validated categorical pair
(blue = Gaia DR3 prediction, a model; orange = SPHEREx measurement, derived from native pixels); text in ink colours."""

from __future__ import annotations

from pathlib import Path

import math

import numpy as np

BLUE, ORANGE, INK, INK2, SURFACE, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"


def _style(plt) -> None:  # noqa: ANN001
    plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                         "ytick.color": INK2, "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False})


def make_stage2_plots(res: dict, og, out_dir: Path, slug: str) -> list[Path]:  # noqa: ANN001, C901
    """Stage-2 evidence: positions, two-season images, detector estimates, residuals, fit stamps, diagnostics."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    meas = [r for r in res["frames"] if r["status"] == "measured"]
    pairs = [p for p in res["pairs"] if "p_vs_zero" in p]
    from skyshift.coords.tangent import offsets_mas

    # 1. measured and predicted positions on the sky, relative to the first-season prediction of each pair
    if pairs:
        fig, axes = plt.subplots(1, 2, figsize=(8.4, 4.2), sharex=True, sharey=True)
        for ax, approach in zip(axes, ("untied", "tied")):
            ps = [p for p in pairs if p["approach"] == approach]
            for p in ps:
                ax.annotate("", xy=tuple(p["predicted_arcsec"]), xytext=(0, 0), arrowprops={"arrowstyle": "-|>", "color": BLUE, "lw": 1.2, "alpha": 0.8})
                ax.errorbar([p["measured_arcsec"][0]], [p["measured_arcsec"][1]], xerr=[p["sigma_total_arcsec"][0]], yerr=[p["sigma_total_arcsec"][1]],
                            fmt="o", color=ORANGE, ms=5, elinewidth=1.0, capsize=0)
                ax.annotate(f"D{p['detector']}", (p["measured_arcsec"][0], p["measured_arcsec"][1]), textcoords="offset points", xytext=(6, -10), fontsize=7, color=INK2)
            ax.plot([0], [0], "o", color=INK2, ms=4)
            ax.set_xlim(1.2, -1.2)
            ax.set_ylim(-2.2, 0.6)
            ax.set_aspect("equal")
            ax.set_xlabel("Δ east from season-1 position (″)")
            ax.set_title(f"{'Untied (archive WCS)' if approach == 'untied' else 'Tied to reference stars'}: {len(ps)} pair(s)", fontsize=8.5)
        axes[0].set_ylabel("Δ north (″)")
        fig.legend(handles=[plt.Line2D([], [], color=BLUE, lw=1.2, label="Gaia DR3 prediction (model)"),
                            plt.Line2D([], [], color=ORANGE, marker="o", ls="", ms=5, label="SPHEREx measurement ±1σ total (stat ⊕ sys)")],
                   loc="lower center", ncol=2, fontsize=8)
        fig.suptitle(f"{res['target']['name']}: season-2 minus season-1 position", fontsize=10)
        fig.tight_layout(rect=(0, 0.07, 1, 0.94))
        paths.append(out_dir / f"{slug}_positions.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 2. two-season image comparison (every measured pair; native pixels)
    by_band: dict[str, list[dict]] = {}
    for r in meas:
        by_band.setdefault(r["band_id"], []).append(r)
    bands = [b for b, rs in sorted(by_band.items()) if len(rs) == 2]
    if bands:
        fig, axes = plt.subplots(2, len(bands), figsize=(2.0 * len(bands), 4.4), squeeze=False)
        for j, b in enumerate(bands):
            for i, r in enumerate(sorted(by_band[b], key=lambda r: r["mid_utc"])):
                img = np.asarray(og.images[r["frame_id"]].image, dtype=float)
                cx, cy = int(round(r["measured"]["x_px"])), int(round(r["measured"]["y_px"]))
                h = 6
                st = img[cy - h : cy + h + 1, cx - h : cx + h + 1]
                ax = axes[i][j]
                ax.imshow(np.arcsinh((st - np.nanmedian(st)) / max(float(np.nanstd(st)), 1e-9)), origin="lower", cmap="gray_r",
                          extent=(cx - h - 0.5, cx + h + 0.5, cy - h - 0.5, cy + h + 0.5))
                ax.plot(r["predicted"]["x_px"], r["predicted"]["y_px"], "+", color=BLUE, ms=10, mew=1.5)
                ax.plot(r["measured"]["x_px"], r["measured"]["y_px"], "x", color=ORANGE, ms=8, mew=1.5)
                for f in r.get("uncatalogued_features") or []:
                    ax.plot(f["x"], f["y"], "o", mfc="none", mec=INK2, ms=9, mew=1.0)
                ax.set_title(f"D{r['detector']} S{r['season']} {r['mid_utc'][:10]}", fontsize=7.5)
                ax.set_xticks([])
                ax.set_yticks([])
                ax.grid(False)
        fig.legend(handles=[plt.Line2D([], [], color=BLUE, marker="+", ls="", ms=9, mew=1.5, label="Gaia DR3 prediction (model)"),
                            plt.Line2D([], [], color=ORANGE, marker="x", ls="", ms=8, mew=1.5, label="ePSF measurement"),
                            plt.Line2D([], [], color=INK2, marker="o", mfc="none", ls="", ms=8, label="uncatalogued feature (>= 5σ)")],
                   loc="lower center", ncol=3, fontsize=7.5)
        fig.suptitle("Two seasons, native pixels (13 × 13 px, arcsinh; detector orientation, not north-up)", fontsize=8.5)
        fig.tight_layout(rect=(0, 0.07, 1, 0.94))
        paths.append(out_dir / f"{slug}_two_seasons.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 3. detector-by-detector estimates: measured / predicted along the predicted direction
    if pairs:
        fig, ax = plt.subplots(figsize=(6.6, 3.0))
        labels = []
        for k, p in enumerate(sorted(pairs, key=lambda p: (p["detector"], p["approach"]))):
            # all points are measurements (orange); filled = tied to reference stars, open = archive WCS
            ax.errorbar([k], [p["along_ratio"]], yerr=[p["along_ratio_sigma"]], fmt="o" if p["role"] == "primary" else "s", color=ORANGE, ms=6, elinewidth=1.2,
                        capsize=0, mfc=ORANGE if p["approach"] == "tied" else SURFACE, mew=1.4)
            labels.append(f"D{p['detector']} {p['approach']}\n{p['status']}")
        ax.axhline(1.0, color=BLUE, lw=0.8, ls="--")
        ax.axhline(0.0, color=INK2, lw=0.8)
        ax.set_xticks(range(len(labels)), labels, fontsize=7)
        ax.set_ylabel("measured / predicted\n(along the predicted direction)")
        ax.set_title("Measured displacement per detector (dashed: Gaia prediction = 1; 0 = no motion)\nfilled: tied, open: archive WCS; circles primary, squares secondary", fontsize=8)
        fig.tight_layout()
        paths.append(out_dir / f"{slug}_detector_estimates.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 4. residuals per pair (measured - predicted) with statistical and total uncertainty
    if pairs:
        fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.0), sharey=True)
        ps = sorted(pairs, key=lambda p: (p["detector"], p["approach"]))
        x = np.arange(len(ps))
        for k, (ax, name) in enumerate(zip(axes, ("east", "north"))):
            ax.axhline(0, color=INK2, lw=0.8)
            for i, p in enumerate(ps):
                ax.errorbar([i], [p["residual_arcsec"][k]], yerr=[p["sigma_total_arcsec"][k]], fmt="none", ecolor=ORANGE, elinewidth=1.0, alpha=0.45)
                ax.errorbar([i], [p["residual_arcsec"][k]], yerr=[p["sigma_stat_arcsec"][k]], fmt="o", color=ORANGE, ms=5, elinewidth=2.2, capsize=0,
                            mfc=ORANGE if p["approach"] == "tied" else SURFACE, mew=1.4)
            ax.set_xticks(x, [f"D{p['detector']}\n{p['approach']}" for p in ps], fontsize=7)
            ax.set_title(f"Measured − predicted displacement, {name}", fontsize=8.5)
        axes[0].set_ylabel("arcsec (thick: statistical; thin: total)")
        fig.tight_layout()
        paths.append(out_dir / f"{slug}_residuals.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 5. target fits: data, model, normalised residual
    if meas:
        fig, axes = plt.subplots(len(meas), 3, figsize=(5.4, 1.7 * len(meas)), squeeze=False)
        for i, r in enumerate(meas):
            st = r["stamps"]
            d, m, z = (np.asarray(st[k], dtype=float) for k in ("data", "model", "residual_over_sigma"))
            vmax = float(np.nanmax(m)) if np.isfinite(np.nanmax(m)) else 1.0
            for j, (arr, title, kw) in enumerate(((d, "data", {"cmap": "gray_r", "vmin": np.nanmin(m), "vmax": vmax}), (m, "ePSF + plane model", {"cmap": "gray_r", "vmin": np.nanmin(m), "vmax": vmax}),
                                                  (z, "(data − model)/σ", {"cmap": "RdBu_r", "vmin": -10, "vmax": 10}))):
                ax = axes[i][j]
                ax.imshow(arr, origin="lower", **kw)
                ax.set_xticks([])
                ax.set_yticks([])
                ax.grid(False)
                if i == 0:
                    ax.set_title(title, fontsize=7.5)
            axes[i][0].set_ylabel(f"D{r['detector']} S{r['season']}\nχ²/dof {r['measured']['chi2_red']:.0f}", fontsize=7)
        fig.suptitle("Target fits (9 × 9 px; residual colour range ±10σ)", fontsize=8.5)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        paths.append(out_dir / f"{slug}_fits.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 6. data-quality diagnostics per frame
    rows = res["frames"]
    if rows:
        fig, axes = plt.subplots(1, 4, figsize=(10.0, 3.0))
        labels = [f"D{r['detector']} S{r['season']}" for r in rows]
        x = np.arange(len(rows))
        snr = [r["stage1_snr"] or 0 for r in rows]
        axes[0].bar(x, snr, color=[ORANGE if r["status"] == "measured" else GRID for r in rows], width=0.6)
        axes[0].axhline(30, color=INK2, lw=0.8, ls="--")
        axes[0].set_title("stage-1 diagnostic S/N (threshold 30)", fontsize=8)
        chi = [r["measured"]["chi2_red"] if r["status"] == "measured" else 0 for r in rows]
        axes[1].bar(x, chi, color=ORANGE, width=0.6)
        axes[1].set_title("target fit χ²/dof", fontsize=8)
        axes[2].bar(x, [r["n_references"] for r in rows], color=BLUE, width=0.6)
        axes[2].axhline(5, color=INK2, lw=0.8, ls="--")
        axes[2].set_title("reference stars (tie needs 5)", fontsize=8)
        ac = [math.hypot(*r["analysis_choice_rms_px"]) if r["status"] == "measured" else 0 for r in rows]
        sg = [math.hypot(r["measured"]["sigma_x_px"], r["measured"]["sigma_y_px"]) if r["status"] == "measured" else 0 for r in rows]
        axes[3].bar(x - 0.18, ac, color=ORANGE, width=0.36, label="analysis-choice RMS")
        axes[3].bar(x + 0.18, sg, color=INK2, width=0.36, label="fit σ")
        axes[3].set_title("position systematics vs fit σ (px)", fontsize=8)
        axes[3].legend(fontsize=7)
        for ax in axes:
            ax.set_xticks(x, labels, fontsize=6.5, rotation=60)
        fig.tight_layout()
        paths.append(out_dir / f"{slug}_diagnostics.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    del offsets_mas
    return paths


def make_plots(res: dict, og, out_dir: Path, slug: str) -> list[Path]:  # noqa: ANN001 - ObservedGaia for the image stamps
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    pairs = [p for p in res["pairs"] if "measured_arcsec" in p]
    untied = (res.get("sensitivity_post_hoc") or {}).get("untied", {})
    upairs = untied.get("pairs", [])
    # 1. displacement vectors per pair (sky plane, east to the left, north up): row 1 primary (tied), row 2 post hoc (untied)
    rows_ = [("Primary: tied to reference stars", pairs), ("POST HOC: untied (archive WCS)", upairs)]
    rows_ = [(t, ps) for t, ps in rows_ if ps]
    if rows_:
        ncol = max(len(ps) for _, ps in rows_)
        fig, axes = plt.subplots(len(rows_), ncol, figsize=(2.3 * ncol, 2.6 * len(rows_) + 0.9), sharex=True, sharey=True, squeeze=False)
        allp = [p for _, ps in rows_ for p in ps]
        lim = 1.2 * max(max(abs(v) for v in p["predicted_arcsec"] + p["measured_arcsec"]) + max(p["sigma_total_arcsec"]) for p in allp)
        for i, (title, ps) in enumerate(rows_):
            for j in range(ncol):
                ax = axes[i][j]
                if j >= len(ps):
                    ax.set_visible(False)
                    continue
                p = ps[j]
                pe, pn = p["predicted_arcsec"]
                me, mn = p["measured_arcsec"]
                se, sn = p["sigma_total_arcsec"]
                ax.annotate("", xy=(pe, pn), xytext=(0, 0), arrowprops={"arrowstyle": "-|>", "color": BLUE, "lw": 1.6})
                ax.errorbar([me], [mn], xerr=[se], yerr=[sn], fmt="o", color=ORANGE, ms=6, elinewidth=1.2, capsize=0)
                ax.plot([0], [0], "o", color=INK2, ms=3)
                ax.set_xlim(lim, -lim)  # east to the left
                ax.set_ylim(-lim, lim)
                ax.set_aspect("equal")
                ax.set_title(f"{p['label']} ({p['role']})\n{p['from_utc'][:10]} → {p['to_utc'][:10]}", fontsize=7.5, color=INK)
                if i == len(rows_) - 1 or j >= len(rows_[-1][1]):
                    ax.set_xlabel("Δ east (″)", fontsize=8)
            axes[i][0].set_ylabel(f"{title}\nΔ north (″)", fontsize=8)
        handles = [plt.Line2D([], [], color=BLUE, lw=1.6, label="Gaia DR3 prediction (model)"),
                   plt.Line2D([], [], color=ORANGE, marker="o", ls="", ms=6, label="SPHEREx measurement ±1σ (ePSF on native pixels)")]
        fig.legend(handles=handles, loc="lower center", ncol=1, fontsize=8)
        fig.suptitle(f"{res['target']['name']}: displacement between the two seasons", fontsize=10, color=INK)
        fig.tight_layout(rect=(0, 0.1, 1, 0.95))
        paths.append(out_dir / f"{slug}_displacement_vectors.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 2. measured minus predicted per frame (tied), with the total budget; and the zero-displacement tests
    rows = [r for r in res["frames"] if r["status"] == "measured"]
    if rows:
        fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.2), sharey=True)
        labels = [f"D{r['detector']} S{r['season']}\n{r['mid_utc'][5:10]}" for r in rows]
        x = np.arange(len(rows))
        for k, (ax, name) in enumerate(zip(axes, ("east", "north"))):
            y = [r["tied_residual_arcsec"][k] for r in rows]
            s = [r["budget"]["total_arcsec"][k] for r in rows]
            ax.axhline(0, color=INK2, lw=0.8)
            ax.errorbar(x, y, yerr=s, fmt="o", color=ORANGE, ms=5, elinewidth=1.2, capsize=0)
            ax.set_xticks(x, labels, fontsize=7)
            ax.set_title(f"Measured − predicted, {name} (tied to reference stars)", fontsize=8.5)
        axes[0].set_ylabel("arcsec")
        fig.tight_layout()
        paths.append(out_dir / f"{slug}_residuals_per_frame.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    nulls = res["zero_displacement_tests"]
    null_title = "Zero-displacement tests of the error budget (expected 0 ± 1)"
    if not nulls and untied.get("zero_displacement_tests"):
        nulls = untied["zero_displacement_tests"]
        for p in nulls:
            p.setdefault("measured_minus_predicted_arcsec", [p["measured_arcsec"][k] - p["predicted_arcsec"][k] for k in (0, 1)])
        null_title = "POST HOC, untied positions: zero-displacement tests of the error budget (expected 0 ± 1)"
    if nulls:
        fig, ax = plt.subplots(figsize=(6.4, 2.8))
        x = np.arange(len(nulls))
        for k, (lab, mk) in enumerate((("east", "o"), ("north", "s"))):
            pull = [p["measured_minus_predicted_arcsec"][k] / p["sigma_total_arcsec"][k] for p in nulls]
            ax.plot(x + (k - 0.5) * 0.15, pull, mk, color=ORANGE if k == 0 else INK2, ms=6, ls="", label=f"{lab}: difference / σ")
        ax.axhline(0, color=INK2, lw=0.8)
        for v in (-3, 3):
            ax.axhline(v, color=INK2, lw=0.6, ls=":")
        ticks = [(f"D{p['detectors'][0]} vs D{p['detectors'][1]}" if p["detectors"][0] != p["detectors"][1] else f"D{p['detectors'][0]}, 2 exposures")
                 + f"\n{p['from_utc'][:10]}" for p in nulls]
        ax.set_xticks(x, ticks, fontsize=7)
        ax.set_ylabel("normalised difference")
        ax.set_title(null_title, fontsize=8)
        ax.legend(fontsize=7, loc="upper right")
        fig.tight_layout()
        paths.append(out_dir / f"{slug}_zero_displacement_tests.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    # 3. native-pixel stamps of the primary pairs with the predicted (+) and measured (x) positions
    prim = [p for p in pairs if p["role"] == "primary"]
    if prim:
        fig, axes = plt.subplots(2, len(prim), figsize=(2.2 * len(prim), 4.6), squeeze=False)
        by_id = {r["frame_id"]: r for r in res["frames"]}
        for j, p in enumerate(prim):
            for i, fid in enumerate((p["from"], p["to"])):
                r = by_id[fid]
                img = np.asarray(og.images[fid].image, dtype=float)
                cx, cy = int(round(r["measured"]["x_px"])), int(round(r["measured"]["y_px"]))
                h = 6
                stamp = img[cy - h : cy + h + 1, cx - h : cx + h + 1]
                bg = float(np.nanmedian(stamp))
                ax = axes[i][j]
                ax.imshow(np.arcsinh((stamp - bg) / max(float(np.nanstd(stamp)), 1e-9)), origin="lower", cmap="gray_r",
                          extent=(cx - h - 0.5, cx + h + 0.5, cy - h - 0.5, cy + h + 0.5))
                ax.plot(r["predicted"]["x_px"], r["predicted"]["y_px"], "+", color=BLUE, ms=11, mew=1.6)
                ax.plot(r["measured"]["x_px"], r["measured"]["y_px"], "x", color=ORANGE, ms=9, mew=1.6)
                ax.set_title(f"D{r['detector']} {r['mid_utc'][:10]}", fontsize=8)
                ax.set_xticks([])
                ax.set_yticks([])
                ax.grid(False)
        handles = [plt.Line2D([], [], color=BLUE, marker="+", ls="", ms=10, mew=1.6, label="Gaia DR3 prediction (model)"),
                   plt.Line2D([], [], color=ORANGE, marker="x", ls="", ms=8, mew=1.6, label="ePSF measurement")]
        fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=8)
        fig.suptitle("Native pixels around the target (13 × 13 px, arcsinh stretch)\ndetector orientation, not north-up", fontsize=8.5)
        fig.tight_layout(rect=(0, 0.06, 1, 0.94))
        paths.append(out_dir / f"{slug}_stamps.png")
        fig.savefig(paths[-1], dpi=150)
        plt.close(fig)
    return paths
