import importlib
import json
import os
import sys
import types
import unittest

os.environ.setdefault("ACCOUNT_KEY", "test-account-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_API_KEY", "test-supabase-key")
os.environ.setdefault("SUPABASE_EMAIL", "test@example.com")
os.environ.setdefault("SUPABASE_PASSWORD", "test-password")

from fastapi import HTTPException

from routers import nus_nextbus


class FakeRequest:
    headers = {}


class FakeDBResponse:
    def __init__(self, data=None, count=None):
        self.data = data if data is not None else []
        self.count = count


class FakeDBTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.filters = {}
        self.pending_upsert = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def upsert(self, data, *args, **kwargs):
        self.pending_upsert = data
        self.client.upserts.setdefault(self.name, []).append((data, kwargs))
        return self

    def execute(self):
        if self.pending_upsert is not None:
            if self.name == "jsons":
                for row in self.pending_upsert:
                    self.client.jsons[row["id"]] = row["json_value"]
            return FakeDBResponse(self.pending_upsert)

        if self.name == "jsons":
            row_id = self.filters.get("id")
            if row_id in self.client.jsons:
                return FakeDBResponse([{"json_value": self.client.jsons[row_id]}])
        return FakeDBResponse([])


class FakeDBClient:
    def __init__(self):
        self.upserts = {}
        self.jsons = {
            nus_nextbus.BUS_STOP_AVAILABLE_SERVICES_KEY: json.dumps(
                {"40081": ["167"]}
            )
        }

    def table(self, name):
        return FakeDBTable(self, name)


class FakeBlobCache:
    def __init__(self):
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)
        return True


def install_fake_database_module():
    fake_database = types.ModuleType("routers.database")
    fake_database.getDBClient = lambda: FakeDBClient()
    sys.modules["routers.database"] = fake_database


def sample_static_data():
    return {
        "stops": [
            {
                "caption": "COM 3",
                "name": "COM3",
                "LongName": "COM 3",
                "ShortName": "COM 3",
                "latitude": 1.294431,
                "longitude": 103.775217,
            },
            {
                "caption": "Kent Ridge MRT",
                "name": "KR-MRT",
                "LongName": "Kent Ridge MRT",
                "ShortName": "KR MRT",
                "latitude": 1.29482,
                "longitude": 103.784413,
            },
        ],
        "routes": {
            "D1": [
                {"seq": 1, "stop_name": "COM 3", "busstopcode": "COM3"},
                {"seq": 2, "stop_name": "Kent Ridge MRT", "busstopcode": "KR-MRT"},
            ],
            "D2": [
                {"seq": 1, "stop_name": "Kent Ridge MRT", "busstopcode": "KR-MRT"},
                {"seq": 2, "stop_name": "COM 3", "busstopcode": "COM3"},
            ],
        },
    }


class NusNextBusHelperTests(unittest.TestCase):
    def test_parse_nus_timing_html_uses_existing_response_shape_and_ignores_public_bus(self):
        html = """
        <table>
          <tr><th>Route</th><th>Arrival</th><th>Next Arrival</th></tr>
          <tr><td>D1</td><td>5 <span>mins</span></td><td>- <span>mins</span></td></tr>
          <tr><td>D2</td><td>- <span>mins</span></td><td>12 <span>mins</span></td></tr>
          <tr><td>95</td><td>3 <span>mins</span></td><td>- <span>mins</span></td></tr>
        </table>
        """

        result = nus_nextbus.parse_nus_timing_html(html, {"D1", "D2"})

        self.assertEqual([row["serviceNo"] for row in result], ["D1", "D2"])
        self.assertEqual(result[0]["serviceDetails"][0]["busArrivalTime"], 5)
        self.assertEqual(result[0]["serviceDetails"][0]["busMonitored"], 1)
        self.assertEqual(result[0]["serviceDetails"][1]["busArrivalTime"], -100)
        self.assertEqual(result[0]["serviceDetails"][2]["busArrivalTime"], -100)
        self.assertEqual(result[1]["serviceDetails"][1]["busArrivalTime"], 12)

    def test_static_data_formats_into_current_database_shapes(self):
        static_data = sample_static_data()
        timestamp = "2026-06-01T12:00:00+08:00"

        stops = nus_nextbus.format_nus_bus_stops(static_data, timestamp)
        routes = nus_nextbus.format_nus_bus_routes(static_data, timestamp)
        raw_routes = nus_nextbus.format_nus_bus_route_raw(static_data, timestamp)
        lookup = nus_nextbus.build_nus_stop_services_lookup(static_data)

        self.assertEqual(stops[0]["id"], "COM3")
        self.assertEqual(stops[0]["road_name"], "NUS")
        self.assertEqual(stops[0]["bus_services"], "D1,D2")
        self.assertEqual(json.loads(routes[0]["json_value"])["serviceNo"], "D1")
        self.assertEqual(
            json.loads(routes[0]["json_value"])["routes"][0]["busStopIDs"],
            ["COM3", "KR-MRT"],
        )
        self.assertEqual(json.loads(raw_routes[0]["json_value"])["services"]["D1"]["operator"], "NUS")
        self.assertEqual(lookup["COM3"], ["D1", "D2"])

    def test_merge_stop_services_preserves_lta_and_adds_nus(self):
        merged = nus_nextbus.merge_bus_stop_available_services(
            {"40081": ["167"], "COM3": ["D1"]},
            {"COM3": ["D2"], "KR-MRT": ["D1"]},
        )

        self.assertEqual(merged["40081"], ["167"])
        self.assertEqual(merged["COM3"], ["D1", "D2"])
        self.assertEqual(merged["KR-MRT"], ["D1"])


class NusNextBusRouteTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        install_fake_database_module()
        cls.busstop = importlib.import_module("routers.busstop")
        cls.bus = importlib.import_module("routers.bus")

    async def test_bustiming_uses_nus_branch_for_nus_stop_codes(self):
        calls = []

        async def fake_is_nus_stop_code(stop_code, db_client=None):
            calls.append(("is_nus", stop_code))
            return True

        async def fake_fetch_nus_timings(stop_code, requested_services, process_all, db_client=None):
            calls.append(("fetch_nus", stop_code, requested_services, process_all))
            return [
                {
                    "serviceNo": "D1",
                    "serviceDetails": [
                        {
                            "busArrivalTime": 4,
                            "busLoad": "-",
                            "busFeature": "-",
                            "busType": "-",
                            "busMonitored": 1,
                            "busLongitude": "-",
                            "busLatitude": "-",
                        },
                        nus_nextbus.DEFAULT_BUS.copy(),
                        nus_nextbus.DEFAULT_BUS.copy(),
                    ],
                }
            ]

        async def fake_query_api(*args, **kwargs):
            raise AssertionError("LTA should not be called for NUS stop codes")

        original_is_nus = self.busstop.is_nus_stop_code
        original_fetch = self.busstop.fetch_nus_timings
        original_query = self.busstop.queryAPI
        self.busstop.is_nus_stop_code = fake_is_nus_stop_code
        self.busstop.fetch_nus_timings = fake_fetch_nus_timings
        self.busstop.queryAPI = fake_query_api
        try:
            response = await self.busstop.get_bus_timing(
                FakeRequest(),
                busstopcode="COM3",
                busservicenos="D1",
            )
        finally:
            self.busstop.is_nus_stop_code = original_is_nus
            self.busstop.fetch_nus_timings = original_fetch
            self.busstop.queryAPI = original_query

        self.assertEqual(json.loads(response.body)[0]["serviceNo"], "D1")
        self.assertEqual(calls[0], ("is_nus", "COM3"))
        self.assertEqual(calls[1], ("fetch_nus", "COM3", {"D1"}, False))

    async def test_bustiming_rejects_unknown_non_lta_stop_code(self):
        async def fake_is_nus_stop_code(stop_code, db_client=None):
            return False

        original_is_nus = self.busstop.is_nus_stop_code
        self.busstop.is_nus_stop_code = fake_is_nus_stop_code
        try:
            with self.assertRaises(HTTPException) as ctx:
                await self.busstop.get_bus_timing(
                    FakeRequest(),
                    busstopcode="NOTREAL",
                    busservicenos="D1",
                )
        finally:
            self.busstop.is_nus_stop_code = original_is_nus

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_extract_nus_bus_data_upserts_all_expected_tables(self):
        fake_db = FakeDBClient()
        fake_cache = FakeBlobCache()

        async def fake_fetch_nus_static_data():
            return sample_static_data()

        original_db = self.bus.dbClient
        original_cache = self.bus.blob_cache
        original_fetch = self.bus.fetch_nus_static_data
        self.bus.dbClient = fake_db
        self.bus.blob_cache = fake_cache
        self.bus.fetch_nus_static_data = fake_fetch_nus_static_data
        try:
            result = await self.bus.extract_nus_bus_data(FakeRequest())
        finally:
            self.bus.dbClient = original_db
            self.bus.blob_cache = original_cache
            self.bus.fetch_nus_static_data = original_fetch

        self.assertEqual(result["stops"], 2)
        self.assertEqual(result["routes"], 2)
        self.assertIn("bus_stops", fake_db.upserts)
        self.assertIn("bus_route", fake_db.upserts)
        self.assertIn("bus_route_raw", fake_db.upserts)
        self.assertIn("jsons", fake_db.upserts)
        merged_services = json.loads(fake_db.jsons[nus_nextbus.BUS_STOP_AVAILABLE_SERVICES_KEY])
        self.assertEqual(merged_services["40081"], ["167"])
        self.assertEqual(merged_services["COM3"], ["D1", "D2"])
        self.assertEqual(
            fake_cache.deleted,
            ["/getallbusstops", "/getBusRoutesData", "/bus-routes/stops"],
        )
