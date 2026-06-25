# new-public-sample-template

**Version:** 1.0.0



---

For the main AVEVA samples page [ReadMe](https://github.com/AVEVA)

## Get CONNECT Bearer Token (Python, OAuth 2.0)

This sample includes a Python script that:

- Reads your OpenID Connect metadata from the well-known URL.
- Extracts the `token_endpoint`.
- Requests an OAuth 2.0 client credentials token.

### Well-known URL

By default, the script uses:

https://identity.platform.connect.aveva.com/account/4af5e437-75b6-4759-b1af-a3922b9db82f/authentication/.well-known/openid-configuration

### Prerequisites

- Python 3.10+
- A CONNECT OAuth client with:
	- `client_id`
	- `client_secret`
	- A valid scope (default used by script is `api`)

### Install dependencies

```powershell
pip install -r requirements.txt
```

### Configure appsettings.json

Create `appsettings.json` in the repository root (you can copy from `appsettings.example.json`):

```json
{
	"well_known_url": "https://identity.platform.connect.aveva.com/account/4af5e437-75b6-4759-b1af-a3922b9db82f/authentication/.well-known/openid-configuration",
	"client_id": "your-client-id",
	"client_secret": "your-client-secret",
	"scope": "api",
	"data_service_url": "https://your-connect-data-service-endpoint"
}
```

### Run

```powershell
python get_connect_token.py
```

The script prints token metadata and the access token.

## Call CONNECT Data Services With Bearer Token

Use `call_connect_data_service.py` to:

- Discover the OAuth token endpoint from your well-known URL.
- Request a bearer token with client credentials.
- Call a CONNECT Data Services endpoint with `Authorization: Bearer <token>`.

### Configure appsettings.json

Set `data_service_url` in `appsettings.json` to the full CONNECT Data Services endpoint URL.

### Run

```powershell
python call_connect_data_service.py
```

The script prints HTTP status, response headers, and response body from the Data Services endpoint.
