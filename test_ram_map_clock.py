"""Isolated tests of the real resolver methods, without vehicle/runtime imports.

Loads the two production method ASTs unchanged. Injected inputs are a clock,
GPS/map messages, and source constants. This is not full-stack or road validation.
Set RAM_RESOLVER_BASELINE=1 to run against the exact installed source via git show.
"""
import ast
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent
PATH = 'sunnypilot/selfdrive/controls/lib/speed_limit/speed_limit_resolver.py'
BASELINE = '6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2'
EPOCH_NOW = 1_794_854_400.0
MAX_AGE = 10.0


def resolver_methods():
  source = subprocess.check_output(['git', 'show', f'{BASELINE}:{PATH}'], cwd=ROOT, text=True) \
    if os.getenv('RAM_RESOLVER_BASELINE') == '1' else (ROOT / PATH).read_text()
  cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'SpeedLimitResolver')
  methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and
             n.name in ('_process_map_data', '_calculate_map_data_limits')]
  assert len(methods) == 2
  module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
                           ast.ClassDef(name='ResolverUnderTest', bases=[], keywords=[], body=methods, decorator_list=[])],
                      type_ignores=[])
  namespace = {'time': SimpleNamespace(time=lambda: EPOCH_NOW, monotonic=lambda: 5000.0),
               'LIMIT_MAX_MAP_DATA_AGE': MAX_AGE, 'LIMIT_ADAPT_ACC': -1.,
               'SpeedLimitSource': SimpleNamespace(map=2)}
  exec(compile(ast.fix_missing_locations(module), PATH, 'exec'), namespace)
  obj = namespace['ResolverUnderTest']()
  obj._gps_location_service = 'gpsLocation'
  obj.v_ego = 20.0
  obj.limit_solutions = {2: 0.0}
  obj.distance_solutions = {2: 0.0}
  return obj


def messages(age_s, ahead_distance=50.):
  return {'gpsLocation': SimpleNamespace(unixTimestampMillis=int((EPOCH_NOW-age_s)*1000)),
          'liveMapDataSP': SimpleNamespace(speedLimit=20., speedLimitValid=True,
            speedLimitAhead=10., speedLimitAheadValid=True, speedLimitAheadDistance=ahead_distance)}


class MapClockTests(unittest.TestCase):
  def test_fresh_gps_accepts_map_limit(self):
    resolver = resolver_methods()
    resolver._process_map_data(messages(0, ahead_distance=1000))
    self.assertEqual(resolver.limit_solutions[2], 20.)

  def test_stale_gps_rejects_map_limit(self):
    resolver = resolver_methods()
    resolver._process_map_data(messages(30))
    self.assertEqual(resolver.limit_solutions[2], 0.)

  def test_future_gps_rejects_map_limit(self):
    resolver = resolver_methods()
    resolver._process_map_data(messages(-30))
    self.assertEqual(resolver.limit_solutions[2], 0.)

  def test_zero_timestamp_rejects_map_limit(self):
    resolver = resolver_methods()
    sm = messages(0)
    sm['gpsLocation'].unixTimestampMillis = 0
    resolver._process_map_data(sm)
    self.assertEqual(resolver.limit_solutions[2], 0.)

  def test_age_limit_is_inclusive(self):
    resolver = resolver_methods()
    resolver._process_map_data(messages(MAX_AGE, ahead_distance=1000))
    self.assertEqual(resolver.limit_solutions[2], 20.)

  def test_just_past_age_limit_is_rejected(self):
    resolver = resolver_methods()
    resolver._process_map_data(messages(MAX_AGE+.1))
    self.assertEqual(resolver.limit_solutions[2], 0.)

  def test_distance_since_fix_uses_elapsed_seconds(self):
    resolver = resolver_methods()
    # Fix age 2 s at 20 m/s: 40 m travelled, leaving 10 m of a 50 m distance.
    resolver._process_map_data(messages(2))
    self.assertEqual(resolver.limit_solutions[2], 10.)
    self.assertAlmostEqual(resolver.distance_solutions[2], 10.)

  def test_passed_waypoint_does_not_produce_negative_distance(self):
    resolver = resolver_methods()
    resolver._process_map_data(messages(2, ahead_distance=20))
    self.assertEqual(resolver.limit_solutions[2], 10.)
    self.assertEqual(resolver.distance_solutions[2], 0.)


if __name__ == '__main__':
  unittest.main()
