'''
Copyright 2018-2026 AVEVA Group Limited

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
SPDX-License-Identifier: Apache-2.0
'''

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import requests

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

DEFAULT_SETTINGS_PATH = Path(__file__).with_name("appsettings.json")
DATA_BACKFILL_START_TIME = "2026-06-01T00:00:00Z"
DATA_BACKFILL_END_TIME = "2026-07-01T00:00:00Z"
DATA_BACKFILL_INTERVAL = "01:00:00"
DATA_READ_FILTER = ""
DATA_READ_INTERVAL = "24:00:00"
DATA_READ_BOUNDARY_TYPE = "Outside"
DATA_READ_START_BOUNDARY_TYPE = "Exact"
DATA_READ_END_BOUNDARY_TYPE = "Inside"
DATA_READ_SAMPLED_INTERVALS = 5


# ============================================================================
# PARSING & UTILITY FUNCTIONS
# ============================================================================

def parse_iso_datetime(value: str) -> datetime:
    # Support common UTC suffix used in timestamp payloads.
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value)


def parse_hms_interval_to_timedelta(value: str) -> timedelta:
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
    # Parse and validate timestamps before calculating sample count.
    start = parse_iso_datetime(start_iso.strip())
    end = parse_iso_datetime(end_iso.strip())
    if start > end:
        raise ValueError("time_range_iso start must be less than or equal to end")
    
    step = parse_hms_interval_to_timedelta(interval)
    time_range = end - start
    
    # Calculate the number of intervals (add 1 to include both start and end)
    interval_count = int(time_range / step) + 1
    
    return interval_count


def generate_random_timeindexeddouble_data(start_iso: str, end_iso: str, interval: str) -> list[dict[str, Any]]:
    # Build deterministic timestamps and random values for stream backfill samples.
    start = parse_iso_datetime(start_iso.strip())
    end = parse_iso_datetime(end_iso.strip())
    if start > end:
        raise ValueError("time_range_iso start must be less than or equal to end")

    step = parse_hms_interval_to_timedelta(interval)

    data: list[dict[str, Any]] = []
    current = start
    # Generate inclusive sample points so both the start and end timestamps are represented.
    while current <= end:
        timestamp = current.isoformat().replace("+00:00", "Z")
        data.append({"Timestamp": timestamp, "Value": random.random()})
        current += step

    return data


# ============================================================================
# CONFIGURATION & SETTINGS
# ============================================================================

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
    # Validate required auth and endpoint configuration values.
    settings = load_settings(settings_path)

    client_id = settings.get("ClientId")
    client_secret = settings.get("ClientSecret")
    account_id = settings.get("AccountId")
    data_store_id = settings.get("DataStoreId")
    resource = settings.get("Resource")
    scope = settings.get("Scope","api")

    if not client_id or not client_secret:
        fail("Set client_id and client_secret in appsettings.json.")

    if not account_id or not data_store_id:
        fail("Set account_id and data_store_id in appsettings.json.")

    if not resource:
        fail("Set resource to the full CONNECT Data Services endpoint URL in appsettings.json.")

    cleaned_account_id = account_id.removesuffix("/")
    cleaned_resource = resource.removeprefix("https://")
    well_known_url = f"https://identity.{cleaned_resource}/account/{cleaned_account_id}/authentication/.well-known/openid-configuration"
    streams_url = f"https://{cleaned_resource}/{scope}/account/{cleaned_account_id}/sds/{data_store_id}/v2"

    return {
        "well_known_url": well_known_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "streams_url" : streams_url,
        "scope": scope
    }


# ============================================================================
# AUTHENTICATION
# ============================================================================

def get_access_token(
    well_known_url: str,
    client_id: str,
    client_secret: str,
    scope: str,
) -> str:
    # First discover OAuth endpoints from OpenID metadata, then request client-credentials token.
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


# ============================================================================
# HTTP REQUEST HELPERS
# ============================================================================

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


# ============================================================================
# Streams Store OPERATIONS
# ============================================================================

def get_or_create_streams_type(token: str, runtime_settings: dict[str, str], streams_type_body: str) -> dict[str, Any]:
    # Upsert type definition so stream creation has a known schema.
    streams_type_id = streams_type_body["id"]
    response = post(token, f"{runtime_settings['streams_url']}/Types/{streams_type_id}", streams_type_body)
    print("Streams type created or retrieved")
    return response.json()


def get_or_create_stream(token: str, runtime_settings: dict[str, str], streams_body: str) -> dict[str, Any]:
    stream_id = streams_body["id"]
    response = post(token, f"{runtime_settings['streams_url']}/Streams/{stream_id}", streams_body)
    print("Stream created or retrieved")
    return response.json()


def backfill_stream_data(token: str, runtime_settings: dict[str, str], stream_id: str) -> None:
    # Seed each stream with sample values across the configured time range.
    data = generate_random_timeindexeddouble_data(DATA_BACKFILL_START_TIME, DATA_BACKFILL_END_TIME, DATA_BACKFILL_INTERVAL)
    put(token, f"{runtime_settings['streams_url']}/Streams/{stream_id}/Data", data)
    print(f'Data backfilled to stream {stream_id}')


def get_data(access_token: str, url: str, count: int = 1000) -> dict[str, Any]:
    # Read paginated results and flatten all pages into one items list.
    all_items = []
    continuation_token = None
    
    while True:
        # Rebuild each request URL from the original resource URL so pagination state is explicit.
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
        
        # Merge each page into one flat item list for the caller.
        if "items" in response_data:
            all_items.extend(response_data["items"])
        
        # Check for continuation token
        continuation_token = response_data.get("continuationToken")
        if not continuation_token:
            # No more pages, return combined results
            return {"items": all_items}
        
        # Continue to next page


def post_for_data(
    token: str,
    url: str,
    body: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    """Send POST request with pagination and retry logic for failed streams."""
    # Collect combined results from all pages and retries.
    all_data = {}
    stream_ids_to_retry = body.get("ids", [])
    retry_count = 0
    
    while retry_count <= max_retries:
        # Rebuild the request body from the current retry set so partial failures can be retried cleanly.
        request_body = {"ids": stream_ids_to_retry}
        
        response = post(token, url, request_body)
        response_data = response.json()
        
        # Handle 207 Multi-Status responses
        if response.status_code == 207:
            multi_status = response_data.get("multiStatus", [])
            failed_stream_ids = []
            
            for status_item in multi_status:
                if status_item.get("status") in [200, 201]:
                    # Extract successful data
                    if "data" in status_item:
                        all_data.update(status_item["data"])
                elif status_item.get("status") in [400, 401, 403, 404]:
                    # Bad request, unauthorized, forbidden or not found. Do not retry.
                    print(f"Error {status_item.get("status")}: {status_item.get("detail")} posting for data to stream {status_item.get("resourceId")}. Will not retry. {status_item.get("resolution")}")
                else:
                    # Collect failed stream IDs for retry while preserving successful results.
                    resource_id = status_item.get("resourceId")
                    if resource_id and retry_count < max_retries:
                        failed_stream_ids.append(resource_id)
                    else:
                        print(f"Maximum retries for {resource_id}. Will not retry. Error {status_item.get("status")}: {status_item.get("detail")}. {status_item.get("resolution")}")
            
            # Retry failed streams if any
            if failed_stream_ids:
                stream_ids_to_retry = failed_stream_ids
                retry_count += 1
                continue
            else:
                # No more failed streams
                break
        else:
            # Non-207 bulk reads return data in a normal result payload instead of per-stream statuses.
            if "result" in response_data:
                all_data.update(response_data["result"])
            
            # Check for continuation token (pagination)
            continuation_token = response_data.get("continuationToken")
            if continuation_token:
                # Keep paging with the same stream set until continuation token is exhausted.
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
    # Build bulk sampled-read endpoint and request body once for reuse.
    body_bulk = {"ids": stream_ids}
    url = (
        f"{runtime_settings['streams_url']}/Bulk/Streams/Data/Sampled"
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


# ============================================================================
# VISUALIZATION & DISPLAY
# ============================================================================

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

    # Normalise columns and coerce timestamp to datetime for plotting.
    df = df.rename(columns={c: c.lower() for c in ['Timestamp', 'Value'] if c in df.columns})
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Create a wider plotting window for better date readability.
    fig, ax = plt.subplots(figsize=(14, 6))

    # Use a simple matplotlib grid and a stable color cycle for stream separation.
    ax.grid(True, linestyle='--', alpha=0.3)
    color_cycle = plt.get_cmap('tab10').colors

    # Plot one or many series depending on whether stream_id is present.
    if 'stream_id' in df.columns:
        for index, (stream_id, group) in enumerate(df.groupby('stream_id', sort=False)):
            series = group.sort_values('timestamp') if 'timestamp' in group.columns else group
            ax.plot(
                series['timestamp'],
                series['value'],
                marker='o',
                label=str(stream_id),
                color=color_cycle[index % len(color_cycle)],
            )
        ax.legend(title='stream_id')
    else:
        ordered = df.sort_values('timestamp') if 'timestamp' in df.columns else df
        ax.plot(ordered['timestamp'], ordered['value'], marker='o')

    # Reduce axis crowding by auto-selecting fewer date ticks.
    locator = mdates.AutoDateLocator(minticks=4, maxticks=16)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    plt.gcf().autofmt_xdate() # Automatically rotates the dates for readability

    # Set window title
    fig.canvas.manager.set_window_title(title)

    # Display the chart
    plt.show()


def table(data: list[dict[str, Any]], title: str) -> None:
    # Convert data to dataframe.
    df = pd.DataFrame(data)

    # Normalise column names, then convert timestamp.
    df = df.rename(columns={c: c.lower() for c in ['Timestamp', 'Value'] if c in df.columns})
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Limit displayed rows for large datasets to keep the table legible.
    max_rows_per_page = 20
    total_rows = len(df)
    
    if total_rows > max_rows_per_page:
        # Display first page for large tables
        df_display = df.head(max_rows_per_page)
        title_text = f"Table (showing {max_rows_per_page} of {total_rows} rows)"
    else:
        df_display = df
        title_text = "Table"
    
    # Scale figure dimensions with table size.
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


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # End-to-end sample flow: authenticate, provision streams, write data, then read/visualize it.

    # Step 1. Load settings from appsettings.json.
    runtime_settings = load_runtime_settings(DEFAULT_SETTINGS_PATH)

    # Step 2. Get token from token endpoint found in well-known url.
    token = get_access_token(
        well_known_url=runtime_settings["well_known_url"],
        client_id=runtime_settings["client_id"],
        client_secret=runtime_settings["client_secret"],
        scope=runtime_settings["scope"]
    )

    # Step 3. Get type definition and send to CONNECT.
    streams_type = get_or_create_streams_type(token, runtime_settings, load_settings(Path(__file__).with_name("StreamType.json")))

    # Step 4. Get stream 1 definition and send to CONNECT.
    stream_1 = get_or_create_stream(token, runtime_settings, load_settings(Path(__file__).with_name("Stream1.json")))

    # Get stream 2 definition and send to CONNECT.
    stream_2 = get_or_create_stream(token, runtime_settings, load_settings(Path(__file__).with_name("Stream2.json")))

    # Step 5. Backfill data into stream 1.
    backfill_stream_data(token, runtime_settings, stream_1['id'])

    # Step 6. Backfill data into stream 2.
    backfill_stream_data(token, runtime_settings, stream_2['id'])

    # Step 7. Read and show stored data for stream 1 in time window.
    raw_data = get_data(
        token,
        (
            f"{runtime_settings['streams_url']}/Streams/{stream_1['id']}/Data/Window"
            f"?startIndex={DATA_BACKFILL_START_TIME}"
            f"&endIndex={DATA_BACKFILL_END_TIME}"
            f"&filter={DATA_READ_FILTER}"
            f"&boundaryType={DATA_READ_BOUNDARY_TYPE}"
            f"&startBoundaryType={DATA_READ_START_BOUNDARY_TYPE}"
            f"&endBoundaryType={DATA_READ_END_BOUNDARY_TYPE}"
        ),
    )
    table(raw_data["items"], f"Raw data for {stream_1['id']}")

    # Step 8. Read and show interpolated data for stream 2 in time window.
    interpolated_data = get_data(
        token,
        (
            f"{runtime_settings['streams_url']}/Streams/{stream_2['id']}/Data/Interpolated/Interval"
            f"?startIndex={DATA_BACKFILL_START_TIME}"
            f"&endIndex={DATA_BACKFILL_END_TIME}"
            f"&count={calculate_interval_count(DATA_BACKFILL_START_TIME,DATA_BACKFILL_END_TIME,DATA_READ_INTERVAL)}"
        ),
    )
    table(interpolated_data["items"], f"Interpolated data for {stream_2['id']}")

    # Step 9. Read and plot stored data for streams in bulk in time window.
    bulk_data = read_sampled_bulk_stream_data(token, runtime_settings, [stream_1['id'], stream_2['id']], DATA_READ_SAMPLED_INTERVALS)
    plot(bulk_data, "Sampled Data")

    input("Press Enter to exit...")



