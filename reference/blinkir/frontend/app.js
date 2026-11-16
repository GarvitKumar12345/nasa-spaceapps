let currentData = null;
let viewMode = "blink";
let blinkAlpha = 1.0;
let autoBlinkTimer = null;
let selectedBand = "all";
let clickedPx = [32, 32];
let aladinInstance = null;

document.addEventListener("DOMContentLoaded", async () => {
  initAladin();
  await loadPresets();

  const params = new URLSearchParams(window.location.search);
  const initialQuery = params.get("target") || params.get("query") || "WISE_0855";
  const initialMode = params.get("mode");
  if (initialMode === "diff") {
    setViewMode("diff");
  }

  await fetchCutout({ query: initialQuery });
  bindUIEvents();
});

function renderSkyContextMap(ra, dec, label) {
  const container = document.getElementById("aladinContainer");
  if (!container) return;

  // Try real AllWISE sky tile first; automatically fall back to local All-Sky Equatorial Map on error
  const hipsUrl =
    `https://alasky.cds.unistra.fr/hips-image-services/hips2fits` +
    `?hips=CDS/P/allWISE/color&width=360&height=220&fov=0.25` +
    `&projection=TAN&coordsys=icrs&ra=${encodeURIComponent(ra)}&dec=${encodeURIComponent(dec)}&format=jpg`;

  container.innerHTML = `
    <div style="position:relative;width:100%;height:100%;background:#050914;">
      <img id="wiseSkyImg" src="${hipsUrl}" alt="AllWISE Sky Context"
           style="width:100%;height:100%;object-fit:cover;display:block;" />
      <canvas id="localSkyMapCanvas" width="320" height="190"
              style="display:none;width:100%;height:100%;"></canvas>
      <div style="position:absolute;bottom:5px;left:6px;right:6px;display:flex;justify-content:space-between;font-size:0.68rem;color:#e2e8f0;background:rgba(7,11,20,0.8);padding:2px 6px;border-radius:4px;">
        <span id="skyCtxSource">AllWISE Infrared Context</span>
        <span>RA ${ra.toFixed(2)}°, Dec ${dec.toFixed(2)}°</span>
      </div>
    </div>
  `;

  const img = document.getElementById("wiseSkyImg");
  img.onerror = () => {
    img.style.display = "none";
    const cvs = document.getElementById("localSkyMapCanvas");
    cvs.style.display = "block";
    document.getElementById("skyCtxSource").textContent = "All-Sky ICRS Map (AllWISE/Gaia Ref)";
    drawLocalAllSkyCanvas(cvs, ra, dec);
  };
}

function drawLocalAllSkyCanvas(cvs, activeRa, activeDec) {
  const ctx = cvs.getContext("2d");
  const w = cvs.width;
  const h = cvs.height;

  ctx.fillStyle = "#050914";
  ctx.fillRect(0, 0, w, h);

  // Equatorial RA/Dec grid
  ctx.strokeStyle = "#16223b";
  ctx.lineWidth = 1;
  for (let i = 1; i < 6; i++) {
    ctx.beginPath();
    ctx.moveTo((w / 6) * i, 0);
    ctx.lineTo((w / 6) * i, h);
    ctx.stroke();
  }
  for (let j = 1; j < 4; j++) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 4) * j);
    ctx.lineTo(w, (h / 4) * j);
    ctx.stroke();
  }

  // Approximate Galactic Plane curve
  ctx.strokeStyle = "rgba(56, 189, 248, 0.22)";
  ctx.lineWidth = 8;
  ctx.beginPath();
  for (let ra = 0; ra <= 360; ra += 5) {
    const decGal = 62.6 * Math.sin(((ra - 282.25) * Math.PI) / 180);
    const x = ((360 - ra) / 360) * w;
    const y = ((90 - decGal) / 180) * h;
    if (ra === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Plot the 5 official NASA benchmark coordinates
  const benchmarks = [
    { name: "WISE 0855", ra: 133.8, dec: -7.2 },
    { name: "Barnard's", ra: 269.5, dec: 4.7 },
    { name: "Eps Indi B", ra: 331.0, dec: -56.8 },
    { name: "RW Aur", ra: 77.0, dec: 30.4 },
    { name: "R Dra", ra: 248.2, dec: 66.8 },
  ];
  benchmarks.forEach((b) => {
    const bx = ((360 - b.ra) / 360) * w;
    const by = ((90 - b.dec) / 180) * h;
    ctx.fillStyle = "#64748b";
    ctx.beginPath();
    ctx.arc(bx, by, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  // Highlight active target
  const ax = ((360 - ((activeRa % 360 + 360) % 360)) / 360) * w;
  const ay = ((90 - Math.max(-90, Math.min(90, activeDec))) / 180) * h;
  ctx.strokeStyle = "#f59e0b";
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  ctx.arc(ax, ay, 7, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = "#f59e0b";
  ctx.beginPath();
  ctx.arc(ax, ay, 2.5, 0, Math.PI * 2);
  ctx.fill();
}

function initAladin() {
  const ra = currentData ? currentData.ra : 133.795129;
  const dec = currentData ? currentData.dec : -7.245147;
  renderSkyContextMap(ra, dec);
}

async function loadPresets() {
  const res = await fetch("/api/presets");
  const data = await res.json();
  const listEl = document.getElementById("presetList");
  listEl.innerHTML = "";

  data.targets.forEach((t) => {
    const btn = document.createElement("button");
    btn.className = "preset-btn";
    btn.dataset.targetId = t.id;
    btn.innerHTML = `
      <span class="preset-title">${t.name}</span>
      <span class="preset-sub">${t.category} &bull; PM: ${t.proper_motion_arcsec_yr}"/yr</span>
    `;
    btn.addEventListener("click", () => {
      document.getElementById("searchInput").value = t.id;
      fetchCutout({ query: t.id });
    });
    listEl.appendChild(btn);
  });
}

async function fetchCutout({ query = null, ra = null, dec = null }) {
  const fov = parseFloat(document.getElementById("fovInput").value) || 0.04;
  const preferLive = document.getElementById("liveToggle").checked;
  const url = new URL("/api/sky-cutout", window.location.origin);
  if (query) url.searchParams.set("query", query);
  if (ra !== null && dec !== null) {
    url.searchParams.set("ra", ra);
    url.searchParams.set("dec", dec);
  }
  url.searchParams.set("fov", fov);
  url.searchParams.set("prefer_live", preferLive);

  document.getElementById("targetTitle").textContent = "Querying SPHEREx DR1 & QR3...";
  try {
    const res = await fetch(url);
    if (!res.ok) {
      const rawText = await res.text();
      let detail = `Server error (${res.status})`;
      try {
        detail = JSON.parse(rawText).detail || detail;
      } catch (_) {}
      document.getElementById("targetTitle").textContent = currentData?.resolved_name || "Query Failed";
      alert(detail);
      return;
    }
    currentData = await res.json();
    clickedPx = [Math.floor(currentData.grid_size / 2), Math.floor(currentData.grid_size / 2)];
    updateUI();
  } catch (err) {
    document.getElementById("targetTitle").textContent = currentData?.resolved_name || "Connection Error";
    alert("Network error querying backend: " + err.message);
  }
}

function updateUI() {
  if (!currentData) return;

  document.getElementById("targetTitle").textContent = currentData.resolved_name || "Custom Sky Region";
  document.getElementById("targetCoords").textContent =
    `ICRS: RA ${currentData.ra.toFixed(5)}°, Dec ${currentData.dec.toFixed(5)}° (${currentData.ra_hms || ""} ${currentData.dec_dms || ""}) | FOV ${currentData.fov_deg}°`;
  document.getElementById("scienceHighlight").textContent =
    currentData.highlight || "Click any source in the sky canvas to inspect its 102-band infrared spectrum.";

  document.querySelectorAll(".preset-btn").forEach((b) => {
    b.classList.toggle("selected", b.dataset.targetId === currentData.target_id);
  });

  const badge = document.getElementById("flagBadge");
  badge.textContent = currentData.flag_status || "CLEAN";
  badge.className = "pill " + (currentData.flag_status === "CLEAN" ? "pill-clean" : "pill-warn");
  document.getElementById("flagDetails").textContent = currentData.flag_details || "";

  document.getElementById("pmValueLabel").textContent =
    `${currentData.proper_motion_arcsec_yr ?? "0.00"} arcsec/yr`;
  document.getElementById("sourceModeLabel").textContent =
    `${currentData.source_mode} (${currentData.exposure_count} frames)`;

  // Update the bottom-left Sky Context box whenever a new target loads
  if (typeof renderSkyContextMap === "function") {
    renderSkyContextMap(currentData.ra, currentData.dec, currentData.resolved_name);
  } else if (aladinInstance) {
    aladinInstance.gotoRaDec(currentData.ra, currentData.dec);
  }

  // Gaia optical-veto status readout
  const gaiaStatus = currentData.gaia_status || currentData.gaia_source_mode || "LIVE_ESA_GAIA_TAP";
  const gaiaCount = (currentData.gaia_sources || []).length;

  let vetoHtml = "";
  if (gaiaStatus === "GAIA_TAP_UNAVAILABLE" || gaiaStatus === "GAIA_OFFLINE_UNAVAILABLE") {
    vetoHtml = `<span style="color: #fbbf24;">Gaia TAP offline — optical cross-match unavailable</span>`;
  } else if (gaiaCount === 0) {
    vetoHtml = `<span style="color: #38bdf8;">0 optical matches — IR-only candidate ✓</span>`;
  } else {
    vetoHtml = `<span style="color: #4ade80;">${gaiaCount} optical matches (${gaiaStatus})</span>`;
  }

  const vetoEl = document.getElementById("optical-veto-status");
  if (vetoEl) vetoEl.innerHTML = vetoHtml;
  const pipelineStatusEl = document.getElementById("pipelineStatus");
  if (pipelineStatusEl) pipelineStatusEl.textContent = `${gaiaCount} (${gaiaStatus})`;

  const pageUrl = new URL(window.location.href);
  pageUrl.searchParams.set("target", currentData.target_id || `${currentData.ra.toFixed(4)},${currentData.dec.toFixed(4)}`);
  pageUrl.searchParams.set("mode", viewMode);
  window.history.replaceState({}, "", pageUrl);

  renderCanvas();
  renderSpectrum();
}

function setViewMode(mode) {
  viewMode = mode;
  document.getElementById("modeBlinkBtn").classList.toggle("active-mode", mode === "blink");
  document.getElementById("modeDiffBtn").classList.toggle("active-mode", mode === "diff");
  renderCanvas();
}

function renderCanvas() {
  if (!currentData) return;
  const canvas = document.getElementById("blinkCanvas");
  const ctx = canvas.getContext("2d");
  const grid = currentData.grid_size || 64;
  const scale = canvas.width / grid;

  const ep1 = currentData.epoch1_image;
  const ep2 = selectedBand === "all"
    ? currentData.epoch2_image
    : (currentData.band_images[selectedBand] || currentData.epoch2_image);
  const diff = currentData.difference_image;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (let y = 0; y < grid; y++) {
    for (let x = 0; x < grid; x++) {
      if (viewMode === "diff") {
        const d = diff[y][x];
        const norm = Math.max(-1, Math.min(1, d / 2.2));
        let r = 24, g = 30, b = 44;
        if (norm > 0) {
          r = Math.round(24 + norm * 231);
          g = Math.round(30 + norm * 195);
          b = Math.round(44 + norm * 80);
        } else {
          const neg = -norm;
          r = Math.round(24 + neg * 20);
          g = Math.round(30 + neg * 150);
          b = Math.round(44 + neg * 211);
        }
        ctx.fillStyle = `rgb(${r},${g},${b})`;
      } else {
        const val = (1.0 - blinkAlpha) * ep1[y][x] + blinkAlpha * ep2[y][x];
        const intensity = Math.max(0, Math.min(255, Math.round((val / 3.8) * 255)));
        const r = Math.min(255, Math.round(intensity * 1.08));
        const g = Math.min(255, Math.round(intensity * 0.96));
        const b = Math.min(255, Math.round(intensity * 0.85));
        ctx.fillStyle = `rgb(${r},${g},${b})`;
      }
      ctx.fillRect(x * scale, y * scale, Math.ceil(scale), Math.ceil(scale));
    }
  }

  if (document.getElementById("overlayVectorsChk").checked && currentData.allwise_offset_px) {
    const cx = (grid / 2) * scale;
    const cy = (grid / 2) * scale;
    const [dxWise, dyWise] = currentData.allwise_offset_px;
    if (Math.hypot(dxWise, dyWise) > 0.5) {
      const wx = cx + dxWise * scale;
      const wy = cy + dyWise * scale;

      ctx.save();
      ctx.strokeStyle = "#f59e0b";
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(wx, wy);
      ctx.lineTo(cx, cy);
      ctx.stroke();

      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(wx, wy, 6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  // Overlay Gaia DR3 stars (clean rings + proper-motion trail, no canvas text)
  if (document.getElementById("gaiaOverlayChk").checked) {
    const w = canvas.width;
    const h = canvas.height;
    (currentData.gaia_sources || []).forEach((star) => {
      const sx = (star.gx / grid) * w;
      const sy = (star.gy / grid) * h;
      const sx16 = (star.gx_2016 / grid) * w;
      const sy16 = (star.gy_2016 / grid) * h;

      if (Math.hypot(sx - sx16, sy - sy16) > 3) {
        ctx.save();
        ctx.strokeStyle = "#4ade80";
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(sx16, sy16);
        ctx.lineTo(sx, sy);
        ctx.stroke();
        ctx.restore();
      }

      const isFastMover = star.total_pm_arcsec_yr > 1.0;
      ctx.strokeStyle = isFastMover ? "#22c55e" : "rgba(34, 197, 94, 0.45)";
      ctx.lineWidth = isFastMover ? 2 : 1;
      ctx.beginPath();
      ctx.arc(sx, sy, isFastMover ? 9 : 5, 0, Math.PI * 2);
      ctx.stroke();
    });
  }

  if (document.getElementById("crosshairChk").checked) {
    const [px, py] = clickedPx;
    const sx = (px + 0.5) * scale;
    const sy = (py + 0.5) * scale;
    ctx.save();
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(sx, sy, 11, 0, Math.PI * 2);
    ctx.moveTo(sx - 16, sy);
    ctx.lineTo(sx + 16, sy);
    ctx.moveTo(sx, sy - 16);
    ctx.lineTo(sx, sy + 16);
    ctx.stroke();
    ctx.restore();
  }
}

function renderSpectrum() {
  if (!currentData || !currentData.spectrum_102) return;
  const spec = currentData.spectrum_102;
  const grid = currentData.grid_size || 64;
  const center = grid / 2;
  const distFromCenter = Math.hypot(clickedPx[0] - center, clickedPx[1] - center);

  const isBackground = distFromCenter > 4.5;
  const xVals = spec.map((d) => d.wavelength_um);
  const yVals = spec.map((d) => (isBackground ? (d.bg_star_flux_mjy || d.flux_mjy * 0.4) : d.flux_mjy));

  const traces = [
    {
      x: xVals,
      y: yVals,
      mode: "lines+markers",
      name: isBackground ? "Selected Background Source" : currentData.resolved_name,
      line: { color: "#38bdf8", width: 2.2 },
      marker: { size: 4 },
    },
  ];

  if (document.getElementById("bgCompareChk").checked && !isBackground && spec[0].bg_star_flux_mjy) {
    traces.push({
      x: xVals,
      y: spec.map((d) => d.bg_star_flux_mjy),
      mode: "lines",
      name: "Reference Field Star",
      line: { color: "#64748b", width: 1.5, dash: "dot" },
    });
  }

  const shapes = [];
  const annotations = [];
  if (document.getElementById("molMarkersChk").checked) {
    shapes.push(
      { type: "rect", x0: 2.88, x1: 3.15, y0: 0, y1: 1, yref: "paper", fillcolor: "rgba(56,189,248,0.12)", line: { width: 0 } },
      { type: "rect", x0: 3.20, x1: 3.45, y0: 0, y1: 1, yref: "paper", fillcolor: "rgba(245,158,11,0.14)", line: { width: 0 } }
    );
    annotations.push(
      { x: 3.01, y: 0.96, yref: "paper", text: "H2O Ice", showarrow: false, font: { size: 10, color: "#38bdf8" } },
      { x: 3.33, y: 0.86, yref: "paper", text: "CH4 Methane", showarrow: false, font: { size: 10, color: "#f59e0b" } }
    );
  }

  const layout = {
    paper_bgcolor: "#0a101d",
    plot_bgcolor: "#0a101d",
    margin: { t: 24, r: 14, b: 40, l: 48 },
    font: { color: "#cbd5e1", size: 11 },
    xaxis: { title: "Wavelength (microns, 0.75 - 5.0 um)", gridcolor: "#1e2a45" },
    yaxis: { title: "Flux (mJy)", gridcolor: "#1e2a45" },
    legend: { orientation: "h", y: 1.14, x: 0 },
    shapes,
    annotations,
  };

  Plotly.newPlot("spectrumChart", traces, layout, { displayModeBar: false, responsive: true });
}

function bindUIEvents() {
  document.getElementById("searchBtn").addEventListener("click", () => {
    const q = document.getElementById("searchInput").value.trim();
    if (q) fetchCutout({ query: q });
  });

  document.getElementById("searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("searchBtn").click();
  });

  document.getElementById("modeBlinkBtn").addEventListener("click", () => setViewMode("blink"));
  document.getElementById("modeDiffBtn").addEventListener("click", () => setViewMode("diff"));

  document.getElementById("blinkSlider").addEventListener("input", (e) => {
    blinkAlpha = parseInt(e.target.value, 10) / 100.0;
    document.getElementById("blinkPctLabel").textContent = `${e.target.value}% QR3`;
    if (viewMode !== "blink") setViewMode("blink");
    else renderCanvas();
  });

  document.getElementById("autoBlinkBtn").addEventListener("click", (e) => {
    if (autoBlinkTimer) {
      clearInterval(autoBlinkTimer);
      autoBlinkTimer = null;
      e.target.textContent = "Auto-Blink: OFF";
    } else {
      setViewMode("blink");
      e.target.textContent = "Auto-Blink: ON";
      autoBlinkTimer = setInterval(() => {
        blinkAlpha = blinkAlpha > 0.5 ? 0.0 : 1.0;
        const pct = Math.round(blinkAlpha * 100);
        document.getElementById("blinkSlider").value = pct;
        document.getElementById("blinkPctLabel").textContent = `${pct}% QR3`;
        renderCanvas();
      }, 650);
    }
  });

  document.getElementById("bandSelect").addEventListener("change", (e) => {
    selectedBand = e.target.value;
    document.getElementById("bandLabel").textContent =
      selectedBand === "all" ? "All 6 Bands Co-Add" : `Band ${selectedBand}`;
    renderCanvas();
  });

  document.getElementById("overlayVectorsChk").addEventListener("change", renderCanvas);
  document.getElementById("gaiaOverlayChk").addEventListener("change", renderCanvas);
  document.getElementById("crosshairChk").addEventListener("change", renderCanvas);
  document.getElementById("molMarkersChk").addEventListener("change", renderSpectrum);
  document.getElementById("bgCompareChk").addEventListener("change", renderSpectrum);

  document.getElementById("blinkCanvas").addEventListener("click", (e) => {
    if (!currentData) return;
    const rect = e.target.getBoundingClientRect();
    const grid = currentData.grid_size || 64;
    const gx = Math.floor(((e.clientX - rect.left) / rect.width) * grid);
    const gy = Math.floor(((e.clientY - rect.top) / rect.height) * grid);
    clickedPx = [Math.max(0, Math.min(grid - 1, gx)), Math.max(0, Math.min(grid - 1, gy))];
    document.getElementById("clickedPixelLabel").textContent = `Pixel (${clickedPx[0]}, ${clickedPx[1]})`;
    renderCanvas();
    renderSpectrum();
  });

  document.getElementById("shareUrlBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(window.location.href);
    alert("Shareable discovery permalink copied to clipboard!");
  });

  document.getElementById("exportCardBtn").addEventListener("click", async () => {
    if (!currentData) return;
    const payload = {
      target_name: currentData.resolved_name || "Candidate",
      ra: currentData.ra,
      dec: currentData.dec,
      fov_deg: currentData.fov_deg,
      measured_shift_arcsec: (currentData.proper_motion_arcsec_yr || 0) * 0.5,
      proper_motion_arcsec_yr: currentData.proper_motion_arcsec_yr || 0,
      flag_status: currentData.flag_status || "CLEAN",
      notes: "Extracted via SkyShift 4D SPHEREx DR1+QR3 Blink & 102-Band Spectrometer",
    };
    const res = await fetch("/api/export-candidate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const card = await res.json();
    const blob = new Blob([JSON.stringify(card, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `SkyShift_DiscoveryCard_${(currentData.target_id || "Custom")}.json`;
    a.click();
  });
}

