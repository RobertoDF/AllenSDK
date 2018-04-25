import pytest
import os
import tempfile
import logging
logging.basicConfig(level=logging.DEBUG)

import numpy as np
import pandas as pd

from allensdk.brain_observatory.drifting_gratings import DriftingGratings
from allensdk.brain_observatory.static_gratings import StaticGratings
from allensdk.brain_observatory.natural_movie import NaturalMovie
from allensdk.brain_observatory.natural_scenes import NaturalScenes
from allensdk.brain_observatory.locally_sparse_noise import LocallySparseNoise
from allensdk.brain_observatory.session_analysis import SessionAnalysis
from allensdk.core.brain_observatory_nwb_data_set import BrainObservatoryNwbDataSet as BODS
import allensdk.brain_observatory.stimulus_info as si

@pytest.fixture(scope="module")
def paths():
    return {
        'analysis_a': '/allen/aibs/informatics/module_test_data/observatory/py2_analysis/570305847_three_session_A_analysis.h5',
        'analysis_b': '/allen/aibs/informatics/module_test_data/observatory/py2_analysis/569407590_three_session_B_analysis.h5',
        'analysis_c': '/allen/aibs/informatics/module_test_data/observatory/py2_analysis/569494121_three_session_C2_analysis.h5',
        'nwb_a': '/allen/aibs/informatics/module_test_data/observatory/py2_analysis/570305847.nwb',        
        'nwb_b': '/allen/aibs/informatics/module_test_data/observatory/py2_analysis/569407590.nwb',
        'nwb_c': '/allen/aibs/informatics/module_test_data/observatory/py2_analysis/569494121.nwb'
    }

@pytest.fixture(scope="module")
def nwb_a(paths):
    return paths['nwb_a']

@pytest.fixture(scope="module")
def nwb_b(paths):
    return paths['nwb_b']

@pytest.fixture(scope="module")
def nwb_c(paths):
    return paths['nwb_c']

@pytest.fixture(scope="module")
def analysis_a(paths):
    return paths['analysis_a']

@pytest.fixture(scope="module")
def analysis_b(paths):
    return paths['analysis_b']

@pytest.fixture(scope="module")
def analysis_c(paths):
    return paths['analysis_c']

# session a

@pytest.fixture(scope="module")
def dg(nwb_a, analysis_a):
    return DriftingGratings.from_analysis_file(BODS(nwb_a), analysis_a)

@pytest.fixture(scope="module")
def nm1a(nwb_a, analysis_a):
    return NaturalMovie.from_analysis_file(BODS(nwb_a), analysis_a, si.NATURAL_MOVIE_ONE)

@pytest.fixture(scope="module")
def nm3(nwb_a, analysis_a):
    return NaturalMovie.from_analysis_file(BODS(nwb_a), analysis_a, si.NATURAL_MOVIE_THREE)

# session b

@pytest.fixture(scope="module")
def sg(nwb_b, analysis_b):
    return StaticGratings.from_analysis_file(BODS(nwb_b), analysis_b)

@pytest.fixture(scope="module")
def nm1b(nwb_b, analysis_b):
    return NaturalMovie.from_analysis_file(BODS(nwb_b), analysis_b, si.NATURAL_MOVIE_ONE)

@pytest.fixture(scope="module")
def ns(nwb_b, analysis_b):
    return NaturalScenes.from_analysis_file(BODS(nwb_b), analysis_b)

# session c
@pytest.fixture(scope="module")
def lsn(nwb_c, analysis_c):
    return LocallySparseNoise.from_analysis_file(BODS(nwb_c), analysis_c, si.LOCALLY_SPARSE_NOISE_8DEG)

@pytest.fixture(scope="module")
def nm1c(nwb_c, analysis_c):
    return NaturalMovie.from_analysis_file(BODS(nwb_c), analysis_c, si.NATURAL_MOVIE_ONE)

@pytest.fixture(scope="module")
def nm2(nwb_c, analysis_c):
    return NaturalMovie.from_analysis_file(BODS(nwb_c), analysis_c, si.NATURAL_MOVIE_TWO)

@pytest.fixture(scope="module")
def analysis_a_new(nwb_a):
    with tempfile.NamedTemporaryFile(delete=True) as tf:
        save_path = tf.name

    logging.debug("running analysis a")
    session_analysis = SessionAnalysis(nwb_a, save_path)
    session_analysis.session_a(plot_flag=False, save_flag=True)    
    logging.debug("done running analysis a")
    logging.debug(save_path)

    yield save_path

    if os.path.exists(save_path):
        os.remove(save_path)

@pytest.fixture(scope="module")
def analysis_b_new(nwb_b):
    with tempfile.NamedTemporaryFile(delete=True) as tf:
        save_path = tf.name

    logging.debug("running analysis b")
    session_analysis = SessionAnalysis(nwb_b, save_path)
    session_analysis.session_b(plot_flag=False, save_flag=True)    
    logging.debug("done running analysis b")
    logging.debug(save_path)

    yield save_path

    if os.path.exists(save_path):
        os.remove(save_path)

@pytest.fixture(scope="module")
def analysis_c_new(nwb_c):
    with tempfile.NamedTemporaryFile(delete=True) as tf:
        save_path = tf.name

    logging.debug("running analysis c")
    session_analysis = SessionAnalysis(nwb_c, save_path)
    session_analysis.session_c2(plot_flag=False, save_flag=True)    
    logging.debug("done running analysis c")
    logging.debug(save_path)

    yield save_path

    if os.path.exists(save_path):
        os.remove(save_path)


def compare_peak(p1, p2):
    assert len(set(p1.columns) ^ set(p2.columns)) == 0
    
    p1 = p1.infer_objects()
    p2 = p2.infer_objects()

    peak_blacklist = [ "rf_center_on_x_lsn",
                       "rf_center_on_y_lsn",
                       "rf_center_off_x_lsn",
                       "rf_center_off_y_lsn",
                       "rf_area_on_lsn",
                       "rf_area_off_lsn",
                       "rf_distance_lsn",
                       "rf_overlap_index_lsn",
                       "rf_chi2_lsn" ]

    for col in p1.select_dtypes(include=[np.number]):
        if col in peak_blacklist:
            print("skipping " + col)
            continue

        print("checking " + col)
        assert np.allclose(p1[col], p2[col], equal_nan=True)

    for col in p1.select_dtypes(include=['O']):
        print("checking " + col)
        assert all(p1[col] == p2[col])

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_session_a(analysis_a, analysis_a_new):
    peak = pd.read_hdf(analysis_a, "analysis/peak")
    new_peak = pd.read_hdf(analysis_a_new, "analysis/peak")
    compare_peak(peak, new_peak)


@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_drifting_gratings(dg, nwb_a, analysis_a_new):
    print("reading outputs")
    dg_new = DriftingGratings.from_analysis_file(BODS(nwb_a), analysis_a_new)
    #assert np.allclose(dg.sweep_response, dg_new.sweep_response)
    assert np.allclose(dg.mean_sweep_response, dg_new.mean_sweep_response, equal_nan=True)
        
    assert np.allclose(dg.response, dg_new.response, equal_nan=True)
    assert np.allclose(dg.noise_correlation, dg_new.noise_correlation, equal_nan=True)
    assert np.allclose(dg.signal_correlation, dg_new.signal_correlation, equal_nan=True)
    assert np.allclose(dg.representational_similarity, dg_new.representational_similarity, equal_nan=True)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_natural_movie_one_a(nm1a, nwb_a, analysis_a_new):
    nm1a_new = NaturalMovie.from_analysis_file(BODS(nwb_a), analysis_a_new, si.NATURAL_MOVIE_ONE)
    #assert np.allclose(nm1a.sweep_response, nm1a_new.sweep_response)
    assert np.allclose(nm1a.binned_cells_sp, nm1a_new.binned_cells_sp, equal_nan=True)
    assert np.allclose(nm1a.binned_cells_vis, nm1a_new.binned_cells_vis, equal_nan=True)
    assert np.allclose(nm1a.binned_dx_sp, nm1a_new.binned_dx_sp, equal_nan=True)
    assert np.allclose(nm1a.binned_dx_vis, nm1a_new.binned_dx_vis, equal_nan=True)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")    
def test_natural_movie_three(nm3, nwb_a, analysis_a_new):
    #nm3_new = NaturalMovie.from_analysis_file(BODS(nwb_a), analysis_a_new, si.NATURAL_MOVIE_THREE)
    #assert np.allclose(nm3.sweep_response, nm3_new.sweep_response)
    pass


@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_session_b(analysis_b, analysis_b_new):
    peak = pd.read_hdf(analysis_b, "analysis/peak")
    new_peak = pd.read_hdf(analysis_b_new, "analysis/peak")
    compare_peak(peak, new_peak)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_static_gratings(sg, nwb_b, analysis_b_new):
    sg_new = StaticGratings.from_analysis_file(BODS(nwb_b), analysis_b_new)
    #assert np.allclose(sg.sweep_response, sg_new.sweep_response)
    assert np.allclose(sg.mean_sweep_response, sg_new.mean_sweep_response, equal_nan=True)

    assert np.allclose(sg.response, sg_new.response, equal_nan=True)
    assert np.allclose(sg.noise_correlation, sg_new.noise_correlation, equal_nan=True)
    assert np.allclose(sg.signal_correlation, sg_new.signal_correlation, equal_nan=True)
    assert np.allclose(sg.representational_similarity, sg_new.representational_similarity, equal_nan=True)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_natural_movie_one_b(nm1b, nwb_b, analysis_b_new):    
    nm1b_new = NaturalMovie.from_analysis_file(BODS(nwb_b), analysis_b_new, si.NATURAL_MOVIE_ONE)
    #assert np.allclose(nm1b.sweep_response, nm1b_new.sweep_response)

    assert np.allclose(nm1b.binned_cells_sp, nm1b_new.binned_cells_sp, equal_nan=True)
    assert np.allclose(nm1b.binned_cells_vis, nm1b_new.binned_cells_vis, equal_nan=True)
    assert np.allclose(nm1b.binned_dx_sp, nm1b_new.binned_dx_sp, equal_nan=True)
    assert np.allclose(nm1b.binned_dx_vis, nm1b_new.binned_dx_vis, equal_nan=True)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_natural_scenes(ns, nwb_b, analysis_b_new):    
    ns_new = NaturalScenes.from_analysis_file(BODS(nwb_b), analysis_b_new)
    #assert np.allclose(ns.sweep_response, ns_new.sweep_response)
    assert np.allclose(ns.mean_sweep_response, ns_new.mean_sweep_response, equal_nan=True)

    assert np.allclose(ns.noise_correlation, ns_new.noise_correlation, equal_nan=True)
    assert np.allclose(ns.signal_correlation, ns_new.signal_correlation, equal_nan=True)
    assert np.allclose(ns.representational_similarity, ns_new.representational_similarity, equal_nan=True)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_session_c2(analysis_c, analysis_c_new):
    peak = pd.read_hdf(analysis_c, "analysis/peak")
    new_peak = pd.read_hdf(analysis_c_new, "analysis/peak")
    compare_peak(peak, new_peak)

@pytest.mark.skipif(os.getenv('TEST_COMPETE') != 'true',
                    reason="partial testing")
def test_locally_sparse_noise(lsn, nwb_c, analysis_c_new):
    lsn_new = LocallySparseNoise.from_analysis_file(BODS(nwb_c), analysis_c_new, si.LOCALLY_SPARSE_NOISE)
    #assert np.allclose(lsn.sweep_response, lsn_new.sweep_response)
    assert np.allclose(lsn.mean_sweep_response, lsn_new.mean_sweep_response, equal_nan=True)

@pytest.mark.skipif(os.getenv('TEST_COMPLETE') != 'true',
                    reason="partial testing")
def test_natural_movie_one_c(nm1c, nwb_c, analysis_c_new):    
    nm1c_new = NaturalMovie.from_analysis_file(BODS(nwb_c), analysis_c_new, si.NATURAL_MOVIE_ONE)
    #assert np.allclose(nm1c.sweep_response, nm1c_new.sweep_response)

    assert np.allclose(nm1c.binned_dx_sp, nm1c_new.binned_dx_sp, equal_nan=True) 
    assert np.allclose(nm1c.binned_dx_vis, nm1c_new.binned_dx_vis, equal_nan=True) 
    assert np.allclose(nm1c.binned_cells_sp, nm1c_new.binned_cells_sp, equal_nan=True) 
    assert np.allclose(nm1c.binned_cells_vis, nm1c_new.binned_cells_vis, equal_nan=True) 
    
    

