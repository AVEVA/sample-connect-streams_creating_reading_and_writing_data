import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import random

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

DEFAULT_SETTINGS_PATH = Path(__file__).with_name("appsettings.json")
DATA_BACKFILL_START_TIME = "2026-06-24T00:00:00Z"
DATA_BACKFILL_END_TIME = "2026-06-25T00:00:00Z"
DATA_BACKFILL_INTERVAL = "01:00:00"
DATA_READ_FILTER = ""
DATA_READ_COUNT = 1000
DATA_READ_BOUNDARY_TYPE = "Outside"
DATA_READ_START_BOUNDARY_TYPE = "Exact"
DATA_READ_END_BOUNDARY_TYPE = "Inside"


def _parse_iso_datetime(value: str) -> datetime:
    # Support common UTC suffix used in SDS payloads.
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value)


def _parse_hms_interval_to_timedelta(value: str) -> timedelta:
    # Supports H:MM:SS (for example 1:00:00).
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("interval must use H:MM:SS format, for example 1:00:00")

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
    except ValueError as exc:
        raise ValueError("interval must contain whole numbers in H:MM:SS format") from exc

    if hours < 0 or minutes < 0 or seconds < 0:
        raise ValueError("interval parts must be non-negative")
    if minutes >= 60 or seconds >= 60:
        raise ValueError("minutes and seconds must be less than 60")

    interval = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if interval <= timedelta(0):
        raise ValueError("interval must be greater than zero")
    return interval


def build_timeseries_data(start_iso: str, end_iso: str, interval: str) -> list[dict[str, Any]]:

    start = _parse_iso_datetime(start_iso.strip())
    end = _parse_iso_datetime(end_iso.strip())
    if start > end:
        raise ValueError("time_range_iso start must be less than or equal to end")

    step = _parse_hms_interval_to_timedelta(interval)

    data: list[dict[str, Any]] = []
    current = start
    index = 0
    while current <= end:
        timestamp = current.isoformat().replace("+00:00", "Z")
        data.append({"Timestamp": timestamp, "Value": random.random()})
        current += step
        index += 1

    return data


def fail(message: str, details: Any | None = None) -> None:
    print(message, file=sys.stderr)
    if details is not None:
        if isinstance(details, (dict, list)):
            print(json.dumps(details, indent=2), file=sys.stderr)
        else:
            print(str(details), file=sys.stderr)
    raise SystemExit(1)


def load_settings(settings_path: Path) -> dict[str, Any]:
    try:
        with settings_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        fail(f"Settings file not found: {settings_path}")
    except json.JSONDecodeError as exc:
        fail(f"Settings file is not valid JSON: {settings_path}", exc)

    if not isinstance(data, dict):
        fail("Settings file root must be a JSON object.")

    return data


def load_runtime_settings(settings_path: Path) -> dict[str, Any]:
    settings = load_settings(settings_path)

    well_known_url = settings.get("well_known_url")
    client_id = settings.get("client_id")
    client_secret = settings.get("client_secret")
    account_id = settings.get("account_id")
    data_store_id = settings.get("data_store_id")
    scope = settings.get("scope") or "api"
    base_url = settings.get("base_url")
    sds_api_version = settings.get("sds_api_version")

    if not well_known_url:
        fail("Set well_known_url in appsettings.json.")

    if not client_id or not client_secret:
        fail("Set client_id and client_secret in appsettings.json.")

    if not account_id or not data_store_id:
        fail("Set account_id and data_store_id in appsettings.json.")

    if not base_url:
        fail("Set base_url to the full CONNECT Data Services endpoint URL in appsettings.json.")

    if not sds_api_version:
        fail("Set sds_api_version in appsettings.json.")

    sds_url = f"{base_url}/api/account/{account_id}/sds/{data_store_id}/{sds_api_version}"

    return {
        "well_known_url": well_known_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
        "sds_url" : sds_url
    }


def get_access_token(
    well_known_url: str,
    client_id: str,
    client_secret: str,
    scope: str,
) -> str:
    try:
        discovery_response = requests.get(well_known_url, timeout=30)
        discovery_response.raise_for_status()
        discovery = discovery_response.json()
    except requests.RequestException as exc:
        fail("Failed to fetch OpenID configuration.", exc)

    token_endpoint = discovery.get("token_endpoint")
    if not token_endpoint:
        fail("token_endpoint was not present in OpenID configuration.", discovery)

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
    }

    try:
        token_response = requests.post(token_endpoint, data=payload, timeout=30)
        token_response.raise_for_status()
        token_json = token_response.json()
    except requests.RequestException as exc:
        error_payload = None
        try:
            error_payload = token_response.json()  # type: ignore[name-defined]
        except Exception:
            pass
        fail("Token request failed.", error_payload or exc)

    access_token = token_json.get("access_token")
    if not access_token:
        fail("No access_token in token response.", token_json)

    return access_token


def get(access_token: str, url: str) -> None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        fail("GET request failed.", exc)
    
    return response.json()

def post(access_token: str, url: str, body: Any) -> None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=30)
    except requests.RequestException as exc:
        fail("POST request failed.", exc)
    
    return response

def put(access_token: str, url: str, body: Any) -> None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.put(url, headers=headers, json=body, timeout=30)
    except requests.RequestException as exc:
        fail("PUT request failed.", exc)
    
    return response

def plot(data):
    # 1. Convert data to dataframe
    df = pd.DataFrame(data)

    # 2. Set the visual style 
    sns.set_theme(style="whitegrid")

    # 3. Plot multiple lines automatically using 'hue'
    sns.lineplot(data=df, x='timestamp', y='value', marker='o')

    # 4. Display the chart
    plt.title("Product Performance Comparison")
    plt.show()

if __name__ == "__main__":
    
    # load settings from appsettings.json
    runtime_settings = load_runtime_settings(DEFAULT_SETTINGS_PATH)

    # get token from token endpoint found in well-known url
    token = get_access_token(
        well_known_url=runtime_settings["well_known_url"],
        client_id=runtime_settings["client_id"],
        client_secret=runtime_settings["client_secret"],
        scope=runtime_settings["scope"],
    )

    print("Access token acquired")

    # get sds type definition and send to CONNECT
    sds_type_body = load_settings(Path(__file__).with_name("SDSType.json"))
    sds_type_id = sds_type_body["id"]
    post(token, f"{runtime_settings["sds_url"]}/Types/{sds_type_id}", sds_type_body)
    print("Sds type created or updated")

    # get sds stream definition and send to CONNECT
    sds_stream_body = load_settings(Path(__file__).with_name("SDSStream.json"))
    sds_stream_id = sds_stream_body["id"]
    post(token, f"{runtime_settings["sds_url"]}/Streams/{sds_stream_id}", sds_stream_body)
    print("Sds stream created or updated")

    # backfill data into stream
    data = build_timeseries_data(DATA_BACKFILL_START_TIME, DATA_BACKFILL_END_TIME, DATA_BACKFILL_INTERVAL)
    put(token, f"{runtime_settings['sds_url']}/Streams/{sds_stream_id}/Data", data)
    print("Data backfilled to stream")

    # read raw data in time window
    raw_data = get(
        token,
        (
            f"{runtime_settings['sds_url']}/Streams/{sds_stream_id}/Data/Window"
            f"?startIndex={DATA_BACKFILL_START_TIME}"
            f"&endIndex={DATA_BACKFILL_END_TIME}"
            f"&filter={DATA_READ_FILTER}"
            f"&count={DATA_READ_COUNT}"
            f"&boundaryType={DATA_READ_BOUNDARY_TYPE}"
            f"&startBoundaryType={DATA_READ_START_BOUNDARY_TYPE}"
            f"&endBoundaryType={DATA_READ_END_BOUNDARY_TYPE}"
        ),
    )
    plot(raw_data["items"])

    

    

