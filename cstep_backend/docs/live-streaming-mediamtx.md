# Live Streaming With Self-Hosted WebRTC

This project includes a self-hosted MediaMTX container. For browser-based streaming, use WebRTC/WHIP. No paid streaming service or OBS is required.

## Start Services

Start the media server:

```powershell
docker compose up -d mediamtx
```

Start Django separately:

```powershell
python manage.py runserver
```

## Django Settings

The backend uses these defaults:

```env
MEDIA_SERVER_WEBRTC_BASE_URL=http://localhost:8889/live
MEDIA_SERVER_RTMP_BASE_URL=rtmp://localhost:1935/live
MEDIA_SERVER_HLS_BASE_URL=http://localhost:8888/live
```

Use your server domain or IP instead of `localhost` when testing from another device. Browser camera access usually requires `localhost` or HTTPS.

## Create WebRTC Broadcast Sessions

Create one broadcast session per camera. The first camera created for an event
is marked as the primary camera automatically:

```json
{
  "event": 1,
  "broadcaster": 1,
  "name": "Camera 1"
}
```

Add more cameras by creating more broadcast sessions for the same event:

```json
{
  "event": 1,
  "broadcaster": 1,
  "name": "Camera 2"
}
```

The response includes:

```json
{
  "id": 10,
  "name": "Camera 1",
  "is_primary": true,
  "stream_key": "...",
  "ingest_url": "http://localhost:8889/live/<stream_key>/whip",
  "playback_url": "http://localhost:8889/live/<stream_key>/whep"
}
```

## Open Broadcaster In Browser

Get the primary camera ingest details:

```text
http://localhost:8000/events/<event_id>/broadcast/
```

Or request a specific camera:

```text
http://localhost:8000/events/<event_id>/broadcast/?camera_id=<broadcast_session_id>
```

The response includes camera sessions in `broadcast_sessions`. Use each
camera's `ingest_url` in the browser publisher.

## Start Event In Django

After the browser publisher is open, call:

```http
POST /events/<event_id>/go_live/
```

Detail, watch, and join APIs return camera playback details in
`broadcast_sessions`.

```text
http://localhost:8889/live/<primary_stream_key>/whep
```

## Open Viewer In Browser

Get the primary camera playback URL:

```text
http://localhost:8000/events/<event_id>/watch/
```

Or request a specific camera:

```text
http://localhost:8000/events/<event_id>/watch/?camera_id=<broadcast_session_id>
```

## Viewer API Flow

After the event is live:

```http
POST /events/<event_id>/join/
```

The response returns `broadcast_sessions` and `viewer_session_id`.

For live status updates, connect:

```text
ws://localhost:8000/ws/events/<event_id>/?token=<access_token>
```

## Stop Stream

Stop publishing in the browser, then call:

```http
POST /events/<event_id>/end_stream/
```
