"""Coordinate, WCS, and pixel-convention checks."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.wcs import WCS, Sip

from skyshift.coords.tangent import (
    MAS_PER_RAD,
    angular_separation_deg,
    offsets_mas,
    sky_to_tangent,
    tangent_to_sky,
    validate_dec_deg,
    wrap_ra_deg,
)
from skyshift.coords.wcs import (
    description_to_wcs,
    local_jacobian_mas_per_px,
    make_tan_wcs,
    pixel_to_sky,
    sky_to_pixel,
    wcs_to_description,
)

pytestmark = pytest.mark.coords


def test_ra_wrap_edge_cases():
    """RA wraps into [0, 360) for negative, >360, exact-360 and -0.0 inputs."""
    out = wrap_ra_deg(np.array([-1e-12, -0.0, 360.0, 720.5, -90.0, 359.9999999]))
    assert np.all((out >= 0) & (out < 360))
    assert out[2] == 0.0 and out[3] == pytest.approx(0.5) and out[4] == pytest.approx(270.0)
    assert not np.signbit(wrap_ra_deg(-0.0))


def test_tangent_projection_across_ra_zero():
    """Points straddling RA 0/360 project to small symmetric east offsets (not ~360 deg) and round-trip."""
    xi, _ = sky_to_tangent(np.array([359.999, 0.001]), np.array([10.0, 10.0]), 0.0, 10.0)
    east = xi * MAS_PER_RAD
    expected = 0.001 * 3.6e6 * np.cos(np.radians(10.0))
    assert east[0] == pytest.approx(-expected, rel=1e-6) and east[1] == pytest.approx(expected, rel=1e-6)
    _, eta = sky_to_tangent(np.array([359.999, 0.001]), np.array([10.0, 10.0]), 0.0, 10.0)
    ra, _ = tangent_to_sky(xi, eta, 0.0, 10.0)
    assert ra[0] == pytest.approx(359.999, abs=1e-9) and ra[1] == pytest.approx(0.001, abs=1e-9)


def test_separation_across_wrap_matches_small_angle():
    """Great-circle separation across RA 0 equals the small-angle value (Vincenty)."""
    assert angular_separation_deg(359.9995, 0.0, 0.0005, 0.0) == pytest.approx(0.001, rel=1e-9)


def test_declination_conventions():
    """|Dec| > 90 or non-finite declinations are rejected; +north is +eta."""
    for bad in (90.0001, -91.0, np.nan):
        with pytest.raises(ValueError):
            validate_dec_deg(bad)
    _, eta = sky_to_tangent(10.0, 20.001, 10.0, 20.0)
    assert eta > 0


def test_gnomonic_round_trip_and_undefined_hemisphere():
    """Gnomonic round trip agrees to < 1e-6 mas; points >= 90 deg from the tangent point raise."""
    rng = np.random.default_rng(3)
    ra = 123.4 + rng.uniform(-0.05, 0.05, 100)
    dec = -45.6 + rng.uniform(-0.05, 0.05, 100)
    e, n = offsets_mas(ra, dec, 123.4, -45.6)
    ra2, dec2 = tangent_to_sky(e / MAS_PER_RAD, n / MAS_PER_RAD, 123.4, -45.6)
    assert np.max(angular_separation_deg(ra, dec, ra2, dec2)) * 3.6e6 < 1e-6
    with pytest.raises(ValueError):
        sky_to_tangent(0.0, -60.0, 0.0, 40.0)


def test_pixel_origin_convention():
    """0-based pixel centre (CRPIX - 1) maps to CRVAL; astropy origin 0 vs 1 differ by exactly 1 px."""
    w = make_tan_wcs(150.0, 2.0, 0.4, (100, 120))
    assert w.wcs.crpix[0] == pytest.approx((120 - 1) / 2 + 1) and w.wcs.crpix[1] == pytest.approx((100 - 1) / 2 + 1)
    ra, dec = pixel_to_sky(w, (120 - 1) / 2, (100 - 1) / 2)
    assert float(ra) == pytest.approx(150.0, abs=1e-12) and float(dec) == pytest.approx(2.0, abs=1e-12)
    ra0, dec0 = w.all_pix2world(10.0, 20.0, 0)
    ra1, dec1 = w.all_pix2world(11.0, 21.0, 1)
    assert ra0 == pytest.approx(ra1, abs=1e-12) and dec0 == pytest.approx(dec1, abs=1e-12)


def test_orientation_north_up_east_left_and_rotation_sign():
    """+x is west (east left), +y is north; rotation is the PA of +y measured east of north."""
    w = make_tan_wcs(180.0, 35.0, 0.4, (160, 160))
    e, n = offsets_mas(*pixel_to_sky(w, 89.5, 79.5), 180.0, 35.0)
    assert float(e) == pytest.approx(-4000.0, abs=1e-3) and abs(float(n)) < 1e-3
    w30 = make_tan_wcs(180.0, 35.0, 0.4, (160, 160), rotation_deg=30.0)
    e, n = offsets_mas(*pixel_to_sky(w30, 79.5, 89.5), 180.0, 35.0)
    assert float(e) == pytest.approx(4000.0 * np.sin(np.radians(30)), abs=1e-3)
    assert float(n) == pytest.approx(4000.0 * np.cos(np.radians(30)), abs=1e-3)


@pytest.mark.parametrize("dec0", [89.99, -89.99, 90.0])
def test_wcs_round_trip_near_poles(dec0):
    """Pixel -> sky -> pixel round trip < 1e-6 px at and next to the poles (numerical round trip only)."""
    w = make_tan_wcs(77.0, dec0, 0.4, (160, 160))
    gx, gy = np.meshgrid(np.linspace(-0.5, 159.5, 9), np.linspace(-0.5, 159.5, 9))
    ra, dec = pixel_to_sky(w, gx.ravel(), gy.ravel())
    assert np.all((ra >= 0) & (ra < 360)) and np.all(np.abs(dec) <= 90)
    x, y = sky_to_pixel(w, ra, dec)
    assert np.max(np.hypot(x - gx.ravel(), y - gy.ravel())) < 1e-6


def _sip_wcs() -> WCS:
    w = make_tan_wcs(30.0, -20.0, 0.4, (200, 200))
    w.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
    a = np.zeros((4, 4))
    b = np.zeros((4, 4))
    a[2, 0], a[0, 2], a[1, 1] = 2.0e-5, -1.0e-5, 1.5e-5
    b[2, 0], b[0, 2], b[1, 1] = -1.2e-5, 2.5e-5, 0.8e-5
    w.sip = Sip(a, b, None, None, w.wcs.crpix)
    w.wcs.set()
    return w


def test_sip_distortion_numerical_round_trip_and_effect():
    """SIP WCS: pixel->sky->pixel < 1e-6 px (numerical), and positions move by the A/B polynomial amounts."""
    w = _sip_wcs()
    gx, gy = np.meshgrid(np.linspace(0, 199, 11), np.linspace(0, 199, 11))
    ra, dec = pixel_to_sky(w, gx.ravel(), gy.ravel())
    x, y = sky_to_pixel(w, ra, dec)
    assert np.max(np.hypot(x - gx.ravel(), y - gy.ravel())) < 1e-6
    ra_t, dec_t = pixel_to_sky(make_tan_wcs(30.0, -20.0, 0.4, (200, 200)), gx.ravel(), gy.ravel())
    shift_px = angular_separation_deg(ra, dec, ra_t, dec_t) * 3600.0 / 0.4
    u = gx.ravel() - (w.wcs.crpix[0] - 1)
    v = gy.ravel() - (w.wcs.crpix[1] - 1)
    du = 2.0e-5 * u**2 - 1.0e-5 * v**2 + 1.5e-5 * u * v
    dv = -1.2e-5 * u**2 + 2.5e-5 * v**2 + 0.8e-5 * u * v
    np.testing.assert_allclose(shift_px, np.hypot(du, dv), rtol=2e-3, atol=2e-4)
    assert shift_px.max() > 0.3


def test_wcs_description_round_trip_including_sip():
    """Serialised header -> WCS reproduces positions (< 1e-6 mas) for TAN and SIP headers."""
    for w in (make_tan_wcs(200.0, 10.0, 0.4, (80, 90), rotation_deg=12.0), _sip_wcs()):
        shape = (int(w.pixel_shape[1]), int(w.pixel_shape[0]))
        desc = wcs_to_description(w, shape, "native_header")
        w2 = description_to_wcs(desc)
        gx, gy = np.meshgrid(np.linspace(0, shape[1] - 1, 7), np.linspace(0, shape[0] - 1, 7))
        r1, d1 = pixel_to_sky(w, gx.ravel(), gy.ravel())
        r2, d2 = pixel_to_sky(w2, gx.ravel(), gy.ravel())
        assert np.max(angular_separation_deg(r1, d1, r2, d2)) * 3.6e6 < 1e-6
        assert desc.distortion == ("sip" if w.sip is not None else "none")


def test_local_jacobian_equals_cd_matrix():
    """At the reference pixel the finite-difference Jacobian equals the CD matrix (mas/px, east = +RA)."""
    w = make_tan_wcs(45.0, 30.0, 0.4, (100, 100), rotation_deg=20.0)
    jac = local_jacobian_mas_per_px(w, 49.5, 49.5)
    np.testing.assert_allclose(jac, np.asarray(w.pixel_scale_matrix) * 3.6e6, rtol=1e-6, atol=1e-6)
