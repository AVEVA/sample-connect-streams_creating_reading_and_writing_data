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

To Test the sample:

1. Install pytest `python -m pip install pytest`
1. Run `python -m pytest -q`

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
---

Automated test uses Python 3.9.1 x64

For the main Cds time series samples page [ReadMe](https://github.com/AVEVA/AVEVA-Samples-CloudOperations/blob/main/docs/SDS_TIME_SERIES.md)  
For the main Cds samples page [ReadMe](https://github.com/AVEVA/AVEVA-Samples-CloudOperations)  
For the main AVEVA samples page [ReadMe](https://github.com/AVEVA/AVEVA-Samples)