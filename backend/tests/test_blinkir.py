import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from skyshift.api.app import app


@pytest.mark.api
def test_all_supplied_simulations_have_explicit_origins_and_deterministic_images():
    c = TestClient(app)
    presets = c.get('/api/blinkir/presets').json()
    assert presets['origin'] == 'simulated' and len(presets['presets']) == 5
    for p in presets['presets']:
        r = c.get('/api/blinkir/simulation/' + p['id'])
        assert r.status_code == 200
        s = r.json()
        assert s['origin'] == 'simulated' and s['spectrum_origin'] == 'model_prediction'
        assert len(s['spectrum']) == 102 and len(s['images']) == 2
        assert np.asarray(s['images']).shape == (2, 64, 64)
        assert not np.array_equal(s['images'][0], s['images'][1])
        assert s['epochs'] == ['Simulated epoch A', 'Simulated epoch B']
        assert 'arbitrary' in s['units'] and 'not observed' in s['limitations'][0]
        assert not any(k in s for k in ['flux_mjy', 'exposure_count', 'measured_shift_arcsec'])
        assert c.get('/api/blinkir/simulation/' + p['id']).json()['images'] == s['images']
    assert c.get('/api/blinkir/simulation/unknown').status_code == 404


@pytest.mark.api
def test_unavailable_observations_never_fall_back_to_simulation():
    r = TestClient(app).get('/api/blinkir/observations')
    assert r.status_code == 409 and 'no synthetic fallback' in r.json()['detail']
    assert 'images' not in r.json()


@pytest.mark.api
def test_lesson_export_cannot_be_mistaken_for_real_measurements():
    c = TestClient(app)
    r = c.post('/api/blinkir/export', json={'preset':'WISE_0855', 'x': 30, 'y': 31, 'detector':4, 'notes':'lesson'})
    assert r.status_code == 200
    data = json.loads(r.content)
    assert data['schema'] == 'skyshift.blinkir-lesson/1' and data['origin'] == 'simulated'
    assert data['measured_motion'] is None and data['calibrated_flux'] is None
    assert data['selected_pixel']['x'] == 30 and len(data['illustrative_model_samples']) == 102
    assert c.post('/api/blinkir/export', json={'preset':'WISE_0855', 'x':64}).status_code == 422
