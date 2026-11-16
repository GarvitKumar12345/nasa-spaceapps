import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from skyshift.api.app import app
from skyshift.validation.report import REPO_ROOT


@pytest.mark.api
def test_recorded_evidence_export_contains_original_values_figures_and_integrity():
    c = TestClient(app)
    r = c.get('/api/datasets/spherex-dr1-vanmaanen2/target-motion/evidence.zip')
    assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        path = 'validation/vanmaanen2_motion_stage2.json'
        assert z.read(path) == (REPO_ROOT / path).read_bytes()
        assert 'validation/vanmaanen2_motion_stage2_pairs.csv' in z.namelist()
        assert len([n for n in z.namelist() if n.endswith('.png')]) == 6
        assert json.loads(z.read('integrity.json'))['integrity']['status'] == 'verified'
        assert 'not a synthetic notebook record' in z.read('REPRODUCE.txt').decode()
    assert c.get('/api/datasets/syn-nb-01/target-motion/evidence.zip').status_code == 409
    assert c.get('/api/studies/vanmaanen2/figures/unknown.png').status_code == 404
    image = c.get('/api/studies/vanmaanen2/figures/vanmaanen2_stage2_positions.png')
    assert image.status_code == 200 and image.content.startswith(b'\x89PNG')


@pytest.mark.api
def test_export_remains_available_when_cutouts_are_missing(tmp_path, monkeypatch):
    monkeypatch.setenv('SKYSHIFT_SPHEREX_CACHE', str(tmp_path))
    r = TestClient(app).get('/api/datasets/spherex-dr1-vanmaanen2/target-motion/evidence.zip')
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        status = json.loads(z.read('integrity.json'))['integrity']
        assert status['status'] == 'verified' and status['cache_status'] == 'missing'
        assert len(status['cache_missing']) == 13
