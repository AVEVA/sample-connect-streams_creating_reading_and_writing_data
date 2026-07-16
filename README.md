# Building a Python client to make REST API calls to the SDS Service

**Version:** 1.0.0

[![Build Status](https://dev.azure.com/AVEVA-VSTS/Cloud%20Platform/_apis/build/status%2Fproduct-readiness%2FADH%2FAVEVA.sample-adh-time_series-python?branchName=main)](https://dev.azure.com/AVEVA-VSTS/Cloud%20Platform/_build/latest?definitionId=16145&branchName=main)

The sample code in this topic demonstrates how to invoke SDS REST APIs using Python. By examining the code, you will see how to create an SdsType and SdsStream, and how to backfill and read data in SDS. There are three examples of reading data. Reading raw (stored) values of a single stream, reading interpolated data for a single stream and performing a bulk sampled call for multiple streams.

The sections that follow provide a brief description of the process from beginning to end.

Developed against Python 3.14.2

## Running the Sample

1. Clone the GitHub repository
1. Install required modules: `pip install -r requirements.txt`
1. Open the folder with your favorite IDE
1. Configure the sample using the file [appsettings.placeholder.json](appsettings.placeholder.json). Before editing, rename this file to `appsettings.json`. This repository's `.gitignore` rules should prevent the file from ever being checked in to any fork or branch, to ensure credentials are not compromised.
1. Update `appsettings.json` with the credentials provided by AVEVA
1. Run `program.py`

To Test the Sample:

1. Install pytest `python -m pip install pytest`
1. Run `python -m pytest -q`

## Sample Code Overview

Here is a high level overview of the steps performed by this sample:

1. Get bearer token from token endpoint found in the well-known url provided
1. Get or create SDS Type defined in SDSType.json
1. Get or create two SDS streams defined in SDSStream1.json and SDSStream2.json
1. Generate and backfill random data for Stream1 at the backfill start, end and interval provided in the globals
1. Generate and backfill random data for Stream1 at the backfill start, end and interval provided in the globals
1. Read raw/stored data for Stream1 and display the first 20 values in a table
1. Read interpolated data at the interval provided in the global variables for Stream2 and display the first 20 values in a table
1. Get bulk sampled data for both Stream1 and Stream2 and plot the values in a trend

## Configure the Sample

Included in the sample there is a configuration file with placeholders that need to be replaced with the proper values. They include information for authentication, your account information and connecting to the SDS service instance.

The values to be replaced are in `appsettings.json`:

```json
{
  "well_known_url": "https://identity.platform.connect.aveva.com/account/<account-id>/authentication/.well-known/openid-configuration",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "account_id": "your-account-id",
  "data_store_id": "your-data-store-id",
  "base_url": "https://platform.connect.aveva.com"
}
```
To modify the stream creation, backfill and data read behaviour:

1. To modify the SDS Type definition in SDSType.json. If you change the properties to be different than timestamp and value, you'll need to modify the build_time_series_data function to handle your properties accordingly.
1. To modify the SDS Stream definitions in SDSSTream1.json and SDSStream2.json.
1. To modify the start and end time of data backfill and data reading as well as the behaviour for readig data, modify the global variables at the beginning of Program.py:

    - **DEFAULT_SETTINGS_PATH** - The path to the appsettings.json file
    - **DATA_BACKFILL_START_TIME** - Start time of data backfill period (ISO 8601 format e.g. 2026-01-01T00:00:00Z)
    - **DATA_BACKFILL_END_TIME** - End time of data backfill period (ISO 8601 format e.g. 2026-01-01T00:00:00Z)
    - **DATA_BACKFILL_INTERVAL** - Indicates a time interval at which you'd like to backfill data (format is hh:mm:ss)
    - **DATA_READ_FILTER** - Filter for reading stream data. Expression used to filter the result set based on property values. Filter expressions support comparison operators (eq, ne, gt, ge, lt, le), logical operators (and, or, not), and functions like startswith, endswith, and contains. For datetime properties, use ISO 8601 format like '2023-01-01T00:00:00Z'. The filter syntax follows OData filter expression syntax for precise property-based filtering.
    - **DATA_READ_INTERVAL** - Indicates a time interval at which you'd like to read interpolated data (format is hh:mm:ss). This will be converted to a number of intervals to be sent to sds based on the start and end time.
    - **DATA_READ_BOUNDARY_TYPE** - Controls how data at or near the startIndex and endIndex boundaries is handled when retrieving data. This parameter applies the same boundary behavior to both start and end of the data window. (Exact, Inside, Outside or ExactOrCalculated)
    - **DATA_READ_START_BOUNDARY_TYPE** - Controls how data at or near the startIndex boundary is handled. Determines whether values exactly at the start boundary are included, excluded, or calculated based on interpolation settings. (Exact, Inside, Outside or ExactOrCalculated)
    - **DATA_READ_END_BOUNDARY_TYPE** - Controls how data at or near the endIndex boundary is handled. Determines whether values exactly at the start boundary are included, excluded, or calculated based on interpolation settings. (Exact, Inside, Outside or ExactOrCalculated)
    - **DATA_READ_SAMPLED_INTERVALS** - The number of evenly spaced intervals to divide the data into when requesting summaries or sampled data. Higher values produce more granular results with shorter time spans between points. 

---
 
For the main AVEVA samples page [ReadMe](https://github.com/AVEVA/AVEVA-Samples)