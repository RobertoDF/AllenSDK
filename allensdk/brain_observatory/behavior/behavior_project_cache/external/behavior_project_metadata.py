import argparse
import logging
import os
from typing import Union

import pandas as pd

from allensdk.brain_observatory.behavior.behavior_project_cache import \
    BehaviorProjectCache
from allensdk.brain_observatory.behavior.behavior_project_cache.tables \
    .experiments_table import \
    ExperimentsTable
from allensdk.brain_observatory.behavior.behavior_project_cache.tables \
    .ophys_sessions_table import \
    BehaviorOphysSessionsTable
from allensdk.brain_observatory.behavior.behavior_project_cache.tables \
    .sessions_table import \
    SessionsTable


class BehaviorProjectMetadataWriter:
    """Class to write project-level metadata to csv"""

    def __init__(self, behavior_project_cache: BehaviorProjectCache,
                 out_dir: str):
        self._behavior_project_cache = behavior_project_cache
        self._out_dir = out_dir
        self._logger = logging.getLogger(self.__class__.__name__)

    def write_metadata(self):
        """Writes metadata to csv"""
        os.makedirs(self._out_dir, exist_ok=True)

        behavior_suppress = [
            'donor_id',
            'foraging_id'
        ]
        ophys_suppress = [
            'session_name',
            'donor_id',
            'specimen_id'
        ]
        ophys_experiments_suppress = ophys_suppress + [
            'container_workflow_state',
            'behavior_session_uuid',
            'experiment_workflow_state',
            'published_at',
        ]

        behavior_sessions = self._get_behavior_sessions(
            suppress=behavior_suppress)
        ophys_sessions = self._get_behavior_ophys_sessions(
            suppress=ophys_suppress)
        ophys_experiments = self._get_behavior_ophys_experiments(
            suppress=ophys_experiments_suppress)

        self._write_file(df=behavior_sessions,
                         filename='behavior_session_table.csv')
        self._write_file(df=ophys_sessions,
                         filename='ophys_session_table.csv')
        self._write_file(df=ophys_experiments,
                         filename='ophys_experiment_table.csv')

    def _get_behavior_sessions(self, suppress=None) -> pd.DataFrame:
        behavior_sessions = self._behavior_project_cache. \
            get_behavior_session_table(suppress=suppress, as_df=False)
        return self._get_release_table(table=behavior_sessions)

    def _get_behavior_ophys_sessions(self, suppress=None) -> pd.DataFrame:
        ophys_sessions = self._behavior_project_cache. \
            get_session_table(suppress=suppress, as_df=False)
        return self._get_release_table(table=ophys_sessions)

    def _get_behavior_ophys_experiments(self, suppress=None) -> pd.DataFrame:
        ophys_experiments = self._behavior_project_cache.get_experiment_table(
            suppress=suppress, as_df=False)
        return self._get_release_table(table=ophys_experiments)

    def _get_release_table(self,
                           table: Union[
                               SessionsTable,
                               BehaviorOphysSessionsTable,
                               ExperimentsTable]) -> pd.DataFrame:
        """Takes as input an entire project-level table and filters it to
        include records which we are releasing data for

        Parameters
        ----------
        table
            The project table to filter

        Returns
        --------
        The filtered dataframe
        """
        if isinstance(table, SessionsTable):
            release_table = self._get_behavior_release_table(table=table)
        elif isinstance(table, BehaviorOphysSessionsTable):
            release_table = self._get_ophys_session_release_table(table=table)
        elif isinstance(table, ExperimentsTable):
            release_table = self._get_ophys_experiment_release_table(
                table=table)
        else:
            raise ValueError(f'Bad table {type(table)}')

        return release_table

    def _get_behavior_release_table(self,
                                    table: SessionsTable) -> pd.DataFrame:
        """Returns behavior sessions release table

        Parameters
        ----------
        table
            SessionsTable

        Returns
        ---------
        Dataframe including release behavior-only sessions and
            behavior ophys sessions with nwb metadta for behavior-only
            sessions"""
        table = table.table

        # 1) Filter to release "behavior-only" sessions, which get nwb files
        behavior_release_files = self._get_release_files(
            file_type='BehaviorNwb')
        behavior_only_sessions = table.merge(behavior_release_files,
                                             left_index=True,
                                             right_index=True)

        # 2) Filter to release ophys sessions (but they get no nwb files)
        ophys_release_files = self._get_release_files(
            file_type='BehaviorOphysNwb')
        ophys_session_ids = self._get_ophys_sessions_from_ophys_experiments(
            ophys_experiment_ids=ophys_release_files.index
        )
        ophys_sessions = table[table['ophys_session_id']
            .isin(ophys_session_ids)]
        return pd.concat([behavior_only_sessions, ophys_sessions], sort=False)

    def _get_ophys_session_release_table(
            self, table: BehaviorOphysSessionsTable) -> pd.DataFrame:
        """Returns ophys sessions release table

        Parameters
        ----------
        table
            BehaviorOphysSessionsTable

        Returns
        --------
        Dataframe including release ophys sessions
        """
        # ophys sessions are different because the nwb files for ophys
        # sessions are at the experiment level.
        # We don't want to associate these sessions with nwb files
        release_files = self._get_release_files(
            file_type='BehaviorOphysNwb')
        ophys_session_ids = \
            self._get_ophys_sessions_from_ophys_experiments(
                ophys_experiment_ids=release_files.index)
        return table.table[table.table.index.isin(ophys_session_ids)]

    def _get_ophys_experiment_release_table(
            self, table: ExperimentsTable) -> pd.DataFrame:
        """Returns ophys experiment release table

        Parameters
        ----------
        table
            ExperimentsTable

        Returns
        --------
        Dataframe including release ophys experiments with nwb file metadata
        """
        release_files = self._get_release_files(
            file_type='BehaviorOphysNwb')
        return table.table.merge(release_files, left_index=True,
                                 right_index=True)

    def _get_release_files(self, file_type='BehaviorNwb') -> pd.DataFrame:
        """Gets the release nwb files.

        Parameters
        ----------
        file_type
            NWB files to return ('BehaviorNwb', 'BehaviorOphysNwb')

        Returns
        ---------
        Dataframe of release files and file metadata
        """
        if file_type not in ('BehaviorNwb', 'BehaviorOphysNwb'):
            raise ValueError(f'cannot retrieve file type {file_type}')

        if file_type == 'BehaviorNwb':
            attachable_id_alias = 'behavior_session_id'
        else:
            attachable_id_alias = 'ophys_experiment_id'

        query = f'''
            SELECT attachable_id as {attachable_id_alias}, id as file_id, 
            filename, storage_directory
            FROM well_known_files 
            WHERE published_at IS NOT NULL AND 
                well_known_file_type_id IN (
                    SELECT id 
                    FROM well_known_file_types 
                    WHERE name = '{file_type}'
                );
        '''
        res = self._behavior_project_cache.fetch_api.lims_engine.select(query)
        res['isilon_filepath'] = res['storage_directory'] \
            .str.cat(res['filename'])
        res = res.drop(['filename', 'storage_directory'], axis=1)
        return res.set_index(attachable_id_alias)

    def _get_ophys_sessions_from_ophys_experiments(
            self, ophys_experiment_ids: pd.Series):
        session_query = self._behavior_project_cache.fetch_api. \
            build_in_list_selector_query(
            "oe.id", ophys_experiment_ids.to_list())

        query = f'''
            SELECT os.id as ophys_session_id
            FROM ophys_sessions os
            JOIN ophys_experiments oe on oe.ophys_session_id = os.id
            {session_query}
        '''
        res = self._behavior_project_cache.fetch_api.lims_engine.select(query)
        return res['ophys_session_id']

    def _write_file(self, df: pd.DataFrame, filename: str):
        filepath = os.path.join(self._out_dir, filename)
        self._logger.info(f'Writing {filepath}')

        df = df.reset_index()
        df.to_csv(filepath, index=False)

        self._logger.info('Writing successful')

def main():
    parser = argparse.ArgumentParser(description='Write project metadata to '
                                                 'csvs')
    parser.add_argument('-out_dir', help='directory to save csvs',
                        required=True)
    args = parser.parse_args()

    bpc = BehaviorProjectCache.from_lims()
    bpmw = BehaviorProjectMetadataWriter(behavior_project_cache=bpc,
                                         out_dir=args.out_dir)
    bpmw.write_metadata()


if __name__ == '__main__':
    main()
