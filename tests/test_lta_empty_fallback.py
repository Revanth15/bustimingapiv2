import gzip
import importlib
import json
import os
import sys
import types
import unittest

import httpx
from fastapi import HTTPException

os.environ.setdefault("ACCOUNT_KEY", "test-account-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_API_KEY", "test-supabase-key")
os.environ.setdefault("SUPABASE_EMAIL", "test@example.com")
os.environ.setdefault("SUPABASE_PASSWORD", "test-password")

from routers import utils
from routers.busstop_cache import BusStopCache


class FakeRequest:
    headers = {}


class FakeLTAClient:
    def __init__(self):
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        request = httpx.Request("GET", url, params=params)
        raise httpx.ConnectError("connection failed", request=request)


class FakeDBResponse:
    data = [{"ok": True}]


class FakeDBTable:
    def upsert(self, *args, **kwargs):
        return self

    def execute(self):
        return FakeDBResponse()


class FakeDBClient:
    def table(self, *args, **kwargs):
        return FakeDBTable()


def install_fake_database_module():
    fake_database = types.ModuleType("routers.database")
    fake_database.getDBClient = lambda: FakeDBClient()
    sys.modules["routers.database"] = fake_database


async def noop_sleep(delay):
    return None


class QueryAPIEmptyFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_get_client = utils.get_client
        self.original_sleep = utils.asyncio.sleep
        utils.asyncio.sleep = noop_sleep

    async def asyncTearDown(self):
        utils.get_client = self.original_get_client
        utils.asyncio.sleep = self.original_sleep

    async def test_query_api_default_still_raises_after_retries(self):
        client = FakeLTAClient()
        utils.get_client = lambda: client

        with self.assertRaises(HTTPException) as ctx:
            await utils.queryAPI("ltaodataservice/Traffic-Imagesv2", {})

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(client.calls, 3)

    async def test_query_api_empty_on_error_returns_bus_arrival_shape(self):
        client = FakeLTAClient()
        utils.get_client = lambda: client

        result = await utils.queryAPI(
            "ltaodataservice/v3/BusArrival",
            {"BusStopCode": "40081"},
            empty_on_error=True,
        )

        self.assertEqual(result, {"Services": []})
        self.assertEqual(client.calls, 3)

    async def test_query_api_empty_on_error_returns_value_shape_for_other_lta_paths(self):
        client = FakeLTAClient()
        utils.get_client = lambda: client

        result = await utils.queryAPI(
            "ltaodataservice/Traffic-Imagesv2",
            {},
            empty_on_error=True,
        )

        self.assertEqual(result, {"value": []})
        self.assertEqual(client.calls, 3)

    async def test_helpers_return_empty_data_when_opted_in(self):
        calls = []
        original_query_api = utils.queryAPI

        async def fake_query_api(path, params, empty_on_error=False):
            calls.append((path, params, empty_on_error))
            return {"value": []}

        utils.queryAPI = fake_query_api
        try:
            self.assertEqual(await utils.getCarParkAvailabilityFromLTA(empty_on_error=True), [])
            self.assertEqual(await utils.getTrafficIncidentsFromLTA(empty_on_error=True), [])
            self.assertEqual(await utils.getVMSFromLTA(empty_on_error=True), [])
            self.assertEqual(
                await utils.getAllEVChargingPointsFromLTA(empty_on_error=True),
                {"evLocationsData": []},
            )
        finally:
            utils.queryAPI = original_query_api

        self.assertTrue(calls)
        self.assertTrue(all(call[2] is True for call in calls))


class RouteEmptyFallbackShapeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        install_fake_database_module()
        cls.busstop = importlib.import_module("routers.busstop")
        cls.car = importlib.import_module("routers.car")
        cls.mrt = importlib.import_module("routers.mrt")
        cls.bus = importlib.import_module("routers.bus")

    async def test_bustiming_returns_client_empty_list(self):
        calls = []

        async def fake_query_api(path, params, empty_on_error=False):
            calls.append((path, params, empty_on_error))
            return {"Services": []}

        original_query_api = self.busstop.queryAPI
        original_cache = self.busstop._cache
        self.busstop.queryAPI = fake_query_api
        self.busstop._cache = BusStopCache(ttl=8.0, maxsize=10)
        try:
            response = await self.busstop.get_bus_timing(
                FakeRequest(),
                busstopcode="40081",
                busservicenos="167",
            )
        finally:
            self.busstop.queryAPI = original_query_api
            self.busstop._cache = original_cache

        self.assertEqual(json.loads(response.body), [])
        self.assertEqual(calls[0][2], True)

    async def test_traffic_images_returns_client_empty_list(self):
        calls = []

        async def fake_query_api(path, params, empty_on_error=False):
            calls.append((path, params, empty_on_error))
            return {"value": []}

        original_query_api = self.car.queryAPI
        self.car.queryAPI = fake_query_api
        try:
            result = await self.car.get_traffic_images(FakeRequest())
        finally:
            self.car.queryAPI = original_query_api

        self.assertEqual(result, [])
        self.assertEqual(calls, [("ltaodataservice/Traffic-Imagesv2", {}, True)])

    async def test_car_park_availability_returns_client_empty_list(self):
        calls = []

        async def fake_get_car_parks(empty_on_error=False):
            calls.append(empty_on_error)
            return []

        original_get_car_parks = self.car.getCarParkAvailabilityFromLTA
        self.car.getCarParkAvailabilityFromLTA = fake_get_car_parks
        try:
            result = await self.car.get_parking_availability(FakeRequest())
        finally:
            self.car.getCarParkAvailabilityFromLTA = original_get_car_parks

        self.assertEqual(result, [])
        self.assertEqual(calls, [True])

    async def test_traffic_incidents_returns_client_empty_list(self):
        calls = []

        async def fake_get_incidents(empty_on_error=False):
            calls.append(("incidents", empty_on_error))
            return []

        async def fake_get_vms(empty_on_error=False):
            calls.append(("vms", empty_on_error))
            return []

        original_get_incidents = self.car.getTrafficIncidentsFromLTA
        original_get_vms = self.car.getVMSFromLTA
        self.car.getTrafficIncidentsFromLTA = fake_get_incidents
        self.car.getVMSFromLTA = fake_get_vms
        try:
            result = await self.car.traffic_incidents(FakeRequest())
        finally:
            self.car.getTrafficIncidentsFromLTA = original_get_incidents
            self.car.getVMSFromLTA = original_get_vms

        self.assertEqual(result, [])
        self.assertEqual(calls, [("incidents", True), ("vms", True)])

    async def test_ev_charging_returns_gzipped_client_empty_list(self):
        calls = []

        async def fake_get_ev(empty_on_error=False):
            calls.append(empty_on_error)
            return {"evLocationsData": []}

        original_get_ev = self.car.getAllEVChargingPointsFromLTA
        self.car.getAllEVChargingPointsFromLTA = fake_get_ev
        try:
            response = await self.car.ev_charging(FakeRequest())
        finally:
            self.car.getAllEVChargingPointsFromLTA = original_get_ev

        self.assertEqual(gzip.decompress(response.body), b"[]")
        self.assertEqual(response.headers["content-encoding"], "gzip")
        self.assertEqual(calls, [True])

    async def test_mrt_crowd_density_returns_existing_empty_line_shape(self):
        calls = []

        async def fake_query_api(path, params, empty_on_error=False):
            calls.append((path, params, empty_on_error))
            return {"value": []}

        original_query_api = self.mrt.queryAPI
        self.mrt.queryAPI = fake_query_api
        try:
            result = await self.mrt.get_mrt_crowd_density(
                FakeRequest(),
                mrt_lines=["NSL"],
            )
        finally:
            self.mrt.queryAPI = original_query_api

        self.assertEqual(
            result["lines"],
            {"NSL": {"StartTime": "", "EndTime": "", "Stations": []}},
        )
        self.assertIn("processing_time_seconds", result)
        self.assertEqual(
            calls,
            [("ltaodataservice/PCDRealTime", {"TrainLine": "NSL"}, True)],
        )

    async def test_extract_bus_routes_keeps_default_lta_failure_behavior(self):
        calls = []

        async def fake_get_bus_routes(empty_on_error=False):
            calls.append(empty_on_error)
            return []

        original_get_bus_routes = self.bus.getBusRoutesFromLTA
        self.bus.getBusRoutesFromLTA = fake_get_bus_routes
        try:
            await self.bus.extract_bus_routes_raw_data(FakeRequest())
        finally:
            self.bus.getBusRoutesFromLTA = original_get_bus_routes

        self.assertEqual(calls, [False])
