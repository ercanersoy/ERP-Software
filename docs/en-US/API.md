# REST API and sensors

Other programs, devices and sensors can read and write data through a REST API at `/api/v1`. All data is exchanged as JSON (UTF-8 unless the request names another `charset`).

## Authorization

1. An administrator creates a key under **Administration › API keys**. A key can be limited to
   - selected data screens (none selected = all),
   - reading and/or writing,
   - IP addresses or networks (for example `192.168.10.0/24`),
   - a minimum interval between writes in milliseconds (faster writes get HTTP 429),
   - an expiry date.
2. The key is shown **only once**; only its SHA-256 hash is stored.
3. Send it with every request:

```
Authorization: Bearer erp_1a2b3c4d_...
```

or `X-API-Key: erp_1a2b3c4d_...`. Use HTTPS in production (see [Database systems and operation](DATABASES.md)). The API can be switched off under **Settings**.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /api/v1/ping` | Check the key; returns its name and rights |
| `GET /api/v1/entities` | Data screens the key may use, with their fields |
| `GET /api/v1/entities/{name}` | Data format (fields) of one data screen |
| `GET /api/v1/entities/{name}/config` | Reading interval for sensors (`read_interval_ms`) |
| `GET /api/v1/entities/{name}/records` | List records |
| `POST /api/v1/entities/{name}/records` | Create one record (object) or many (array, up to 1000) |
| `GET /api/v1/entities/{name}/records/{id}` | Read one record |
| `PUT /api/v1/entities/{name}/records/{id}` | Replace a record |
| `PATCH /api/v1/entities/{name}/records/{id}` | Change some fields of a record |
| `DELETE /api/v1/entities/{name}/records/{id}` | Delete a record |
| `GET /api/v1/entities/{name}/latest?n=10` | Newest records (for dashboards) |
| `POST /api/v1/files?kind=image&entity={name}` | Upload a file (multipart field `file`); returns its id |
| `GET /api/v1/files/{id}` | Download a file |
| `WS /api/v1/stream/{name}` | WebSocket for real time data |

Parameters of `GET .../records`: `limit` (1-1000, default 100), `offset`, `since_id` (only newer records, oldest first), `order` (a field name, `id`, `created_at` or `updated_at`), `dir` (`asc`/`desc`), `q` (search) and `<field>=<value>` filters for exact matches.

## Values

| Field type | JSON value |
|---|---|
| Text, long text, choice, e-mail | string |
| Integer, link | number (the id of the linked record) |
| Decimal, currency | string (`"1234.50"`) or number |
| Measurement | number |
| Yes / No | `true` / `false` |
| Date | `"2026-11-12"` |
| Date and time | `"2026-11-12T10:15:00Z"` (stored in UTC) |
| Document, image, video | file id from `POST /api/v1/files` |

Every record also has `id`, `created_at`, `updated_at`, `created_by` and `api_key_id`.

## Examples

Create a record:

```
curl -X POST https://erp.example.com/api/v1/entities/customers/records \
  -H "Authorization: Bearer $ERP_KEY" -H "Content-Type: application/json" \
  -d '{"name": "ACME Ltd.", "balance": "1500.00", "active": true}'
```

Answer: `201 Created` with `{"id": 42}`.

Send many sensor values at once:

```
curl -X POST https://erp.example.com/api/v1/entities/temperatures/records \
  -H "Authorization: Bearer $ERP_KEY" -H "Content-Type: application/json" \
  -d '[{"sensor": "hall", "celsius": 21.4}, {"sensor": "store", "celsius": 4.1}]'
```

Read only new records:

```
curl "https://erp.example.com/api/v1/entities/temperatures/records?since_id=1200&limit=500" \
  -H "Authorization: Bearer $ERP_KEY"
```

A request in a legacy character set:

```
Content-Type: application/json; charset=cp857
```

## Errors

Errors have the form `{"error": "code", "message": "...", "details": {...}}`.

| Status | Meaning |
|---|---|
| 400 | Invalid JSON or request |
| 401 | Missing, wrong, expired or not allowed key (or wrong IP address) |
| 403 | The key may not read or write this data screen |
| 404 | Unknown data screen or record |
| 422 | Validation failed; `details` names the fields (`required`, `invalid_number`, `not_unique`, `unknown_field`, ...) |
| 429 | Faster than the minimum interval of the key; see the `Retry-After` header |
| 503 | API switched off |

## Sensors: adjustable reading interval

For a data screen marked **Sensor / live data**, the administrator sets the **reading interval** (milliseconds). A sensor asks for it regularly and adapts, so the interval can be changed centrally without touching the devices:

```
GET /api/v1/entities/temperatures/config
{"entity": "temperatures", "read_interval_ms": 1000, "min_interval_ms": 0, "server_time": "..."}
```

A minimal sensor program in Python (standard library only):

```
import json, time, urllib.request

BASE = "https://erp.example.com/api/v1/entities/temperatures"
HEADERS = {"Authorization": "Bearer erp_...", "Content-Type": "application/json"}

def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)

interval = call("GET", BASE + "/config")["read_interval_ms"] / 1000
while True:
    value = read_temperature()          # your sensor code
    call("POST", BASE + "/records", {"sensor": "hall", "celsius": value})
    time.sleep(interval)
    interval = call("GET", BASE + "/config")["read_interval_ms"] / 1000
```

## WebSocket for real time data

`/api/v1/stream/{name}` keeps one connection open. Authenticate with the `Authorization` header (or, for clients that can not set headers, `?token=...`).

- On connect the server sends `{"event": "hello", "read_interval_ms": 1000, ...}`.
- Send a JSON object or array to store records; the answer is `{"event": "stored", "ids": [...]}`.
- Send `{"event": "config"}` to get the current reading interval.
- Keys with read permission receive every new record of the data screen: `{"event": "created", "records": [...]}` (also those created through REST).
- Errors: `{"event": "error", "error": "...", "details": {...}}`.

The live monitor in the web interface (`m` in the list of a sensor screen) refreshes at the reading interval.
