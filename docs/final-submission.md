# Final submission audit and next actions

This is the feature-frozen submission release on `session-4-estimator-review`. The reported deadline is 11:59 PM Eastern tonight. No push, merge, visibility change, tunnel or deployment was performed during this audit.

## Verified local release

- All 53 original uncommitted files were inventoried, hashed and reviewed by role: 22 runtime/generated-contract files, 10 tests, 7 documentation files, 2 validation artifacts and 12 isolated reference files. No unexpected environment/cache files or credential patterns were found. Detailed per-file hashes are in the local ignored artifact `validation/results/final-submission-audit.json`.
- The reference source matches the selected files from the supplied archive exactly and is not imported or served. Its unsupported scientific claims remain explicitly disclaimed.
- The staged whitespace check is clean for runtime, tests and documentation. It reports only inherited blank lines at EOF in five original reference-source files; these copies are intentionally preserved rather than reformatted. They do not affect the application or its validation.
- Dependency metadata and lockfiles are unchanged. `uv lock --check --offline` and `npm ls --depth=0` passed. No missing installed dependency was found; this was not a clean-machine network installation test.
- Final application validation: **203 backend passed, 5 live checks skipped; 107 frontend unit passed; 30 browser passed; 0 failures**. Production build runs `tsc -b` and passed. Existing chunk-size and mixed static/dynamic import warnings remain.
- The genuine report is dated **2026-11-16T03:52:06Z**, source identity `ee5b1c07e1053d14986564fd2a0c64c05ec4c0fac486e5cabb99d95c8a06b6de`. Its API is available with `stale=false`. Submission-mode changes are documentation only, so the completed run still covers the runtime code.
- Additional production-preview smoke passed at port 4173: Observatory, Motion lab, Evidence notebook, Methods, BlinkIR, the recorded target study and evidence ZIP download; no browser page errors. Logs: `validation/results/final-production-smoke.log`.
- Original scientific JSON, CSV, review and six Stage 2 figures match reference commit `0c7f4ab`. Primary tied D2 + D3 remains **5.8σ**, **0.94 ± 0.14**, **p = 0.93**. Exploratory **9.6σ** remains separate and post-hoc. No new fit was run.
- All five BlinkIR presets have simulated images, model-prediction spectra and arbitrary units. Observed extraction returns 409 unavailable without synthetic fallback. No verified atmosphere, calibrated flux or new discovery is claimed.

## Critical gaps before submission

1. **Public repository access is unverified.** Both the unauthenticated GitHub page and API returned HTTP 404 during this audit. This may reflect private visibility, an unavailable repository or another access issue; no authenticated account visibility was established. A successful authenticated push would not itself prove public readability.
2. **No public demonstration URL exists yet.** The current URLs are local to this computer. A temporary tunnel is optional after authorization; it is not durable hosting. Record/upload the five-minute demonstration and verify its viewing permissions before submission.
3. **Observed images are not in a fresh clone.** The source repository excludes 30 SPHEREx cutouts: Barnard 17 files / 68,232,960 bytes; van Maanen 2 13 files / 52,153,920 bytes. All are present locally and match the committed manifest SHA-256 values. Without them, observed images cannot be demonstrated; do not treat missing data as a simulation fallback. Gaia records, study JSON/CSV, seal and figures are in the source release. The recorded evidence export works without the cutouts.
4. **Complete the actual submission form.** Confirm team/challenge details, repository branch link, source/data credits, video permissions and any platform-required fields, then submit and retain the confirmation. Those external actions were not performed here.

## Fresh-checkout preparation

Run in PowerShell from the complete repository checkout, not an installed wheel or frontend-only upload:

```powershell
git switch session-4-estimator-review
uv sync --project backend --locked
npm.cmd ci
npm.cmd --prefix frontend ci
```

Restore images from their pinned archive manifests (requires IRSA availability):

```powershell
Push-Location backend
uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-vanmaanen2 --from-manifest
uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest
Pop-Location
npm.cmd run dev
```

No ESA query or scientific fitting rerun is needed for the committed study. If archive access fails tonight, a verified local backup was prepared **outside Git**:

`C:\Users\kumar\Downloads\skyshift-submission\skyshift-observed-cutouts.zip`

It contains only the 30 manifest-listed cutouts under `backend/cache/spherex/...`. SHA-256:

`fb519539a29423491c01b2238c5abf447a25149e87e1347b89f57b5b4d5bae21`

After copying that bundle to a new computer, verify and restore from the repository root:

```powershell
Get-FileHash -Algorithm SHA256 'C:\path\to\skyshift-observed-cutouts.zip'
# Proceed only if the checksum matches the value above.
Expand-Archive -LiteralPath 'C:\path\to\skyshift-observed-cutouts.zip' -DestinationPath .
```

Do not commit downloaded caches. Dependencies still require installation. Alignment caches are optional and regenerate; rebuilding scientific study outputs is unnecessary. Whole-application report hashes are byte-sensitive, so a different LF/CRLF checkout may correctly mark the application report stale; run the documented deterministic validation there if needed. The scientific seal separately normalizes text line endings.

A ready evidence package is also saved outside Git at `C:\Users\kumar\Downloads\skyshift-submission\skyshift-vanmaanen2-evidence.zip` (25 files, including six figures). It does not include image cutouts.

## Push only after explicit authorization

The following commands are provided for the next step; they were **not executed**. Run from the repository root:

```powershell
git status --short --branch
git log -1 --format='%H %s'
git push --set-upstream origin session-4-estimator-review
git ls-remote --heads origin refs/heads/session-4-estimator-review
```

The remote branch hash must match `git rev-parse HEAD`. No force push or merge into main is needed. Use the branch-specific source URL after access is verified:

https://github.com/GarvitKumar12345/nasa-spaceapps/tree/session-4-estimator-review

Check public access without credentials after pushing:

```powershell
curl.exe --fail --location --output NUL --write-out 'HTTP %{http_code}\n' 'https://github.com/GarvitKumar12345/nasa-spaceapps/tree/session-4-estimator-review'
```

Require HTTP 200 and open the same URL in a signed-out/private browser. A 404 remains a blocker; resolve account/repository access with the owner rather than claiming publication. No visibility change is authorized by this document.

## Optional temporary demonstration sharing — authorization required

This option exposes the existing built app while keeping its backend and verified image cache on this computer. It is a **temporary demonstration**, not production hosting or a durable judging URL. Quick Tunnels stop when their process exits, change hostname on restart and have no uptime guarantee. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

The local API is already running on 8000 and the built preview on 4173. Do not start duplicate listeners. If restarting the API, use a separate terminal:

```powershell
Set-Location 'C:\Users\kumar\Downloads\nasa spaceapps\backend'
uv run uvicorn skyshift.api.app:app --host 127.0.0.1 --port 8000
```

After authorization, use another terminal for a dedicated temporary-sharing preview on 4174:

```powershell
Set-Location 'C:\Users\kumar\Downloads\nasa spaceapps'
# Build already passed; do not change code for sharing.
$env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = '.trycloudflare.com'
npm.cmd --prefix frontend run preview -- --host 127.0.0.1 --port 4174 --strictPort
```

Vite preview inherits the existing `/api` proxy, so requests reach the backend on 8000. The environment variable adds the tunnel host without disabling host checks globally. See [Vite preview proxy](https://vite.dev/config/preview-options#preview-proxy) and [allowed hosts](https://vite.dev/config/server-options#server-allowedhosts).

`cloudflared` is not currently installed on this machine. For Windows x64, download the official executable in a third terminal, **after authorization** (the download URL was verified HTTP 200; no executable was downloaded or run during this audit):

```powershell
curl.exe --fail --location --output "$env:TEMP\cloudflared.exe" 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
& "$env:TEMP\cloudflared.exe" --version
& "$env:TEMP\cloudflared.exe" tunnel --url http://127.0.0.1:4174
```

For other operating systems, use [Cloudflare's official downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/).

Copy the actual printed HTTPS URL; do not invent one. Keep the API, preview and tunnel running. Keep the computer awake and connected. In another terminal, replace the placeholder and verify:

```powershell
$demoBase = 'https://ACTUAL-HOST.trycloudflare.com'
curl.exe --fail --location --output NUL --write-out 'HTTP %{http_code}\n' "$demoBase/"
curl.exe --fail "$demoBase/api/health"
curl.exe --fail "$demoBase/api/validation"
curl.exe --fail "$demoBase/api/datasets/spherex-dr1-vanmaanen2/target-motion"
curl.exe --fail --output "$env:TEMP\skyshift-public-evidence.zip" "$demoBase/api/datasets/spherex-dr1-vanmaanen2/target-motion/evidence.zip"
```

Open the real URL on a phone using cellular data: check both products, native seasonal images, simulation labels and both export types. A static frontend-only deployment or GitHub Pages alone cannot supply this Python API and image cache. For a durable submission demo, use an authorized full-stack host with the repository data and restored cutouts, or upload a publicly viewable recording. No such host/account is configured here.

## Submission checklist

- [x] Stable runtime code preserved; no submission-mode feature changes.
- [x] Original scientific results and origin labels checked.
- [x] Local validation and production-preview behavior checked.
- [x] Dependency locks and credential/accidental-file checks completed.
- [x] Concise five-minute script in `docs/demo-script.md`.
- [x] Submission copy in `docs/submission.md`; cache and evidence backup outside Git.
- [ ] Authorized branch push completed and remote hash matches.
- [ ] Repository readable by judges without a personal account.
- [ ] Video/public demo link verified from an external signed-out device.
- [ ] Team/challenge metadata, credits and required fields confirmed.
- [ ] Submission accepted before the stated deadline; confirmation retained.
