import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import requests

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

DEFAULT_SETTINGS_PATH = Path(__file__).with_name("appsettings.json")
DATA_BACKFILL_START_TIME = "2026-06-01T00:00:00Z"
DATA_BACKFILL_END_TIME = "2026-06-29T00:00:00Z"
DATA_BACKFILL_INTERVAL = "01:00:00"
DATA_READ_FILTER = ""
DATA_READ_INTERVAL = "24:00:00"
DATA_READ_BOUNDARY_TYPE = "Outside"
DATA_READ_START_BOUNDARY_TYPE = "Exact"
DATA_READ_END_BOUNDARY_TYPE = "Inside"
DATA_READ_SAMPLED_INTERVALS = 5


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


def calculate_interval_count(start_iso: str, end_iso: str, interval: str) -> int:
    """
    Calculate the number of intervals that fit within a time range.
    
    Args:
        start_iso: Start time in ISO 8601 format (e.g., "2026-06-24T00:00:00Z")
        end_iso: End time in ISO 8601 format (e.g., "2026-06-25T00:00:00Z")
        interval: Time interval in H:MM:SS format (e.g., "01:00:00")
    
    Returns:
        Number of intervals between start and end times (inclusive)
    """
    start = _parse_iso_datetime(start_iso.strip())
    end = _parse_iso_datetime(end_iso.strip())
    if start > end:
        raise ValueError("time_range_iso start must be less than or equal to end")
    
    step = _parse_hms_interval_to_timedelta(interval)
    time_range = end - start
    
    # Calculate the number of intervals (add 1 to include both start and end)
    interval_count = int(time_range / step) + 1
    
    return interval_count


def build_timeseries_data(start_iso: str, end_iso: str, interval: str) -> list[dict[str, Any]]:

    start = _parse_iso_datetime(start_iso.strip())
    end = _parse_iso_datetime(end_iso.strip())
    if start > end:
        raise ValueError("time_range_iso start must be less than or equal to end")

    step = _parse_hms_interval_to_timedelta(interval)

    data: list[dict[str, Any]] = []
    current = start
    while current <= end:
        timestamp = current.isoformat().replace("+00:00", "Z")
        data.append({"Timestamp": timestamp, "Value": random.random()})
        current += step

    return data


def fail(message: str, details: Any | None = None) -> NoReturn:
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
    base_url = settings.get("base_url")

    if not well_known_url:
        fail("Set well_known_url in appsettings.json.")

    if not client_id or not client_secret:
        fail("Set client_id and client_secret in appsettings.json.")

    if not account_id or not data_store_id:
        fail("Set account_id and data_store_id in appsettings.json.")

    if not base_url:
        fail("Set base_url to the full CONNECT Data Services endpoint URL in appsettings.json.")

    sds_url = f"{base_url}/api/account/{account_id}/sds/{data_store_id}/v2"

    return {
        "well_known_url": well_known_url,
        "client_id": client_id,
        "client_secret": client_secret,
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
    else:
        print("Access token acquired")
        
    return access_token


def get(access_token: str, url: str) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        fail("GET request failed.", exc)

    return response


def get_data(access_token: str, url: str, count: int = 1000) -> dict[str, Any]:

    all_items = []
    continuation_token = None
    
    while True:
        # Build URL with continuation token and count parameters if needed
        request_url = url
        if continuation_token:
            separator = "&" if "?" in request_url else "?"
            request_url = f"{request_url}{separator}continuationToken={continuation_token}&count={count}"
        elif "?" not in request_url:
            # Add count parameter to initial request
            request_url = f"{request_url}?count={count}"
        elif "count=" not in request_url:
            # URL already has parameters, append count
            request_url = f"{request_url}&count={count}"

        response = get(access_token, request_url)
        response_data = response.json()
        
        # Append items from this page
        if "items" in response_data:
            all_items.extend(response_data["items"])
        
        # Check for continuation token
        continuation_token = response_data.get("continuationToken")
        if not continuation_token:
            # No more pages, return combined results
            return {"items": all_items}
        
        # Continue to next page

def post(access_token: str, url: str, body: Any) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        fail("POST request failed.", exc)
    
    return response

def put(access_token: str, url: str, body: Any) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.put(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        fail("PUT request failed.", exc)
    
    return response

def plot(data: dict[str, list[dict[str, Any]]] | list[dict[str, Any]], title: str) -> None:
    # Handle dict with multiple streams or list of data points
    if isinstance(data, dict):
        # Convert dict of streams to a list with stream_id column
        all_data_points = []
        for stream_id, data_points in data.items():
            for point in data_points:
                point_copy = point.copy()
                point_copy['stream_id'] = stream_id
                all_data_points.append(point_copy)
        df = pd.DataFrame(all_data_points)
    else:
        # Handle single stream list of data points
        df = pd.DataFrame(data)

    # 2. Normalise column names so seaborn x/y references match, then convert timestamp
    df = df.rename(columns={c: c.lower() for c in ['Timestamp', 'Value'] if c in df.columns})
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 4. Set the visual style 
    sns.set_theme(style="whitegrid")

    # Create a wider plotting window for better date readability.
    fig, ax = plt.subplots(figsize=(14, 6))

    # 5. Plot multiple lines automatically using 'hue' for stream_id if available
    if 'stream_id' in df.columns:
        sns.lineplot(data=df, x='timestamp', y='value', hue='stream_id', marker='o', ax=ax)
    else:
        sns.lineplot(data=df, x='timestamp', y='value', marker='o', ax=ax)

    # 5. Reduce axis crowding by auto-selecting fewer date ticks.
    locator = mdates.AutoDateLocator(minticks=4, maxticks=16)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    plt.gcf().autofmt_xdate() # Automatically rotates the dates for readability

    # 6. Set window title
    fig.canvas.manager.set_window_title(title)

    # 7. Display the chart
    plt.show()

def table(data: list[dict[str, Any]], title: str) -> None:
    # 1. Convert data to dataframe
    df = pd.DataFrame(data)

    # 2. Normalise column names, then convert timestamp
    df = df.rename(columns={c: c.lower() for c in ['Timestamp', 'Value'] if c in df.columns})
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 3. Display the table in a window with scrolling for large datasets
    max_rows_per_page = 20
    total_rows = len(df)
    
    if total_rows > max_rows_per_page:
        # Display first page for large tables
        df_display = df.head(max_rows_per_page)
        title_text = f"Table (showing {max_rows_per_page} of {total_rows} rows)"
    else:
        df_display = df
        title_text = "Table"
    
    # Calculate appropriate figure size based on rows and columns
    n_rows, n_cols = df_display.shape
    fig_height = max(8, 0.3 * (n_rows + 1) + 1)  # +1 for header row
    fig_width = max(12, n_cols * 1.5)
    
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')
    
    # Set window title
    fig.canvas.manager.set_window_title(title)
    
    table_obj = ax.table(
        cellText=df_display.values,
        colLabels=df_display.columns,
        cellLoc='left',
        loc='center'
    )
    
    table_obj.auto_set_font_size(False)
    table_obj.set_fontsize(9)
    table_obj.scale(1, 1.5)
    
    # Style header row
    for i in range(n_cols):
        table_obj[(0, i)].set_facecolor('#40466e')
        table_obj[(0, i)].set_text_props(weight='bold', color='white')
    
    plt.title(title_text, pad=20)
    plt.tight_layout()
    plt.show()

def get_or_create_sds_type(token: str, runtime_settings: dict[str, str]) -> dict[str, Any]:
    sds_type_body = load_settings(Path(__file__).with_name("SDSType.json"))
    sds_type_id = sds_type_body["id"]
    response = post(token, f"{runtime_settings['sds_url']}/Types/{sds_type_id}", sds_type_body)
    print("Sds type created or retrieved")
    return response.json()

def get_or_create_sds_stream(token: str, runtime_settings: dict[str, str], stream_filename: str) -> dict[str, Any]:
    sds_stream_body = load_settings(Path(__file__).with_name(stream_filename))
    sds_stream_id = sds_stream_body["id"]
    response = post(token, f"{runtime_settings['sds_url']}/Streams/{sds_stream_id}", sds_stream_body)
    print("Sds stream created or retrieved")
    return response.json()

def backfill_stream_data(token: str, runtime_settings: dict[str, str], stream_id: str) -> None:
    data = build_timeseries_data(DATA_BACKFILL_START_TIME, DATA_BACKFILL_END_TIME, DATA_BACKFILL_INTERVAL)
    put(token, f"{runtime_settings['sds_url']}/Streams/{stream_id}/Data", data)
    print(f'Data backfilled to stream {stream_id}')

def post_for_data(
    token: str,
    url: str,
    body: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    """Send POST request with pagination and retry logic for failed streams."""
    all_data = {}
    stream_ids_to_retry = body.get("ids", [])
    retry_count = 0
    
    while retry_count <= max_retries:
        request_body = {"ids": stream_ids_to_retry}
        
        response = post(token, url, request_body)
        response_data = response.json()
        
        # Handle 207 Multi-Status responses
        if response.status_code == 207:
            multi_status = response_data.get("multiStatus", [])
            failed_stream_ids = []
            
            for status_item in multi_status:
                if status_item.get("status") == 200:
                    # Extract successful data
                    if "data" in status_item:
                        all_data.update(status_item["data"])
                else:
                    # Collect failed stream IDs for retry
                    resource_id = status_item.get("resourceId")
                    if resource_id and retry_count < max_retries:
                        failed_stream_ids.append(resource_id)
            
            # Retry failed streams if any
            if failed_stream_ids:
                stream_ids_to_retry = failed_stream_ids
                retry_count += 1
                continue
            else:
                # No more failed streams
                break
        else:
            # Non-207 response
            if "result" in response_data:
                all_data.update(response_data["result"])
            
            # Check for continuation token (pagination)
            continuation_token = response_data.get("continuationToken")
            if continuation_token:
                request_body["continuationToken"] = continuation_token
                stream_ids_to_retry = body.get("ids", [])  # Reset to original IDs for next page
                continue
            else:
                break
    
    return all_data

def read_sampled_bulk_stream_data(
    token: str,
    runtime_settings: dict[str, str],
    stream_ids: list[str],
    intervals: int,
) -> dict[str, Any]:
    body_bulk = {"ids": stream_ids}
    url = (
        f"{runtime_settings['sds_url']}/Bulk/Streams/Data/Sampled"
        f"?startIndex={DATA_BACKFILL_START_TIME}"
        f"&endIndex={DATA_BACKFILL_END_TIME}"
        f"&intervals={intervals}"
        f"&sampleBy=value"
        f"&filter={DATA_READ_FILTER}"
        f"&boundaryType={DATA_READ_BOUNDARY_TYPE}"
        f"&startBoundaryType={DATA_READ_START_BOUNDARY_TYPE}"
        f"&endBoundaryType={DATA_READ_END_BOUNDARY_TYPE}"
    )
    bulk_data = post_for_data(token, url, body_bulk)
    return bulk_data

if __name__ == "__main__":
    
    # load settings from appsettings.json
    runtime_settings = load_runtime_settings(DEFAULT_SETTINGS_PATH)

    # get token from token endpoint found in well-known url
    token = get_access_token(
        well_known_url=runtime_settings["well_known_url"],
        client_id=runtime_settings["client_id"],
        client_secret=runtime_settings["client_secret"],
        scope="api",
    )

    # get sds type definition and send to CONNECT
    sds_type = get_or_create_sds_type(token, runtime_settings)

    # get sds stream 1 definition and send to CONNECT
    sds_stream_1 = get_or_create_sds_stream(token, runtime_settings, "SDSStream1.json")

    # get sds stream 2 definition and send to CONNECT
    sds_stream_2 = get_or_create_sds_stream(token, runtime_settings, "SDSStream2.json")

    # backfill data into streams
    backfill_stream_data(token, runtime_settings, sds_stream_1['id'])
    backfill_stream_data(token, runtime_settings, sds_stream_2['id'])

    # read and show stored data for singular stream in time window
    raw_data = get_data(
        token,
        (
            f"{runtime_settings['sds_url']}/Streams/{sds_stream_1['id']}/Data/Window"
            f"?startIndex={DATA_BACKFILL_START_TIME}"
            f"&endIndex={DATA_BACKFILL_END_TIME}"
            f"&filter={DATA_READ_FILTER}"
            f"&boundaryType={DATA_READ_BOUNDARY_TYPE}"
            f"&startBoundaryType={DATA_READ_START_BOUNDARY_TYPE}"
            f"&endBoundaryType={DATA_READ_END_BOUNDARY_TYPE}"
        ),
    )
    table(raw_data["items"], f"Raw data for {sds_stream_1['id']}")

    # read and show interpolated data for a singular stream in time window
    interpolated_data = get_data(
        token,
        (
            f"{runtime_settings['sds_url']}/Streams/{sds_stream_2['id']}/Data/Interpolated/Interval"
            f"?startIndex={DATA_BACKFILL_START_TIME}"
            f"&endIndex={DATA_BACKFILL_END_TIME}"
            f"&count={calculate_interval_count(DATA_BACKFILL_START_TIME,DATA_BACKFILL_END_TIME,DATA_READ_INTERVAL)}"
        ),
    )
    table(interpolated_data["items"], f"Interpolated data for {sds_stream_2['id']}")

    # read and plot stored data for streams in bulk in time window
    bulk_data = read_sampled_bulk_stream_data(token, runtime_settings, [sds_stream_1['id'], sds_stream_2['id']], DATA_READ_SAMPLED_INTERVALS)
    plot(bulk_data, "Sampled Data")

    input("Press Enter to exit...")



