"""Integration of real serialized message schemas with isolated resolver methods.

Uses synthetic inputs. Requires pycapnp==2.1.0 and matching local cereal schemas.
Does not load messaging, native Params, or the full driving stack.
"""
import unittest
from cereal import log
from test_ram_map_clock import resolver_methods, EPOCH_NOW


def decoded_messages(age, distance=50):
  gps = log.Event.new_message(logMonoTime=5_000_000_000_000, valid=True)
  gps.init('gpsLocationExternal')
  gps.gpsLocationExternal.unixTimestampMillis = int((EPOCH_NOW-age)*1000)
  gps.gpsLocationExternal.hasFix = True
  map_event = log.Event.new_message(logMonoTime=5_000_000_000_000, valid=True)
  map_event.init('liveMapDataSP')
  for field, value in dict(speedLimit=20., speedLimitValid=True, speedLimitAhead=10.,
                           speedLimitAheadValid=True, speedLimitAheadDistance=float(distance)).items():
    setattr(map_event.liveMapDataSP, field, value)
  data = gps.to_bytes()+map_event.to_bytes()
  parsed = list(log.Event.read_multiple_bytes(data))
  return {'gpsLocation': parsed[0].gpsLocationExternal, 'liveMapDataSP': parsed[1].liveMapDataSP}


class ClockSchemaTests(unittest.TestCase):
  def test_unix_timestamp_round_trip(self):
    sm = decoded_messages(2)
    self.assertEqual(sm['gpsLocation'].unixTimestampMillis, int((EPOCH_NOW-2)*1000))
    self.assertTrue(sm['gpsLocation'].hasFix)

  def test_decoded_fresh_fix_updates_upcoming_distance(self):
    resolver = resolver_methods(baseline=False)
    resolver._process_map_data(decoded_messages(2))
    self.assertEqual(resolver.limit_solutions[2], 10.)
    self.assertAlmostEqual(resolver.distance_solutions[2], 10.)

  def test_decoded_stale_fix_is_rejected(self):
    resolver = resolver_methods(baseline=False)
    resolver._process_map_data(decoded_messages(30))
    self.assertEqual(resolver.limit_solutions[2], 0.)

  def test_decoded_small_future_skew_is_accepted(self):
    resolver = resolver_methods(baseline=False)
    resolver._process_map_data(decoded_messages(-.008))
    self.assertEqual(resolver.limit_solutions[2], 10.)
    self.assertAlmostEqual(resolver.distance_solutions[2], 50.)

  def test_baseline_demonstrates_original_clock_problem(self):
    resolver = resolver_methods(baseline=True)
    resolver._process_map_data(decoded_messages(30))
    self.assertEqual(resolver.limit_solutions[2], 20.)


if __name__ == '__main__':
  unittest.main()
