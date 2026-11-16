"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import random
import time

import pytest
from pytest_mock import MockerFixture

from cereal import custom
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit import LIMIT_MAX_MAP_DATA_AGE

from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.speed_limit_resolver import SpeedLimitResolver, ALL_SOURCES
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Policy

SpeedLimitSource = custom.LongitudinalPlanSP.SpeedLimit.Source


def create_mock(properties, mocker: MockerFixture):
  mock = mocker.MagicMock()
  for _property, value in properties.items():
    setattr(mock, _property, value)
  return mock


def setup_sm_mock(mocker: MockerFixture):
  cruise_speed_limit = random.uniform(0, 120)
  live_map_data_limit = random.uniform(0, 120)

  car_state = create_mock({
    'gasPressed': False,
    'brakePressed': False,
    'standstill': False,
  }, mocker)
  car_state_sp = create_mock({
    'speedLimit': cruise_speed_limit,
  }, mocker)
  live_map_data = create_mock({
    'speedLimit': live_map_data_limit,
    'speedLimitValid': True,
    'speedLimitAhead': 0.,
    'speedLimitAheadValid': 0.,
    'speedLimitAheadDistance': 0.,
  }, mocker)
  gps_data = create_mock({
    'unixTimestampMillis': time.time() * 1e3,
  }, mocker)
  sm_mock = mocker.MagicMock()
  sm_mock.__getitem__.side_effect = lambda key: {
    'carState': car_state,
    'liveMapDataSP': live_map_data,
    'carStateSP': car_state_sp,
    'gpsLocation': gps_data,
  }[key]
  return sm_mock


parametrized_policies = pytest.mark.parametrize(
  "policy, sm_key, function_key", [
    (Policy.car_state_only, 'carStateSP', SpeedLimitSource.car),
    (Policy.car_state_priority, 'carStateSP', SpeedLimitSource.car),
    (Policy.map_data_only, 'liveMapDataSP', SpeedLimitSource.map),
    (Policy.map_data_priority, 'liveMapDataSP', SpeedLimitSource.map),
  ],
  ids=lambda val: val.name if hasattr(val, 'name') else str(val)
)


@pytest.mark.parametrize("resolver_class", [SpeedLimitResolver])
class TestSpeedLimitResolverValidation:

  @pytest.mark.parametrize("policy", list(Policy), ids=lambda policy: policy.name)
  def test_initial_state(self, resolver_class, policy):
    resolver = resolver_class()
    resolver.policy = policy
    for source in ALL_SOURCES:
      if source in resolver.limit_solutions:
        assert resolver.limit_solutions[source] == 0.
        assert resolver.distance_solutions[source] == 0.

  @parametrized_policies
  def test_resolver(self, resolver_class, policy, sm_key, function_key, mocker: MockerFixture):
    resolver = resolver_class()
    resolver.policy = policy
    sm_mock = setup_sm_mock(mocker)
    source_speed_limit = sm_mock[sm_key].speedLimit

    # Assert the resolver
    resolver.update(source_speed_limit, sm_mock)
    assert resolver.speed_limit == source_speed_limit
    assert resolver.source == ALL_SOURCES[function_key]

  def test_resolver_combined(self, resolver_class, mocker: MockerFixture):
    resolver = resolver_class()
    resolver.policy = Policy.combined
    sm_mock = setup_sm_mock(mocker)
    socket_to_source = {'carStateSP': SpeedLimitSource.car, 'liveMapDataSP': SpeedLimitSource.map}
    minimum_key, minimum_speed_limit = min(
      ((key, sm_mock[key].speedLimit) for key in
       socket_to_source.keys()), key=lambda x: x[1])

    # Assert the resolver
    resolver.update(minimum_speed_limit, sm_mock)
    assert resolver.speed_limit == minimum_speed_limit
    assert resolver.source == socket_to_source[minimum_key]

  @parametrized_policies
  def test_parser(self, resolver_class, policy, sm_key, function_key, mocker: MockerFixture):
    resolver = resolver_class()
    resolver.policy = policy
    sm_mock = setup_sm_mock(mocker)
    source_speed_limit = sm_mock[sm_key].speedLimit

    # Assert the parsing
    resolver.update(source_speed_limit, sm_mock)
    assert resolver.limit_solutions[ALL_SOURCES[function_key]] == source_speed_limit
    assert resolver.distance_solutions[ALL_SOURCES[function_key]] == 0.

  @pytest.mark.parametrize("policy", list(Policy), ids=lambda policy: policy.name)
  def test_resolve_interaction_in_update(self, resolver_class, policy, mocker: MockerFixture):
    v_ego = 50
    resolver = resolver_class()
    resolver.policy = policy

    sm_mock = setup_sm_mock(mocker)
    resolver.update(v_ego, sm_mock)

    # After resolution
    assert resolver.speed_limit is not None
    assert resolver.distance is not None
    assert resolver.source is not None

  @pytest.mark.parametrize("policy", list(Policy), ids=lambda policy: policy.name)
  def test_old_map_data_ignored(self, resolver_class, policy, mocker: MockerFixture):
    resolver = resolver_class()
    resolver.policy = policy
    sm_mock = mocker.MagicMock()
    sm_mock['gpsLocation'].unixTimestampMillis = (time.time() - 2 * LIMIT_MAX_MAP_DATA_AGE) * 1e3
    resolver._get_from_map_data(sm_mock)
    assert resolver.limit_solutions[SpeedLimitSource.map] == 0.
    assert resolver.distance_solutions[SpeedLimitSource.map] == 0.

  @pytest.mark.parametrize("age, accepted", [
    (0., True),
    (LIMIT_MAX_MAP_DATA_AGE, True),
    (LIMIT_MAX_MAP_DATA_AGE + .1, False),
    (-.008, True),
    (-1., True),
    (-1.1, False),
    (30., False),
    (1_794_854_400., False),  # zero GPS timestamp
  ])
  def test_map_fix_uses_unix_clock(self, resolver_class, age, accepted, mocker: MockerFixture):
    now = 1_794_854_400.
    mocker.patch('time.time', return_value=now)
    mocker.patch('time.monotonic', return_value=5000.)
    resolver = resolver_class()
    resolver.v_ego = 20.
    sm = setup_sm_mock(mocker)
    sm['gpsLocation'].unixTimestampMillis = int((now - age) * 1000)
    sm['liveMapDataSP'].speedLimit = 20.
    resolver._get_from_map_data(sm)
    assert resolver.limit_solutions[SpeedLimitSource.map] == (20. if accepted else 0.)

  @pytest.mark.parametrize("age, ahead_distance, expected_distance", [
    (2., 50., 10.),
    (2., 20., 0.),
    (-.008, 50., 50.),
  ])
  def test_map_distance_uses_elapsed_seconds(self, resolver_class, age, ahead_distance, expected_distance,
                                           mocker: MockerFixture):
    now = 1_794_854_400.
    mocker.patch('time.time', return_value=now)
    mocker.patch('time.monotonic', return_value=5000.)
    resolver = resolver_class()
    resolver.v_ego = 20.
    sm = setup_sm_mock(mocker)
    sm['gpsLocation'].unixTimestampMillis = int((now - age) * 1000)
    sm['liveMapDataSP'].speedLimit = 20.
    sm['liveMapDataSP'].speedLimitAhead = 10.
    sm['liveMapDataSP'].speedLimitAheadValid = True
    sm['liveMapDataSP'].speedLimitAheadDistance = ahead_distance
    resolver._get_from_map_data(sm)
    assert resolver.limit_solutions[SpeedLimitSource.map] == 10.
    assert resolver.distance_solutions[SpeedLimitSource.map] == pytest.approx(expected_distance)
