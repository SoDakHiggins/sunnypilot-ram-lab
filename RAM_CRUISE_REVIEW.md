# Ram cruise development lab — candidate map-clock correction

This review branch contains the offline trace reviewer plus a candidate correction
to GPS timestamp handling in the map speed-limit resolver. That correction changes
which map targets can reach speed planning. It has not been installed on a comma.
Do not install this branch: isolated source tests are not full-stack validation.
No validated driving fix or installation package is provided.

## How this fits together

GitHub stores the code and its history. This fork is a separate development copy
of sunnypilot. Sunnylink is the dashboard for an installed device; it does not
automatically deploy commits from this repository. A future device build would
need a deliberate installation path, backup, rollback procedure and validation.
No device installation, update, remote-access change or setting change was made.

## First reproducible source issue

The installed resolver subtracts `gps_data.unixTimestampMillis` (Unix calendar
time) from `time.monotonic()` (a clock with an unrelated origin). With normal
Unix timestamps this produces a large negative age, so an old GPS fix can pass
the freshness check. The same mismatch in distance calculation can put an
upcoming limit at an unrealistically large distance instead of anticipating it.
`system/ubloxd/ubloxd.py` assigns this GPS field from UTC, confirming its clock
domain. This is a source-level finding, not a diagnosis of the reported incident.

The candidate uses Unix time for both calculations, rejects fixes older than ten
seconds or more than one second in the future, and prevents negative travelled
distance. The one-second future tolerance permits small GPS/system clock skew;
it is a candidate threshold, not a validated guarantee for all clock adjustments.
It does not change the desired deceleration, curve-speed thresholds, retained
last-valid-limit behavior, cruise engagement or CAN commands.

### Validation performed

| Check | Installed baseline | Candidate |
| --- | --- | --- |
| Fresh GPS accepted | Pass | Pass |
| GPS older than 10 seconds rejected | Fail | Pass |
| GPS more than one second in the future rejected | Fail | Pass |
| Small future skew accepted without negative travel | Fail (distance) | Pass |
| Missing/zero timestamp rejected | Pass | Pass |
| Exactly 10-second age accepted | Pass | Pass |
| Just over 10-second age rejected | Fail | Pass |
| Two-second fix age updates distance correctly | Fail | Pass |
| Passed waypoint distance clamps to zero | Fail | Pass |

All 70 checks pass:

- 12 isolated map-clock checks executing the actual two source methods.
- 5 checks using the matching real Cap'n Proto schemas and binary serialization
  with synthetic inputs, including the original stale-fix error.
- 8 checks executing the unchanged ICBM class with enum/message stand-ins.
- 10 offline trace-reviewer checks, including signed estimated vehicle speed.
- 35 resolver-module tests, comprising 24 existing cases with corrected Unix-time
  fixtures and 11 new age/distance cases. These import the whole resolver and use
  locally compiled native Params and messaging bindings, with mocked data inputs.

The installed-baseline run intentionally fails 7 of the 12 isolated clock cases,
showing the tests detect the original clock/distance problem. Python 3.12.14 and
pycapnp 2.1.0 were used. Local x86-64 Params and msgq bindings were compiled from
matching repository source with official comma dependency packages. This is
resolver-module validation, not a full driving-stack build or test. The targeted
pytest run excludes repository-wide manager/hardware hooks and uses a separate
local parameter prefix. It reports three dependency/configuration warnings.
No vehicle simulation, full upstream-suite run, hardware test or road test has
been performed. All checked-in message fixtures are synthetic.

```sh
python3 -m unittest test_ram_map_clock.py test_ram_icbm_source.py test_ram_cruise_review.py test_ram_clock_schema.py -v
RAM_RESOLVER_BASELINE=1 python3 -m unittest test_ram_map_clock.py -v
# Requires the matching Python/native development dependencies:
OPENPILOT_PREFIX=ram_clock_review python3 -m pytest -o addopts='' \
  --confcutdir=sunnypilot/selfdrive/controls/lib/speed_limit/tests \
  sunnypilot/selfdrive/controls/lib/speed_limit/tests/test_speed_limit_resolver.py -q
```

### What remains unresolved

- Whether this clock mismatch contributed to the actual 55-mph selection.
- Whether that selection came from a map value, retained limit, or factory resume.
- Last-valid speed limits may still be retained after current input becomes invalid;
  this candidate deliberately does not redesign that behavior.
- ICBM consumes the target speed, not the planner's acceleration request. The
  eight source checks confirm this and manual-button/cancel/override behavior,
  but they cannot establish real Ram braking smoothness or CAN timing.
- A stale GPS fix and an outdated map are separate issues; this correction does
  not prove that the map data itself is current or correct.
- Behavior during larger device clock adjustments, startup and missing map input
  still needs evaluation before any deployment. A small future-skew allowance
  does not establish correct behavior under every clock change.

## Baseline

- Device observed: comma four, sunnypilot 2026.002.002, release-mici.
- Exact source baseline: `6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2`.
- Vehicle detected by device: `RAM_1500_5TH_GEN`.
- The public fork contains code and artificial fixtures only. Keep actual driving
  data, routes, identifiers, videos and settings exports outside this repository.
- The original incident trace has not been identified. No reported driving failure
  is reproduced yet.

## Findings from the matching source

1. `sunnypilot/selfdrive/controls/lib/longitudinal_planner.py`,
   `update_targets` selects the lowest target across cruise, vision curves,
   map curves and speed-limit assist. Its publication includes both `vTarget`
   and `aTarget`, plus the selected source and individual curve targets.
2. `sunnypilot/selfdrive/car/intelligent_cruise_button_management/controller.py`,
   `update_calculations` consumes `LP_SP.vTarget`, rounds to displayed speed units,
   and compares it with `CS.cruiseState.speedCluster`. Its state machine requests
   increase/decrease buttons. It does not use `LP_SP.aTarget`.
3. `opendbc_repo/opendbc/sunnypilot/car/chrysler/icbm.py`, `update` translates
   those requests into Ram cruise-button CAN messages. Factory ACC determines
   the acceleration/braking response. A gentle planner acceleration request alone
   therefore does not guarantee gentle factory-ACC braking.
4. `sunnypilot/selfdrive/car/cruise_ext.py` and `selfdrive/car/cruise.py` contain
   separate software-target and stock-cluster speed paths. Their separation is
   a reason to inspect both values rather than treating one display as proof of
   accepted vehicle commands.
5. `sunnypilot/selfdrive/controls/lib/speed_limit/speed_limit_resolver.py`
   retains a last-valid limit. Current-limit validity and last-valid-limit
   validity are different signals. We have not established where the reported
   55 mph came from; map, previous set speed, initialization and resume behavior
   remain hypotheses.

## Run without the vehicle

Python 3.10+; no extra dependencies for the JSONL analyzer or its nine unit checks:

```sh
python3 -m unittest test_ram_cruise_review.py -v
python3 ram_cruise_review.py --jsonl ram_cruise_demo.jsonl --synthetic
```

The demonstration is invented. It shows a 50-to-30 mph target step, actual
deceleration and a delayed cluster response. It is not this truck's recording.
Flags are review candidates; zero flags never means a drive or controller is safe.

Optional local-log mode, from a fully configured matching sunnypilot development
environment:

```sh
python3 ram_cruise_review.py --log-file /private/path/qlog.zst
```

This adapter reads an existing local file only. It keeps selected speed fields
from carState/carControl/longitudinalPlanSP and excludes location/camera data.
The upstream LogReader dependencies are not bundled. The adapter has field-mapping
unit coverage and has been exercised against existing private qlog recordings.
Sparse qlogs may omit messages; stale input is skipped and gaps are flagged.
Estimated vehicle speed is signed, including small negative values near rest.
Negative or unset cruise-speed values are rejected rather than treated as real
speeds. A recording with controls disabled cannot diagnose active ICBM behavior.
No recordings or extracted driving traces are checked into this repository.

## Normalized trace format

One JSON object per line, strictly increasing `t` in seconds. All speed fields
are meters/second; accelerations are meters/second squared.

Required: `t`, `enabled` (boolean), `v_ego_mps`, `a_ego_mps2`,
`requested_mps`, `cluster_set_mps`, `speed_limit_valid` (boolean), `source`.

Optional: `planned_accel_mps2`, `driver_ceiling_mps`. The ceiling must come from
independent evidence of driver intent; never infer it from the software target.

Review filters: target drop at least 5 mph at a rate at least 10 mph/second;
actual deceleration below -2 m/s²; requested/cluster difference above 5 mph for
at least 3 seconds; requested speed more than 1 mph above an independently
recorded ceiling; limit-assist increase at least 5 mph without a current valid
limit. Gaps above 2 seconds break continuity. These are screening choices,
not recommended controller tuning or validated safety thresholds.

## Next engineering steps

1. Obtain an existing private incident trace if available, or use passive logging
   during ordinary manually controlled driving. Do not recreate hazardous behavior.
2. Identify the selected target source, actual stock cruise response, validity
   flags, engagement/resume buttons and any driver intervention.
3. Add a regression case only after the cause is established. Evaluate explicit
   driver speed ceilings, uncertain-data handling and earlier curve planning in
   offline replay. Do not smooth away a necessary slowdown or relax curve limits
   just to suppress braking.
4. Any future controller change requires software/hardware simulation and
   controlled-course validation. Preserve upstream driver monitoring, braking
   override and CAN actuation safeguards. Offline checks are not vehicle validation.
