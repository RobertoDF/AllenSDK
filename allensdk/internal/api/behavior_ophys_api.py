import logging
from typing import Optional
from pathlib import Path

import numpy as np
import h5py
import pandas as pd
import uuid
import matplotlib.image as mpimg  # NOQA: E402

from allensdk.api.cache import memoize
from allensdk.internal.api.ophys_lims_api import OphysLimsApi
from allensdk.brain_observatory.behavior.sync import (
    get_sync_data, get_stimulus_rebase_function, frame_time_offset)
from allensdk.brain_observatory.sync_dataset import Dataset
from allensdk.brain_observatory import sync_utilities
from allensdk.internal.brain_observatory.time_sync import OphysTimeAligner
from allensdk.brain_observatory.behavior.stimulus_processing import get_stimulus_presentations, get_stimulus_templates, get_stimulus_metadata
from allensdk.brain_observatory.behavior.metadata_processing import get_task_parameters
from allensdk.brain_observatory.behavior.running_processing import get_running_df
from allensdk.brain_observatory.behavior.rewards_processing import get_rewards
from allensdk.brain_observatory.behavior.trials_processing import get_trials
from allensdk.brain_observatory.behavior.eye_tracking_processing import load_eye_tracking_hdf, process_eye_tracking_data
from allensdk.brain_observatory.running_speed import RunningSpeed
from allensdk.brain_observatory.behavior.image_api import ImageApi
from allensdk.internal.api import PostgresQueryMixin
from allensdk.brain_observatory.behavior.behavior_ophys_api import BehaviorOphysApiBase
from allensdk.brain_observatory.behavior.trials_processing import get_extended_trials
from allensdk.internal.core.lims_utilities import safe_system_path
from allensdk.core.auth_config import LIMS_DB_CREDENTIAL_MAP
from allensdk.core.authentication import credential_injector, DbCredentials


class BehaviorOphysLimsApi(OphysLimsApi, BehaviorOphysApiBase):

    def __init__(self, ophys_experiment_id: int,
                 lims_credentials: Optional[DbCredentials] = None):
        super().__init__(ophys_experiment_id, lims_credentials)
        self.logger = logging.getLogger(self.__class__.__name__)

    @memoize
    def get_sync_data(self):
        sync_path = self.get_sync_file()
        return get_sync_data(sync_path)

    @memoize
    def get_stimulus_timestamps(self):
        sync_path = self.get_sync_file()
        timestamps, _, _ = (OphysTimeAligner(sync_file=sync_path)
                            .corrected_stim_timestamps)
        return timestamps

    @staticmethod
    def _process_ophys_plane_timestamps(
            ophys_timestamps: np.ndarray, plane_group: Optional[int],
            group_count: int):
        """
        On mesoscope rigs each frame corresponds to a different imaging plane;
        the laser moves between N pairs of planes. So, every Nth 2P
        frame time in the sync file corresponds to a given plane (and
        its multiplexed pair). The order in which the planes are
        acquired dictates which timestamps should be assigned to which
        plane pairs. The planes are acquired in ascending order, where
        plane_group=0 is the first group of planes.

        If the plane group is None (indicating it does not belong to
        a plane group), then the plane was not collected concurrently
        and the data do not need to be resampled. This is the case for
        Scientifica 2p data, for example.

        Parameters
        ----------
        ophys_timestamps: np.ndarray
            Array of timestamps for 2p data
        plane_group: int
            The plane group this experiment belongs to. Signals the
            order of acquisition.
        group_count: int
            The total number of plane groups acquired.
        """
        if (group_count == 0) or (plane_group is None):
            return ophys_timestamps
        resampled = ophys_timestamps[plane_group::group_count]
        return resampled

    @memoize
    def get_ophys_timestamps(self):

        ophys_timestamps = self.get_sync_data()['ophys_frames']
        dff_traces = self.get_raw_dff_data()
        plane_group = self.get_imaging_plane_group()

        number_of_cells, number_of_dff_frames = dff_traces.shape
        # Scientifica data has extra frames in the sync file relative
        # to the number of frames in the video. These sentinel frames
        # should be removed.
        # NOTE: This fix does not apply to mesoscope data.
        # See http://confluence.corp.alleninstitute.org/x/9DVnAg
        if plane_group is None:    # non-mesoscope
            num_of_timestamps = len(ophys_timestamps)
            if (number_of_dff_frames < num_of_timestamps):
                self.logger.info(
                    "Truncating acquisition frames ('ophys_frames') "
                    f"(len={num_of_timestamps}) to the number of frames "
                    f"in the df/f trace ({number_of_dff_frames}).")
                ophys_timestamps = ophys_timestamps[:number_of_dff_frames]
            elif number_of_dff_frames > num_of_timestamps:
                raise RuntimeError(
                    f"dff_frames (len={number_of_dff_frames}) is longer "
                    f"than timestamps (len={num_of_timestamps}).")
        # Mesoscope data
        # Resample if collecting multiple concurrent planes (e.g. mesoscope)
        # because the frames are interleaved
        else:
            group_count = self.get_plane_group_count()
            self.logger.info(
                "Mesoscope data detected. Splitting timestamps "
                f"(len={len(ophys_timestamps)} over {group_count} "
                "plane group(s).")
            ophys_timestamps = self._process_ophys_plane_timestamps(
                ophys_timestamps, plane_group, group_count)
            num_of_timestamps = len(ophys_timestamps)
            if number_of_dff_frames != num_of_timestamps:
                raise RuntimeError(
                    f"dff_frames (len={number_of_dff_frames}) is not equal to "
                    f"number of split timestamps (len={num_of_timestamps}).")
        return ophys_timestamps

    @memoize
    def get_experiment_container_id(self):
        query = '''
                SELECT visual_behavior_experiment_container_id
                FROM ophys_experiments_visual_behavior_experiment_containers
                WHERE ophys_experiment_id= {};
                '''.format(self.get_ophys_experiment_id())
        return self.lims_db.fetchone(query, strict=False)

    @memoize
    def get_behavior_stimulus_file(self):
        query = '''
                SELECT stim.storage_directory || stim.filename AS stim_file
                FROM ophys_experiments oe
                JOIN ophys_sessions os ON oe.ophys_session_id = os.id
                JOIN behavior_sessions bs ON bs.ophys_session_id=os.id
                LEFT JOIN well_known_files stim ON stim.attachable_id=bs.id AND stim.attachable_type = 'BehaviorSession' AND stim.well_known_file_type_id IN (SELECT id FROM well_known_file_types WHERE name = 'StimulusPickle')
                WHERE oe.id= {};
                '''.format(self.get_ophys_experiment_id())
        return safe_system_path(self.lims_db.fetchone(query, strict=True))

    def get_behavior_session_uuid(self):
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        return data['session_uuid']

    @memoize
    def get_stimulus_frame_rate(self):
        stimulus_timestamps = self.get_stimulus_timestamps()
        return np.round(1 / np.mean(np.diff(stimulus_timestamps)), 0)

    @memoize
    def get_ophys_frame_rate(self):
        ophys_timestamps = self.get_ophys_timestamps()
        return np.round(1 / np.mean(np.diff(ophys_timestamps)), 0)

    @memoize
    def get_metadata(self):

        metadata = super().get_metadata()
        metadata['ophys_experiment_id'] = self.get_ophys_experiment_id()
        metadata['experiment_container_id'] = self.get_experiment_container_id()
        metadata['ophys_frame_rate'] = self.get_ophys_frame_rate()
        metadata['stimulus_frame_rate'] = self.get_stimulus_frame_rate()
        metadata['targeted_structure'] = self.get_targeted_structure()
        metadata['imaging_depth'] = self.get_imaging_depth()
        metadata['session_type'] = self.get_stimulus_name()
        metadata['experiment_datetime'] = self.get_experiment_date()
        metadata['reporter_line'] = self.get_reporter_line()
        metadata['driver_line'] = self.get_driver_line()
        metadata['LabTracks_ID'] = self.get_external_specimen_name()
        metadata['full_genotype'] = self.get_full_genotype()
        metadata['behavior_session_uuid'] = uuid.UUID(self.get_behavior_session_uuid())
        metadata["imaging_plane_group"] = self.get_imaging_plane_group()

        return metadata

    @memoize
    def get_dff_traces(self):
        dff_traces = self.get_raw_dff_data()
        cell_roi_id_list = self.get_cell_roi_ids()
        df = pd.DataFrame({'dff': [x for x in dff_traces]}, index=pd.Index(cell_roi_id_list, name='cell_roi_id'))

        cell_specimen_table = self.get_cell_specimen_table()
        df = cell_specimen_table[['cell_roi_id']].join(df, on='cell_roi_id')
        return df

    @memoize
    def get_running_data_df(self, lowpass=True):
        stimulus_timestamps = self.get_stimulus_timestamps()
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        return get_running_df(data, stimulus_timestamps, lowpass=lowpass)

    @memoize
    def get_running_speed(self, lowpass=True):
        running_data_df = self.get_running_data_df(lowpass=lowpass)
        assert running_data_df.index.name == 'timestamps'
        return RunningSpeed(timestamps=running_data_df.index.values,
                            values=running_data_df.speed.values)

    @memoize
    def get_stimulus_presentations(self):
        stimulus_timestamps = self.get_stimulus_timestamps()
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        stimulus_presentations_df_pre = get_stimulus_presentations(data, stimulus_timestamps)
        stimulus_metadata_df = get_stimulus_metadata(data)
        idx_name = stimulus_presentations_df_pre.index.name
        stimulus_index_df = stimulus_presentations_df_pre.reset_index().merge(stimulus_metadata_df.reset_index(), on=['image_name']).set_index(idx_name)
        stimulus_index_df.sort_index(inplace=True)
        stimulus_index_df = stimulus_index_df[['image_set', 'image_index', 'start_time',
                                               'phase', 'spatial_frequency']].rename(columns={'start_time': 'timestamps'})
        stimulus_index_df.set_index('timestamps', inplace=True, drop=True)
        stimulus_presentations_df = stimulus_presentations_df_pre.merge(stimulus_index_df, left_on='start_time', right_index=True, how='left')
        assert len(stimulus_presentations_df_pre) == len(stimulus_presentations_df)

        return stimulus_presentations_df[sorted(stimulus_presentations_df.columns)]

    @memoize
    def get_stimulus_templates(self):
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        return get_stimulus_templates(data)

    @memoize
    def get_sync_licks(self):
        lick_times = self.get_sync_data()['lick_times']
        return pd.DataFrame({'time': lick_times})

    @memoize
    def get_licks(self):
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        rebase_function = self.get_stimulus_rebase_function()
        # Get licks from pickle file (need to add an offset to align with
        # the trial_log time stream)
        lick_frames = (data["items"]["behavior"]["lick_sensors"][0]
                       ["lick_events"])
        vsyncs = data["items"]["behavior"]["intervalsms"]
        vsync_times_raw = np.hstack((0, vsyncs)).cumsum() / 1000.0  # cumulative time
        vsync_offset = frame_time_offset(data)
        vsync_times = vsync_times_raw + vsync_offset
        lick_times = [vsync_times[frame] for frame in lick_frames]
        # Align pickle data with sync time stream
        return pd.DataFrame({"time": list(map(rebase_function, lick_times))})

    @memoize
    def get_rewards(self):
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        rebase_function = self.get_stimulus_rebase_function()
        return get_rewards(data, rebase_function)

    @memoize
    def get_task_parameters(self):
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        return get_task_parameters(data)

    @memoize
    def get_trials(self):

        licks = self.get_licks()
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        rewards = self.get_rewards()
        stimulus_presentations = self.get_stimulus_presentations()
        rebase_function = self.get_stimulus_rebase_function()
        trial_df = get_trials(data, licks, rewards, stimulus_presentations, rebase_function)

        return trial_df

    @memoize
    def get_corrected_fluorescence_traces(self):
        demix_file = self.get_demix_file()

        g = h5py.File(demix_file)
        corrected_fluorescence_trace_array = np.asarray(g['data'])
        g.close()

        cell_roi_id_list = self.get_cell_roi_ids()
        ophys_timestamps = self.get_ophys_timestamps()
        assert corrected_fluorescence_trace_array.shape[1], ophys_timestamps.shape[0]
        df = pd.DataFrame({'corrected_fluorescence': list(corrected_fluorescence_trace_array)}, index=pd.Index(cell_roi_id_list, name='cell_roi_id'))

        cell_specimen_table = self.get_cell_specimen_table()
        df = cell_specimen_table[['cell_roi_id']].join(df, on='cell_roi_id')
        return df

    @memoize
    def get_average_projection(self, image_api=None):

        if image_api is None:
            image_api = ImageApi

        avgint_a1X_file = self.get_average_intensity_projection_image_file()
        pixel_size = self.get_surface_2p_pixel_size_um()
        average_image = mpimg.imread(avgint_a1X_file)
        return ImageApi.serialize(average_image, [pixel_size / 1000., pixel_size / 1000.], 'mm')

    @memoize
    def get_motion_correction(self):
        motion_correction_filepath = self.get_rigid_motion_transform_file()
        motion_correction = pd.read_csv(motion_correction_filepath)
        return motion_correction[['x', 'y']]

    @memoize
    def get_nwb_filepath(self):

        query = '''
                SELECT wkf.storage_directory || wkf.filename AS nwb_file
                FROM ophys_experiments oe
                LEFT JOIN well_known_files wkf ON wkf.attachable_id=oe.id AND wkf.well_known_file_type_id IN (SELECT id FROM well_known_file_types WHERE name = 'BehaviorOphysNwb')
                WHERE oe.id = {};
                '''.format(self.get_ophys_experiment_id())
        return safe_system_path(self.lims_db.fetchone(query, strict=True))

    def get_stimulus_rebase_function(self):
        stimulus_timestamps_no_monitor_delay = self.get_sync_data()['stimulus_times_no_delay']
        behavior_stimulus_file = self.get_behavior_stimulus_file()
        data = pd.read_pickle(behavior_stimulus_file)
        stimulus_rebase_function = get_stimulus_rebase_function(data, stimulus_timestamps_no_monitor_delay)
        return stimulus_rebase_function

    def get_extended_trials(self):
        filename = self.get_behavior_stimulus_file()
        data = pd.read_pickle(filename)
        return get_extended_trials(data)

    @memoize
    def get_eye_tracking_filepath(self):
        query = '''SELECT wkf.storage_directory || wkf.filename AS eye_tracking_file
                   FROM ophys_experiments oe
                   LEFT JOIN well_known_files wkf ON wkf.attachable_id=oe.ophys_session_id
                   AND wkf.attachable_type = 'OphysSession'
                   AND wkf.well_known_file_type_id=(SELECT id FROM well_known_file_types WHERE name = 'EyeTracking Ellipses')
                   WHERE oe.id={};
                   '''.format(self.get_ophys_experiment_id())
        return safe_system_path(self.lims_db.fetchone(query, strict=True))

    def get_eye_tracking(self,
                         z_threshold: float = 3.0,
                         dilation_frames: int = 2):
        logger = logging.getLogger("BehaviorOphysLimsApi")

        logger.info(f"Getting eye_tracking_data with "
                    f"'z_threshold={z_threshold}', "
                    f"'dilation_frames={dilation_frames}'")

        filepath = Path(self.get_eye_tracking_filepath())
        sync_path = Path(self.get_sync_file())

        eye_tracking_data = load_eye_tracking_hdf(filepath)
        frame_times = sync_utilities.get_synchronized_frame_times(
            session_sync_file=sync_path,
            sync_line_label_keys=Dataset.EYE_TRACKING_KEYS,
            trim_after_spike=False)

        eye_tracking_data = process_eye_tracking_data(eye_tracking_data,
                                                      frame_times,
                                                      z_threshold,
                                                      dilation_frames)

        return eye_tracking_data

    @staticmethod
    def get_ophys_experiment_df():

        api = (credential_injector(LIMS_DB_CREDENTIAL_MAP)
               (PostgresQueryMixin)())
        query = '''
                SELECT

                oec.visual_behavior_experiment_container_id as container_id,
                oec.ophys_experiment_id,
                oe.workflow_state,
                d.full_genotype as full_genotype,
                id.depth as imaging_depth,
                st.acronym as targeted_structure,
                os.name as session_name,
                equipment.name as equipment_name

                FROM ophys_experiments_visual_behavior_experiment_containers oec
                LEFT JOIN ophys_experiments oe ON oe.id = oec.ophys_experiment_id
                LEFT JOIN ophys_sessions os ON oe.ophys_session_id = os.id
                LEFT JOIN specimens sp ON sp.id=os.specimen_id
                LEFT JOIN donors d ON d.id=sp.donor_id
                LEFT JOIN imaging_depths id ON id.id=oe.imaging_depth_id
                LEFT JOIN structures st ON st.id=oe.targeted_structure_id
                LEFT JOIN equipment ON equipment.id=os.equipment_id
                '''

        return pd.read_sql(query, api.get_connection())

    @staticmethod
    def get_containers_df(only_passed=True):

        api = (credential_injector(LIMS_DB_CREDENTIAL_MAP)
               (PostgresQueryMixin)())
        if only_passed is True:
            query = '''
                    SELECT *
                    FROM visual_behavior_experiment_containers vbc
                    WHERE workflow_state IN ('container_qc','publish');
                    '''
        else:
            query = '''
                    SELECT *
                    FROM visual_behavior_experiment_containers vbc
                    '''

        return pd.read_sql(query, api.get_connection()).rename(columns={'id': 'container_id'})[['container_id', 'specimen_id', 'workflow_state']]

    @classmethod
    def get_api_list_by_container_id(cls, container_id):

        df = cls.get_ophys_experiment_df()
        oeid_list = df[df['container_id'] == container_id]['ophys_experiment_id'].values
        return [cls(oeid) for oeid in oeid_list]


if __name__ == "__main__":

    print(BehaviorOphysLimsApi.get_ophys_experiment_df())
    # print(BehaviorOphysLimsApi.get_containers_df(only_passed=False))

    # print(BehaviorOphysLimsApi.get_api_by_container(838105949))

    # ophys_experiment_id = df['ophys_experiment_id'].iloc[0]
    # print(ophys_experiment_id)
    # BehaviorOphysLimsApi
    # print(L)
    # for c in sorted(L.columns):
    #     print(c)
    # for x in [791352433, 814796698, 814796612, 814796558, 814797528]:
    #     print(x in L)
