"""Pre-download screening of discovered images by byte-range reads (~75 kB per image).

For each Spectral Image only the PRIMARY + IMAGE headers (start of file) and the
WCS-WAVE table (end of file) are read with HTTP Range requests; the server must
answer 206 or the request is refused. From these the query position's detector
pixel (TAN-SIP header WCS), its edge margin and the local wavelength/bandwidth
(documented WCS-WAVE lookup) are computed before any cutout is requested.
"""

from __future__ import annotations

import warnings

from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

from skyshift.providers.spherex.discovery import DiscoveryRow
from skyshift.providers.spherex.http import ArchiveClient
from skyshift.providers.spherex.reference import DETECTOR_SHAPE
from skyshift.providers.spherex.wavelength import WaveTable, wavelength_astropy, wavelength_bilinear

BLOCK = 2880
HEAD_BYTES = 14 * BLOCK
TAIL_BYTES = 12 * BLOCK
SCREEN_HEADER_KEYS = (
    "OBSID", "DETECTOR", "EXPIDN", "TIMESYS", "DATE-BEG", "MJD-BEG", "DATE-AVG", "MJD-AVG", "DATE-END", "MJD-END", "XPOSURE",
    "FINAST", "L1DQAFLG", "L2DQAFLG", "ASTRONETSOLVED", "MATCH_NSTARS", "PSF_FWHM", "CRPIX1W", "CRPIX2W",
)


def _read_header(buf: bytes, off: int) -> tuple[fits.Header, int]:
    out = bytearray()
    while True:
        blk = buf[off : off + BLOCK]
        if len(blk) < BLOCK:
            raise ValueError("header truncated in the fetched byte range")
        out += blk
        off += BLOCK
        for i in range(0, BLOCK, 80):
            if blk[i : i + 80].rstrip() == b"END":
                return fits.Header.fromstring(out.decode("ascii")), off


def _data_bytes(h: fits.Header) -> int:
    n = abs(int(h.get("BITPIX", 8))) // 8 * int(h.get("GCOUNT", 1)) * (int(h.get("PCOUNT", 0)) + _prod([int(h.get(f"NAXIS{i}", 0)) for i in range(1, int(h.get("NAXIS", 0)) + 1)]))
    return ((n + BLOCK - 1) // BLOCK) * BLOCK


def _prod(v: list[int]) -> int:
    p = 1
    for x in v:
        p *= x
    return p if v else 0


def fetch_headers(client: ArchiveClient, url: str) -> tuple[fits.Header, fits.Header, fits.HDUList, list[dict]]:
    """(PRIMARY header, IMAGE header, HDUList[Primary, WCS-WAVE]) of a full file via two range reads."""
    records = []
    head, rec = client.get(url, byte_range=f"bytes=0-{HEAD_BYTES - 1}", max_bytes=HEAD_BYTES)
    records.append(rec.as_dict())
    primary, off = _read_header(head, 0)
    off += _data_bytes(primary)
    image, _ = _read_header(head, off)
    if str(image.get("EXTNAME", "")).strip() != "IMAGE":
        raise ValueError(f"first extension is {image.get('EXTNAME')!r}, expected IMAGE")
    tail, rec2 = client.get(url, byte_range=f"bytes=-{TAIL_BYTES}", max_bytes=TAIL_BYTES)
    records.append(rec2.as_dict())
    for k in range(0, len(tail) - BLOCK + 1, BLOCK):
        if not tail[k : k + BLOCK].startswith(b"XTENSION= 'BINTABLE'"):
            continue
        try:
            h, end = _read_header(tail, k)
        except ValueError:
            continue
        if str(h.get("EXTNAME", "")).strip() != "WCS-WAVE":
            continue
        data = tail[end : end + _data_bytes(h)]
        hdul = fits.HDUList.fromstring(fits.PrimaryHDU().header.tostring().encode("ascii") + tail[k:end] + data)
        return primary, image, fits.HDUList([fits.PrimaryHDU(), hdul["WCS-WAVE"].copy()]), records
    raise ValueError("WCS-WAVE table not found in the final bytes of the file")


def screen_row(client: ArchiveClient, row: DiscoveryRow, ra_deg: float, dec_deg: float) -> dict:
    """Screening record for one discovered image (raises on request or parse failure)."""
    primary, image, wave, records = fetch_headers(client, row.access_url)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        w = WCS(image)
    x, y = (float(v) for v in w.all_world2pix([[ra_deg, dec_deg]], 0, tolerance=1e-8, maxiter=50)[0])
    ny, nx = int(image["NAXIS2"]), int(image["NAXIS1"])
    margin = min(x, y, nx - 1 - x, ny - 1 - y)
    inside = margin >= 0
    lam = bw = lam2 = bw2 = None
    if inside:
        lam, bw = wavelength_astropy(image, wave, x, y)
        lam2, bw2 = wavelength_bilinear(image, WaveTable.from_hdu(wave["WCS-WAVE"]), x, y)
    hdr = {k: (image[k].strip() if isinstance(image[k], str) else image[k]) for k in SCREEN_HEADER_KEYS if k in image}
    consistent = str(hdr.get("OBSID", "")) == row.obs_id and int(hdr.get("DETECTOR", -1)) == row.detector
    return {
        "obs_id": row.obs_id, "detector": row.detector, "file_name": row.file_name, "status": "screened",
        "pipeline_version": str(primary.get("VERSION", "")).strip(), "image_shape": [ny, nx],
        "full_frame": [ny, nx] == list(DETECTOR_SHAPE),
        "query_pixel_detector": [round(x, 4), round(y, 4)], "inside": inside, "edge_margin_px": round(margin, 3),
        "lambda_um": lam, "bandwidth_um": bw, "lambda_um_independent": lam2, "bandwidth_um_independent": bw2,
        "identity_consistent": consistent, "header": hdr, "requests": records,
    }
