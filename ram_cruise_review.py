#!/usr/bin/env python3
"""Offline speed-trace review. No vehicle connection, control, or parameter writes.

Review thresholds identify candidates for inspection, never safe driving limits.
See RAM_CRUISE_REVIEW.md. Standard-library JSONL mode needs Python 3.10+.
"""
import argparse
import json
import math
from pathlib import Path

MPH = 0.44704
REQUIRED = ('t', 'v_ego_mps', 'a_ego_mps2', 'requested_mps', 'cluster_set_mps')
OPTIONAL_NUMERIC = ('driver_ceiling_mps', 'planned_accel_mps2')


def validate(sample, previous_t=None):
  if not isinstance(sample, dict):
    raise ValueError('Each sample must be a JSON object')
  for key in (*REQUIRED, *OPTIONAL_NUMERIC):
    value = sample.get(key)
    if value is None and key in OPTIONAL_NUMERIC:
      continue
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
      raise ValueError(f'{key} must be a finite number')
    if key.endswith('_mps') and not 0 <= value <= 80:
      raise ValueError(f'{key} is outside the accepted input range; check units/sentinels')
  if sample['t'] < 0 or (previous_t is not None and sample['t'] <= previous_t):
    raise ValueError('Sample times must be nonnegative and strictly increasing')
  for key in ('enabled', 'speed_limit_valid'):
    if type(sample.get(key)) is not bool:
      raise ValueError(f'{key} must be a boolean')
  if not isinstance(sample.get('source'), str):
    raise ValueError('source must be a string')
  return sample


def analyze(samples):
  findings, previous, gap_since, held = [], None, None, set()
  count = 0
  ceilings = 0

  def flag(code, sample, details):
    findings.append({'time_s': round(sample['t'], 3), 'code': code,
                     'source': sample['source'], 'details': details})

  for sample in samples:
    validate(sample, previous['t'] if previous else None)
    count += 1
    ceilings += sample.get('driver_ceiling_mps') is not None
    dt = sample['t'] - previous['t'] if previous else None
    continuous = previous is not None and dt <= 2
    if previous is not None and not continuous:
      flag('data_gap', sample, {'gap_s': round(dt, 3)})
      gap_since, held = None, set()
    now_held = set()
    if sample['enabled']:
      if sample['a_ego_mps2'] < -2:
        now_held.add('rapid_deceleration')
        if 'rapid_deceleration' not in held:
          flag('rapid_deceleration', sample, {'a_ego_mps2': sample['a_ego_mps2']})
      ceiling = sample.get('driver_ceiling_mps')
      if ceiling is not None and sample['requested_mps'] > ceiling + MPH:
        now_held.add('target_above_driver_ceiling')
        if 'target_above_driver_ceiling' not in held:
          flag('target_above_driver_ceiling', sample,
               {'requested_mph': round(sample['requested_mps'] / MPH, 2),
                'driver_ceiling_mph': round(ceiling / MPH, 2)})
      if continuous and previous['enabled']:
        change = sample['requested_mps'] - previous['requested_mps']
        if change <= -5 * MPH and change / dt <= -10 * MPH:
          flag('abrupt_target_drop', sample, {'change_mph': round(change / MPH, 2), 'interval_s': round(dt, 3)})
        if change >= 5 * MPH and not sample['speed_limit_valid'] and sample['source'] == 'speedLimitAssist':
          flag('limit_assist_increase_without_current_limit', sample, {'change_mph': round(change / MPH, 2)})
      if not previous or not previous['enabled'] or not continuous:
        if sample['requested_mps'] > sample['v_ego_mps'] + 5 * MPH:
          flag('engagement_target_above_vehicle_speed', sample,
               {'difference_mph': round((sample['requested_mps'] - sample['v_ego_mps']) / MPH, 2)})
      if abs(sample['requested_mps'] - sample['cluster_set_mps']) > 5 * MPH:
        if gap_since is None:
          gap_since = sample['t']
        if sample['t'] - gap_since >= 3:
          now_held.add('sustained_requested_cluster_gap')
          if 'sustained_requested_cluster_gap' not in held:
            flag('sustained_requested_cluster_gap', sample,
                 {'duration_s': round(sample['t'] - gap_since, 3),
                  'difference_mph': round((sample['requested_mps'] - sample['cluster_set_mps']) / MPH, 2)})
      else:
        gap_since = None
    else:
      gap_since = None
    held, previous = now_held, sample
  return {'status': 'offline_review_only', 'samples': count, 'driver_ceiling_samples': ceilings,
          'interpretation': 'Flags are review candidates, not diagnoses. No flags is not evidence of safe operation.',
          'findings': findings}


def plan_sample(t, cs, cc, plan):
  """Map selected logged fields; do not infer a driver ceiling from a software target."""
  resolver = plan.get('speedLimit', {}).get('resolver', {})
  return {'t': t, 'enabled': cc['enabled'], 'v_ego_mps': cs['vEgo'],
          'a_ego_mps2': cs['aEgo'], 'requested_mps': plan['vTarget'],
          'cluster_set_mps': cs['cruiseState']['speedCluster'],
          'planned_accel_mps2': plan.get('aTarget'),
          'speed_limit_valid': resolver.get('speedLimitValid', False),
          'source': str(plan['longitudinalPlanSource'])}


def local_log_samples(filename):
  """Optional upstream adapter. Reads only an existing local qlog/rlog file."""
  path = Path(filename).resolve()
  if not path.is_file():
    raise ValueError('Provide an existing local qlog/rlog file; remote routes are not accepted')
  try:
    from openpilot.tools.lib.logreader import LogReader
  except ImportError as exc:
    raise ValueError('Local-log mode requires the matching sunnypilot development environment') from exc
  latest, times, origin, last_t = {}, {}, None, None
  for event in LogReader(str(path), sort_by_time=True):
    kind = event.which()
    if kind not in ('carState', 'carControl', 'longitudinalPlanSP') or not event.valid:
      continue
    clock = event.logMonoTime * 1e-9
    latest[kind], times[kind] = getattr(event, kind).to_dict(), clock
    if kind != 'longitudinalPlanSP' or not all(k in latest for k in ('carState', 'carControl')):
      continue
    if any(clock - times[k] > 0.5 for k in ('carState', 'carControl')):
      continue
    origin = clock if origin is None else origin
    t = clock - origin
    if last_t is not None and t <= last_t:
      continue
    yield plan_sample(t, latest['carState'], latest['carControl'], latest[kind])
    last_t = t


def jsonl_samples(filename):
  with open(filename, encoding='utf-8') as stream:
    for lineno, line in enumerate(stream, 1):
      if not line.strip():
        continue
      try:
        yield json.loads(line)
      except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON on line {lineno}') from exc


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  group = parser.add_mutually_exclusive_group(required=True)
  group.add_argument('--jsonl', help='Normalized trace, SI units')
  group.add_argument('--log-file', help='Existing local qlog/rlog; requires upstream development dependencies')
  parser.add_argument('--synthetic', action='store_true', help='Label artificial input explicitly')
  args = parser.parse_args()
  try:
    report = analyze(jsonl_samples(args.jsonl) if args.jsonl else local_log_samples(args.log_file))
    report['input_kind'] = 'synthetic' if args.synthetic else 'user_supplied_unverified'
    if not report['samples']:
      raise ValueError('No usable samples; a sparse qlog may omit the required messages')
  except (ValueError, KeyError, OSError) as exc:
    parser.exit(2, f'Cannot review trace: {exc}\n')
  print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
  main()
