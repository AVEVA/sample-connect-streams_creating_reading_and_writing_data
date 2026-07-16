"""
End-to-end tests for Program.py.

All HTTP calls are intercepted with unittest.mock so no real network traffic
or credentials are needed.  The tests exercise the full call sequence from
token acquisition through data writes and reads.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import Program as prog

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FAKE_TOKEN = "test-access-token"
SDS_URL = "https://platform.connect.aveva.com/api/account/acct-id/sds/dev-store/v2"

RUNTIME_SETTINGS = {
    "well_known_url": "https://identity.example.com/.well-known/openid-configuration",
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "sds_url": SDS_URL,
}

STREAM_1_ID = "Random_1"
STREAM_2_ID = "Random_2"

# Minimal SDS definitions that load_settings() will return for each JSON file
SDS_TYPE_DEF = {"id": "TimeIndexed.Double"}
SDS_STREAM_1_DEF = {"id": STREAM_1_ID}
SDS_STREAM_2_DEF = {"id": STREAM_2_ID}

# Two fake time-series data points used as server responses
FAKE_POINTS = [
    {"Timestamp": "2026-06-01T00:00:00Z", "Value": 0.1},
    {"Timestamp": "2026-06-01T01:00:00Z", "Value": 0.2},
]


def _ok_response(body):
    """Return a MagicMock that looks like a successful requests.Response."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = body
    r.raise_for_status.return_value = None
    return r


# ---------------------------------------------------------------------------
# Unit tests – pure functions (no HTTP)
# ---------------------------------------------------------------------------


class TestCalculateIntervalCount:
    def test_one_hour_intervals_over_24_hours(self):
        count = prog.calculate_interval_count(
            "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", "01:00:00"
        )
        assert count == 25  # 24 intervals + 1 inclusive endpoint

    def test_same_start_and_end(self):
        count = prog.calculate_interval_count(
            "2026-06-01T00:00:00Z", "2026-06-01T00:00:00Z", "01:00:00"
        )
        assert count == 1

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError, match="start must be less than or equal to end"):
            prog.calculate_interval_count(
                "2026-06-02T00:00:00Z", "2026-06-01T00:00:00Z", "01:00:00"
            )


class TestBuildTimeseriesData:
    def test_generates_correct_point_count(self):
        data = prog.build_timeseries_data(
            "2026-06-01T00:00:00Z", "2026-06-01T02:00:00Z", "01:00:00"
        )
        # start, +1h, +2h  →  3 points
        assert len(data) == 3

    def test_points_have_required_keys(self):
        data = prog.build_timeseries_data(
            "2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "01:00:00"
        )
        for point in data:
            assert "Timestamp" in point
            assert "Value" in point

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            prog.build_timeseries_data(
                "2026-06-02T00:00:00Z", "2026-06-01T00:00:00Z", "01:00:00"
            )


class TestSettingsLoading:
    def _write_json(self, tmp_path: Path, name: str, data) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_load_settings_missing_file_exits(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            prog.load_settings(tmp_path / "missing.json")
        assert "Settings file not found" in capsys.readouterr().err

    def test_load_settings_invalid_json_exits(self, tmp_path, capsys):
        settings_path = tmp_path / "bad.json"
        settings_path.write_text("{this is not valid json", encoding="utf-8")

        with pytest.raises(SystemExit):
            prog.load_settings(settings_path)
        assert "not valid JSON" in capsys.readouterr().err

    def test_load_settings_root_must_be_object(self, tmp_path, capsys):
        settings_path = self._write_json(tmp_path, "settings.json", [1, 2, 3])

        with pytest.raises(SystemExit):
            prog.load_settings(settings_path)
        assert "root must be a JSON object" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "override, expected_message",
        [
            ({"well_known_url": ""}, "Set well_known_url"),
            ({"client_id": ""}, "Set client_id and client_secret"),
            ({"client_secret": ""}, "Set client_id and client_secret"),
            ({"account_id": ""}, "Set account_id and data_store_id"),
            ({"data_store_id": ""}, "Set account_id and data_store_id"),
            ({"base_url": ""}, "Set base_url"),
        ],
    )
    def test_load_runtime_settings_required_fields(self, tmp_path, override, expected_message, capsys):
        settings = {
            "well_known_url": "https://identity.example.com/.well-known/openid-configuration",
            "client_id": "cid",
            "client_secret": "secret",
            "account_id": "acct-id",
            "data_store_id": "store-id",
            "base_url": "https://platform.connect.aveva.com",
        }
        settings.update(override)
        settings_path = self._write_json(tmp_path, "appsettings.json", settings)

        with pytest.raises(SystemExit):
            prog.load_runtime_settings(settings_path)
        assert expected_message in capsys.readouterr().err

    def test_load_runtime_settings_builds_sds_url(self, tmp_path):
        settings = {
            "well_known_url": "https://identity.example.com/.well-known/openid-configuration",
            "client_id": "cid",
            "client_secret": "secret",
            "account_id": "acct-id",
            "data_store_id": "store-id",
            "base_url": "https://platform.connect.aveva.com",
        }
        settings_path = self._write_json(tmp_path, "appsettings.json", settings)

        runtime = prog.load_runtime_settings(settings_path)

        assert runtime["sds_url"] == "https://platform.connect.aveva.com/api/account/acct-id/sds/store-id/v2"


# ---------------------------------------------------------------------------
# Unit tests – HTTP helpers
# ---------------------------------------------------------------------------


class TestGetAccessToken:
    def test_happy_path_returns_token(self):
        discovery = {"token_endpoint": "https://identity.example.com/token"}
        token_resp = {"access_token": FAKE_TOKEN}

        with patch("requests.get", return_value=_ok_response(discovery)), \
             patch("requests.post", return_value=_ok_response(token_resp)):
            result = prog.get_access_token(
                well_known_url="https://identity.example.com/.well-known/openid-configuration",
                client_id="cid",
                client_secret="secret",
                scope="api",
            )

        assert result == FAKE_TOKEN

    def test_missing_token_in_response_exits(self):
        discovery = {"token_endpoint": "https://identity.example.com/token"}
        token_resp = {}  # no access_token

        with patch("requests.get", return_value=_ok_response(discovery)), \
             patch("requests.post", return_value=_ok_response(token_resp)), \
             pytest.raises(SystemExit):
            prog.get_access_token("https://x", "cid", "secret", "api")

    def test_missing_token_endpoint_exits(self):
        discovery = {}  # no token_endpoint

        with patch("requests.get", return_value=_ok_response(discovery)), \
             pytest.raises(SystemExit):
            prog.get_access_token("https://x", "cid", "secret", "api")


class TestGetData:
    def test_single_page_response(self):
        body = {"items": FAKE_POINTS}

        with patch("requests.get", return_value=_ok_response(body)):
            result = prog.get_data(FAKE_TOKEN, f"{SDS_URL}/Streams/{STREAM_1_ID}/Data/Window?startIndex=a&endIndex=b")

        assert result == {"items": FAKE_POINTS}

    def test_paginated_response_combines_pages(self):
        page1 = {"items": [FAKE_POINTS[0]], "continuationToken": "tok-abc"}
        page2 = {"items": [FAKE_POINTS[1]]}

        with patch("requests.get", side_effect=[_ok_response(page1), _ok_response(page2)]):
            result = prog.get_data(FAKE_TOKEN, f"{SDS_URL}/Streams/{STREAM_1_ID}/Data/Window?startIndex=a&endIndex=b")

        assert result == {"items": FAKE_POINTS}

    def test_adds_count_when_initial_url_has_no_query(self):
        with patch("Program.get", return_value=_ok_response({"items": []})) as mock_get:
            prog.get_data(FAKE_TOKEN, f"{SDS_URL}/Streams/{STREAM_1_ID}/Data/Window", count=250)

        called_url = mock_get.call_args[0][1]
        assert called_url.endswith("?count=250")

    def test_adds_count_when_initial_url_has_query(self):
        with patch("Program.get", return_value=_ok_response({"items": []})) as mock_get:
            prog.get_data(
                FAKE_TOKEN,
                f"{SDS_URL}/Streams/{STREAM_1_ID}/Data/Window?startIndex=a&endIndex=b",
                count=250,
            )

        called_url = mock_get.call_args[0][1]
        assert "&count=250" in called_url

    def test_paginated_request_includes_continuation_token_and_count(self):
        page1 = {"items": [FAKE_POINTS[0]], "continuationToken": "tok-abc"}
        page2 = {"items": [FAKE_POINTS[1]]}

        with patch("Program.get", side_effect=[_ok_response(page1), _ok_response(page2)]) as mock_get:
            result = prog.get_data(
                FAKE_TOKEN,
                f"{SDS_URL}/Streams/{STREAM_1_ID}/Data/Window?startIndex=a&endIndex=b",
                count=42,
            )

        assert result == {"items": FAKE_POINTS}
        first_url = mock_get.call_args_list[0][0][1]
        second_url = mock_get.call_args_list[1][0][1]
        assert "&count=42" in first_url
        assert "continuationToken=tok-abc" in second_url
        assert "count=42" in second_url

    def test_http_error_exits(self):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("500")

        with patch("requests.get", return_value=mock_resp), pytest.raises(SystemExit):
            prog.get_data(FAKE_TOKEN, f"{SDS_URL}/Streams/{STREAM_1_ID}/Data/Window")


class TestPostForData:
    def test_200_response_returns_result(self):
        body = {"result": {STREAM_1_ID: FAKE_POINTS}}
        mock_resp = _ok_response(body)

        with patch("Program.post", return_value=mock_resp):
            result = prog.post_for_data(
                FAKE_TOKEN,
                f"{SDS_URL}/Bulk/Streams/Data/Sampled",
                {"ids": [STREAM_1_ID]},
            )

        assert result == {STREAM_1_ID: FAKE_POINTS}

    def test_207_response_extracts_successful_data(self):
        body = {
            "multiStatus": [
                {"status": 200, "data": {STREAM_1_ID: FAKE_POINTS}},
                {"status": 200, "data": {STREAM_2_ID: FAKE_POINTS}},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 207
        mock_resp.json.return_value = body
        mock_resp.raise_for_status.return_value = None

        with patch("Program.post", return_value=mock_resp):
            result = prog.post_for_data(
                FAKE_TOKEN,
                f"{SDS_URL}/Bulk/Streams/Data/Sampled",
                {"ids": [STREAM_1_ID, STREAM_2_ID]},
            )

        assert STREAM_1_ID in result
        assert STREAM_2_ID in result

    def test_207_failed_stream_is_retried(self):
        """A stream that fails on the first 207 response should be retried."""
        fail_then_succeed = [
            # First call: stream 2 fails
            MagicMock(
                status_code=207,
                json=MagicMock(return_value={
                    "multiStatus": [
                        {"status": 200, "data": {STREAM_1_ID: FAKE_POINTS}},
                        {"status": 500, "resourceId": STREAM_2_ID},
                    ]
                }),
                raise_for_status=MagicMock(return_value=None),
            ),
            # Second call (retry): stream 2 succeeds
            MagicMock(
                status_code=207,
                json=MagicMock(return_value={
                    "multiStatus": [
                        {"status": 200, "data": {STREAM_2_ID: FAKE_POINTS}},
                    ]
                }),
                raise_for_status=MagicMock(return_value=None),
            ),
        ]

        with patch("Program.post", side_effect=fail_then_succeed):
            result = prog.post_for_data(
                FAKE_TOKEN,
                f"{SDS_URL}/Bulk/Streams/Data/Sampled",
                {"ids": [STREAM_1_ID, STREAM_2_ID]},
            )

        assert STREAM_1_ID in result
        assert STREAM_2_ID in result

    def test_non_207_continuation_token_requests_next_page(self):
        page1 = _ok_response(
            {
                "result": {STREAM_1_ID: [FAKE_POINTS[0]]},
                "continuationToken": "next-page",
            }
        )
        page2 = _ok_response(
            {
                "result": {STREAM_2_ID: [FAKE_POINTS[1]]},
            }
        )

        with patch("Program.post", side_effect=[page1, page2]) as mock_post:
            result = prog.post_for_data(
                FAKE_TOKEN,
                f"{SDS_URL}/Bulk/Streams/Data/Sampled",
                {"ids": [STREAM_1_ID, STREAM_2_ID]},
            )

        assert result[STREAM_1_ID] == [FAKE_POINTS[0]]
        assert result[STREAM_2_ID] == [FAKE_POINTS[1]]
        assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# End-to-end flow test – full script sequence with all HTTP mocked
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """
    Exercises the complete __main__ sequence:
      token → type → stream × 2 → backfill × 2 → window read → interpolated
      read → bulk sampled read
    Visual output (plot / table) is suppressed via matplotlib non-interactive
    backend and patching plt.show / input.
    """

    def _make_post_side_effect(self):
        """
        Returns a callable used as side_effect for requests.post.
        The first call is the token request; all subsequent calls are SDS writes
        (type, streams, data).
        """
        calls = {"n": 0}

        def _post(url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                # Token endpoint
                return _ok_response({"access_token": FAKE_TOKEN})
            # SDS POST (type / streams)
            return _ok_response({})

        return _post

    def test_full_flow(self, tmp_path, monkeypatch):
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend – no windows opened

        # Write minimal settings file
        settings = {
            "well_known_url": "https://identity.example.com/.well-known/openid-configuration",
            "client_id": "cid",
            "client_secret": "secret",
            "account_id": "acct-id",
            "data_store_id": "dev-store",
            "base_url": "https://platform.connect.aveva.com",
        }
        settings_path = tmp_path / "appsettings.json"
        settings_path.write_text(json.dumps(settings))

        # Write minimal SDS JSON files
        (tmp_path / "SDSType.json").write_text(json.dumps(SDS_TYPE_DEF))
        (tmp_path / "SDSStream1.json").write_text(json.dumps(SDS_STREAM_1_DEF))
        (tmp_path / "SDSStream2.json").write_text(json.dumps(SDS_STREAM_2_DEF))

        # Point Path(__file__) lookups at tmp_path
        monkeypatch.setattr(prog, "DEFAULT_SETTINGS_PATH", settings_path)

        # load_settings reads from the real filesystem; redirect to tmp_path
        original_load = prog.load_settings

        def _load_settings(path: Path):
            return original_load(tmp_path / path.name)

        monkeypatch.setattr(prog, "load_settings", _load_settings)

        # Fake window data response
        window_resp = _ok_response({"items": FAKE_POINTS})
        # Fake interpolated data response
        interpolated_resp = _ok_response({"items": FAKE_POINTS})
        # Fake bulk sampled response
        bulk_post_resp = _ok_response({"result": {STREAM_1_ID: FAKE_POINTS, STREAM_2_ID: FAKE_POINTS}})

        post_side_effect = self._make_post_side_effect()

        with patch("requests.get", side_effect=[
                # 1. OpenID discovery
                _ok_response({"token_endpoint": "https://identity.example.com/token"}),
                # 2. GET window data for stream 1
                window_resp,
                # 3. GET interpolated data for stream 2
                interpolated_resp,
            ]), \
             patch("requests.post", side_effect=post_side_effect), \
             patch("requests.put", return_value=_ok_response({})), \
             patch("Program.post", wraps=prog.post) as mock_prog_post, \
             patch("matplotlib.pyplot.show"), \
             patch("builtins.input", return_value=""):

            # Re-import post_for_data to pick up the patched requests.post
            # Run the __main__ block logic directly (avoiding re-exec)
            runtime_settings = prog.load_runtime_settings(settings_path)

            with patch("requests.get", side_effect=[
                _ok_response({"token_endpoint": "https://identity.example.com/token"}),
                window_resp,
                interpolated_resp,
            ]), patch("requests.post", side_effect=post_side_effect), \
               patch("requests.put", return_value=_ok_response({})):

                token = prog.get_access_token(
                    well_known_url=runtime_settings["well_known_url"],
                    client_id=runtime_settings["client_id"],
                    client_secret=runtime_settings["client_secret"],
                    scope="api",
                )
                assert token == FAKE_TOKEN

                prog.get_or_create_sds_type(token, runtime_settings)
                prog.get_or_create_sds_stream(token, runtime_settings, "SDSStream1.json")
                prog.get_or_create_sds_stream(token, runtime_settings, "SDSStream2.json")
                prog.backfill_stream_data(token, runtime_settings, STREAM_1_ID)
                prog.backfill_stream_data(token, runtime_settings, STREAM_2_ID)

                raw_data = prog.get_data(
                    token,
                    f"{runtime_settings['sds_url']}/Streams/{STREAM_1_ID}/Data/Window"
                    f"?startIndex={prog.DATA_BACKFILL_START_TIME}&endIndex={prog.DATA_BACKFILL_END_TIME}",
                )
                assert len(raw_data["items"]) == len(FAKE_POINTS)

                interp_data = prog.get_data(
                    token,
                    f"{runtime_settings['sds_url']}/Streams/{STREAM_2_ID}/Data/Interpolated/Interval"
                    f"?startIndex={prog.DATA_BACKFILL_START_TIME}&endIndex={prog.DATA_BACKFILL_END_TIME}&count=2",
                )
                assert len(interp_data["items"]) == len(FAKE_POINTS)

            with patch("Program.post", return_value=bulk_post_resp):
                bulk = prog.read_sampled_bulk_stream_data(
                    token, runtime_settings, [STREAM_1_ID, STREAM_2_ID], 5
                )
            assert STREAM_1_ID in bulk
            assert STREAM_2_ID in bulk

            with patch("matplotlib.pyplot.show"):
                prog.plot(bulk, "Sampled Data")
