Extract running speed
=====================
Calculates an average running speed for the subject on each stimulus frame.


Running
-------
```
python -m allensdk.brain_observatory.multi_stimulus_running_speed --input_json <path to input json> --output_json <path to output json>
```
See the schema file for detailed information about input json contents.


Input data
----------
- Mapping stimulus pickle : Contains information about the mapping stimuli that were 
presented in this experiment.
- Behavior stimulus pickle : Contains information about the behavior stimuli that were 
presented in this experiment.
- Replay stimulus pickle : Contains information about the replay stimuli that were 
presented in this experiment.
- Sync h5 : Contains information about the times at which each frame was presented.


Output data
-----------
- Running speeds h5 : Contains two tables. These are:
  - running_speed : rows are intervals. Columns list frame times, frame indexes, mean velocities, and the net rotations from which those velocities are calculated. Known artifacts are removed, but the data are otherwise unfiltered.
  - raw_data : rows are samples. Columns list acquisition times, signal and supply voltages, and net rotations since the last timestamp.