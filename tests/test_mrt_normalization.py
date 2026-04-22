import importlib
import sys
import types
import unittest


class _DummyDBClient:
    def table(self, *_args, **_kwargs):
        raise AssertionError("Database access is not expected in normalization helper tests")


async def _dummy_query_api(*_args, **_kwargs):
    raise AssertionError("LTA API access is not expected in normalization helper tests")


database_stub = types.ModuleType("routers.database")
database_stub.getDBClient = lambda: _DummyDBClient()

utils_stub = types.ModuleType("routers.utils")
utils_stub.queryAPI = _dummy_query_api

sys.modules["routers.database"] = database_stub
sys.modules["routers.utils"] = utils_stub
sys.modules.pop("routers.mrt", None)

mrt = importlib.import_module("routers.mrt")


class TestMRTNormalizationHelpers(unittest.TestCase):
    def test_split_station_codes_handles_single_and_interchange(self):
        self.assertEqual(mrt._split_station_codes("NS10"), ["NS10"])
        self.assertEqual(mrt._split_station_codes("EW16-NE3-TE17"), ["EW16", "NE3", "TE17"])

    def test_normalize_network_handles_mrt_lrt_and_hybrid(self):
        self.assertEqual(mrt._normalize_network("singapore-mrt"), ["mrt"])
        self.assertEqual(mrt._normalize_network("singapore-lrt"), ["lrt"])
        self.assertEqual(mrt._normalize_network("singapore-lrt.singapore-mrt"), ["mrt", "lrt"])

    def test_normalize_color_maps_known_tokens_and_rejects_unknown(self):
        self.assertEqual(mrt._normalize_color("orangered"), "#FF4500")
        self.assertEqual(mrt._normalize_color("brown"), "#A52A2A")

        with self.assertRaisesRegex(ValueError, "Unknown rail color token"):
            mrt._normalize_color("chartreuse")

    def test_to_lat_lng_pair_swaps_and_rounds(self):
        self.assertEqual(mrt._to_lat_lng_pair([103.123456789, 1.987654321]), [1.987654, 103.123457])

    def test_normalize_line_geometry_converts_linestring_and_multilinestring(self):
        line_string = {
            "type": "LineString",
            "coordinates": [[103.8, 1.3], [103.81, 1.31]],
        }
        multi_line_string = {
            "type": "MultiLineString",
            "coordinates": [
                [[103.8, 1.3], [103.81, 1.31]],
                [[103.82, 1.32], [103.83, 1.33]],
            ],
        }

        self.assertEqual(
            mrt._normalize_line_geometry(line_string),
            [[[1.3, 103.8], [1.31, 103.81]]],
        )
        self.assertEqual(
            mrt._normalize_line_geometry(multi_line_string),
            [
                [[1.3, 103.8], [1.31, 103.81]],
                [[1.32, 103.82], [1.33, 103.83]],
            ],
        )

    def test_build_lines_payload_normalizes_color_and_paths(self):
        features = [
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[103.8, 1.3], [103.81, 1.31]],
                },
                "properties": {
                    "name": "North South Line",
                    "network": "singapore-mrt",
                    "line_color": "orangered",
                },
            },
            {
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [
                        [[103.7, 1.2], [103.71, 1.21]],
                        [[103.72, 1.22], [103.73, 1.23]],
                    ],
                },
                "properties": {
                    "name": "Bukit Panjang LRT",
                    "network": "singapore-lrt",
                    "line_color": "gray",
                },
            },
        ]

        payload = mrt._build_lines_payload(features)

        self.assertEqual(len(payload["lines"]), 2)
        self.assertEqual(payload["lines"][0]["id"], "bukit-panjang-lrt")
        self.assertEqual(payload["lines"][0]["network"], "lrt")
        self.assertEqual(payload["lines"][0]["color_hex"], "#808080")
        self.assertEqual(payload["lines"][1]["id"], "north-south-line")
        self.assertEqual(payload["lines"][1]["network"], "mrt")
        self.assertEqual(payload["lines"][1]["color_hex"], "#FF4500")

    def test_build_stations_payload_groups_multiple_polygons_for_same_station(self):
        station_features = [
            {
                "geometry": {"type": "Point", "coordinates": [103.7424, 1.3331]},
                "properties": {
                    "name": "Jurong East",
                    "station_codes": "NS1-EW24",
                    "stop_type": "station",
                    "network": "singapore-mrt",
                    "station_colors": "red-green",
                },
            },
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[103.742456, 1.333123], [103.74249, 1.3331], [103.74243, 1.33308]]],
                },
                "properties": {"station_codes": "NS1-EW24"},
            },
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[103.7427, 1.3329], [103.74274, 1.33286], [103.74268, 1.33282]]],
                },
                "properties": {"station_codes": "NS1-EW24"},
            },
        ]

        station_index = mrt._build_station_index(station_features)
        payload = mrt._build_stations_payload(station_features, station_index)

        self.assertEqual(len(payload["stations"]), 1)
        station = payload["stations"][0]
        self.assertEqual(station["id"], "ns1-ew24")
        self.assertEqual(station["primary_station_code"], "NS1")
        self.assertEqual(station["station_codes"], ["NS1", "EW24"])
        self.assertEqual(station["networks"], ["mrt"])
        self.assertEqual(station["line_colors_hex"], ["#FF0000", "#008000"])
        self.assertEqual(len(station["polygons"]), 2)

    def test_build_exits_payload_joins_station_metadata_and_dedupes(self):
        features = [
            {
                "geometry": {"type": "Point", "coordinates": [103.7424, 1.3331]},
                "properties": {
                    "name": "Jurong East",
                    "station_codes": "NS1-EW24",
                    "stop_type": "station",
                    "network": "singapore-mrt",
                    "station_colors": "red-green",
                },
            },
            {
                "geometry": {"type": "Point", "coordinates": [103.7424564, 1.3331234]},
                "properties": {"name": "A", "station_codes": "NS1-EW24", "stop_type": "entrance"},
            },
            {
                "geometry": {"type": "Point", "coordinates": [103.74245649, 1.33312349]},
                "properties": {"name": "a", "station_codes": "NS1-EW24", "stop_type": "entrance"},
            },
            {
                "geometry": {"type": "Point", "coordinates": [103.7425, 1.33315]},
                "properties": {"name": "B", "station_codes": "NS1-EW24", "stop_type": "entrance"},
            },
        ]

        station_index = mrt._build_station_index(features)
        payload = mrt._build_exits_payload(features, station_index)

        self.assertEqual(len(payload["exits"]), 2)
        first_exit = payload["exits"][0]
        self.assertEqual(first_exit["id"], "ns1-ew24-exit-a")
        self.assertEqual(first_exit["station_id"], "ns1-ew24")
        self.assertEqual(first_exit["station_name"], "Jurong East")
        self.assertEqual(first_exit["station_codes"], ["NS1", "EW24"])
        self.assertEqual(first_exit["exit_code"], "A")
        self.assertEqual(first_exit["latitude"], 1.333123)
        self.assertEqual(first_exit["longitude"], 103.742456)


if __name__ == "__main__":
    unittest.main()
