# CSTEP Backend User-Wise Workflow

This workflow is based on the Django REST Framework views, URL routes, and permission classes in the project.

## Role Access Overview

```mermaid
flowchart TB
    Public["Public Visitor"]
    Base["BASE_USER"]
    Moderator["MODERATOR"]
    EventAdmin["EVENT_ADMIN"]
    SuperAdmin["SUPER_ADMIN"]

    Public --> Auth["Auth APIs<br/>register, login, verify OTP, resend OTP"]
    Auth --> Base

    Base --> BaseViews["User Views<br/>profile, events, registrations, live stream"]
    Moderator --> ModViews["Moderator Views<br/>users, registration review, lobby, analytics"]
    EventAdmin --> AdminViews["Event Admin Views<br/>event management, broadcast sessions, stream lifecycle"]
    SuperAdmin --> SuperViews["Super Admin Views<br/>role management, user deactivation, full admin access"]

    Base --> Moderator
    Moderator --> EventAdmin
    EventAdmin --> SuperAdmin
```

## Shared Authentication Flow

```mermaid
flowchart LR
    Start["User opens app"] --> RegisterOrLogin{"Has account?"}
    RegisterOrLogin -- "No" --> Register["POST /auth/register/"]
    Register --> OTP["OTP generated for phone and email"]
    OTP --> VerifyPhone["POST /auth/verify-otp/<br/>phone_number + otp"]
    VerifyPhone --> VerifyEmail["POST /auth/verify-otp/<br/>email + otp"]
    VerifyEmail --> Tokens["Access + refresh tokens returned"]

    RegisterOrLogin -- "Yes" --> Login["POST /auth/login/"]
    Login --> Tokens
    Tokens --> Protected["Call protected APIs with<br/>Authorization: Bearer access_token"]
    Protected --> Refresh["POST /auth/token/refresh/<br/>when access token expires"]
```

## BASE_USER View Workflow

```mermaid
flowchart TB
    User["BASE_USER"] --> Profile["Profile View<br/>GET/PATCH /auth/me/"]
    User --> EventList["Events View<br/>GET /events/"]
    EventList --> EventDetail["Event Detail<br/>GET /events/{id}/"]

    EventDetail --> RegisterEvent["Register for Event<br/>POST /registrations/"]
    RegisterEvent --> Pending["Registration status: PENDING"]
    Pending --> MyRegs["My Registrations<br/>GET /registrations/my/"]

    EventDetail --> LiveCheck{"Event status is LIVE?"}
    LiveCheck -- "No" --> Wait["Wait for stream to start"]
    LiveCheck -- "Yes" --> JoinStream["Join Stream<br/>POST /events/{id}/join/"]
    JoinStream --> Playback["Receive playback_url and viewer_session_id"]
    Playback --> Heartbeat["Send heartbeat while watching<br/>POST /events/{id}/heartbeat/"]
    Heartbeat --> Leave["Leave Stream<br/>POST /events/{id}/leave/"]
```

## MODERATOR View Workflow

```mermaid
flowchart TB
    Moderator["MODERATOR"] --> UserList["Users View<br/>GET /auth/users/"]
    Moderator --> UserDetail["User Detail<br/>GET /auth/users/{id}/"]

    Moderator --> RegAll["All Registrations<br/>GET /registrations/all/"]
    RegAll --> RegFilter["Optional event filter<br/>?event_id={id}"]
    RegFilter --> Review{"Review registration"}

    Review --> Accept["Accept<br/>PATCH /registrations/{id}/status/"]
    Review --> Hold["Hold<br/>PATCH /registrations/{id}/status/"]
    Review --> Reject["Reject<br/>PATCH /registrations/{id}/status/"]

    RegAll --> Travel["Review travel request<br/>PATCH /registrations/{id}/travel-status/"]
    RegAll --> Translation["Review translation request<br/>PATCH /registrations/{id}/translation-status/"]

    Moderator --> Lobby["Lobby Views"]
    Lobby --> Registered["Registered Participants<br/>GET /registrations/lobby/{event_id}/registered/"]
    Lobby --> Proposed["Pending Participants<br/>GET /registrations/lobby/{event_id}/proposed/"]

    Moderator --> Analytics["Analytics Views"]
    Analytics --> UserSummary["User Summary<br/>GET /analytics/user-summary/"]
    Analytics --> Participation["Participation Summary<br/>GET /analytics/{event_id}/participation/"]
    Analytics --> StreamAnalytics["Stream Analytics<br/>GET /events/{id}/analytics/"]
    Analytics --> ActiveViewers["Active Viewers<br/>GET /events/{id}/viewers/"]
```

## EVENT_ADMIN View Workflow

```mermaid
flowchart TB
    EventAdmin["EVENT_ADMIN"] --> CreateEvent["Create Event<br/>POST /events/"]
    CreateEvent --> Draft["Event status: DRAFT"]

    EventAdmin --> ManageOwn["Update/Delete Event<br/>PATCH/DELETE /events/{id}/"]
    Draft --> BroadcastSetup["Create Broadcast Session<br/>POST /events/broadcast-sessions/"]
    BroadcastSetup --> Credentials["Generate stream_key<br/>Save ingest_url and broadcaster"]

    Credentials --> Broadcaster["Assigned Broadcaster"]
    Broadcaster --> RetrieveSession["Retrieve Broadcast Session<br/>GET /events/broadcast-sessions/{id}/"]
    RetrieveSession --> Ingest["Use ingest_url + stream_key<br/>RTMP or WHIP"]

    EventAdmin --> GoLive["Start Stream<br/>POST /events/{id}/go_live/"]
    GoLive --> Live["Event status: LIVE<br/>Broadcast session active"]
    Live --> NotifyStart["WebSocket broadcast<br/>stream.started"]

    Live --> ViewersJoin["Authenticated users join and watch"]
    ViewersJoin --> LiveMetrics["Viewer sessions, concurrent viewers, heartbeats"]

    EventAdmin --> RotateKey["Regenerate stream key<br/>POST /events/broadcast-sessions/{id}/regenerate_key/"]
    RotateKey --> KeyAllowed{"Session active?"}
    KeyAllowed -- "No" --> NewKey["New stream_key returned"]
    KeyAllowed -- "Yes" --> Blocked["Blocked while stream is active"]

    Live --> EndStream["End Stream<br/>POST /events/{id}/end_stream/"]
    EndStream --> Ended["Event status: ENDED<br/>all active viewer sessions closed"]
    Ended --> NotifyEnd["WebSocket broadcast<br/>stream.ended"]
```

## SUPER_ADMIN View Workflow

```mermaid
flowchart TB
    SuperAdmin["SUPER_ADMIN"] --> FullAccess["Includes BASE_USER, MODERATOR, and EVENT_ADMIN access"]

    SuperAdmin --> UserMgmt["User Management"]
    UserMgmt --> ListUsers["List/Retrieve Users<br/>GET /auth/users/"]
    UserMgmt --> ChangeRole["Update User Role<br/>PATCH /auth/users/{id}/role/"]
    ChangeRole --> Roles["BASE_USER<br/>MODERATOR<br/>EVENT_ADMIN<br/>SUPER_ADMIN"]

    UserMgmt --> Deactivate["Deactivate User<br/>DELETE /auth/users/{id}/deactivate/"]
    Deactivate --> Inactive["User is_active = false"]
```

## Live Stream System Workflow

```mermaid
sequenceDiagram
    participant Admin as EVENT_ADMIN/SUPER_ADMIN
    participant API as Django API
    participant Media as Media Server
    participant WS as WebSocket Channel
    participant Viewer as Authenticated Viewer

    Admin->>API: Create event
    Admin->>API: Create broadcast session
    API-->>Admin: ingest_url + stream_key
    Admin->>API: POST /events/{id}/go_live/
    API->>WS: stream.started
    Admin->>Media: Start ingest using stream_key
    Media->>API: POST /events/webhooks/stream/
    API->>WS: stream.started / stream.ended / stream.error

    Viewer->>API: GET /events/
    Viewer->>API: POST /events/{id}/join/
    API-->>Viewer: playback_url + viewer_session_id
    Viewer->>WS: Connect ws/events/{event_id}/
    Viewer->>API: POST /events/{id}/heartbeat/
    Viewer->>API: POST /events/{id}/leave/

    Admin->>API: POST /events/{id}/end_stream/
    API->>WS: stream.ended
    API->>API: Close active viewer sessions
```

## View-To-Role Matrix

| View Area | BASE_USER | MODERATOR | EVENT_ADMIN | SUPER_ADMIN |
|---|---:|---:|---:|---:|
| Register, verify OTP, login | Yes | Yes | Yes | Yes |
| Own profile | Yes | Yes | Yes | Yes |
| List/detail events | Yes | Yes | Yes | Yes |
| Register for event | Yes | Yes | Yes | Yes |
| Join/live heartbeat/leave stream | Yes | Yes | Yes | Yes |
| List/retrieve users | No | Yes | Yes | Yes |
| Review registrations | No | Yes | Yes | Yes |
| Lobby views | No | Yes | Yes | Yes |
| Analytics | No | Yes | Yes | Yes |
| Create events | No | No | Yes | Yes |
| Manage events | No | Creator/object access only | Yes | Yes |
| Create/manage broadcast sessions | No | No | Yes | Yes |
| Update user roles | No | No | No | Yes |
| Deactivate users | No | No | No | Yes |
