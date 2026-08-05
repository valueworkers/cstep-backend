# CSTEP MVP — Django Backend

Django REST Framework + PostgreSQL + Redis backend for the CSTEP event management platform.

## Stack
- **Django 5** + **DRF 3.15**
- **PostgreSQL** — primary database
- **Redis** — OTP storage via Django cache
- **SimpleJWT** — access + refresh token auth

---

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start server
python manage.py runserver
```

Admin panel: http://localhost:8000/admin

---

## API Endpoints

User-wise workflow diagrams are available in [`docs/user-wise-workflow.md`](docs/user-wise-workflow.md).
Live streaming setup with the bundled MediaMTX Docker service is available in [`docs/live-streaming-mediamtx.md`](docs/live-streaming-mediamtx.md).

### Auth (`/auth/`)
| Method | URL | Access | Description |
|--------|-----|--------|-------------|
| POST | `/register/` | Public | Register user, triggers OTP |
| POST | `/login/` | Public | Returns access + refresh tokens |
| POST | `/token/refresh/` | Public | Refresh access token |
| POST | `/verify-otp/` | Public | Verify phone or email OTP |
| POST | `/resend-otp/` | Public | Resend OTP |
| GET | `/me/` | Auth | Current user profile |

### Users (`/auth/users/`)
| Method | URL | Access | Description |
|--------|-----|--------|-------------|
| GET | `/users/` | Moderator+ | List all users |
| GET | `/users/<id>/` | Moderator+ | User detail |
| PATCH | `/users/<id>/role/` | Super Admin | Update role |
| DELETE | `/users/<id>/deactivate/` | Super Admin | Deactivate user |

### Events (`/events/`)
| Method | URL | Access | Description |
|--------|-----|--------|-------------|
| GET | `/` | Auth | List events |
| POST | `/` | Event Admin+ | Create event |
| GET/PATCH | `/<id>/` | Auth / Event Admin+ | Get or update event |
| POST | `/<id>/join/` | Auth | Log join, get stream link |

### Registrations (`/registrations/`)
| Method | URL | Access | Description |
|--------|-----|--------|-------------|
| POST | `/` | Auth | Register for event |
| GET | `/my/` | Auth | My registrations |
| GET | `/all/` | Moderator+ | All registrations |
| PATCH | `/<id>/status/` | Moderator+ | Accept / Hold / Reject |
| PATCH | `/<id>/travel-status/` | Moderator+ | Accept/Reject travel |
| PATCH | `/<id>/translation-status/` | Moderator+ | Accept/Reject translation |

### Lobby (`/registrations/lobby/`)
| Method | URL | Access | Description |
|--------|-----|--------|-------------|
| GET | `/lobby/<event_id>/registered/` | Moderator+ | All registered users |
| GET | `/lobby/<event_id>/proposed/` | Moderator+ | Pending participants |

### Analytics (`/analytics/`)
| Method | URL | Access | Description |
|--------|-----|--------|-------------|
| GET | `/user-summary/` | Moderator+ | User + participant counts |
| GET | `/<event_id>/participation/` | Moderator+ | Breakdown by date/time/food/status |

---

## Roles
| Role | Access level |
|------|-------------|
| `BASE_USER` | Register, view events, submit registrations |
| `MODERATOR` | + Lobby, analytics, accept/reject |
| `EVENT_ADMIN` | + Create and manage events |
| `SUPER_ADMIN` | Full access including role management |

---

## Auth Flow
1. `POST /auth/register/` → user created, OTP sent to phone + email
2. `POST /auth/verify-otp/` with `phone_number` + `otp`
3. `POST /auth/verify-otp/` with `email` + `otp`
4. `POST /auth/login/` → `{"access": "...", "refresh": "..."}`
5. All protected routes: `Authorization: Bearer <access>`

---

## Sprint 2
- [ ] SMS integration (Twilio / AWS SNS)
- [ ] Email integration (SES / SendGrid)
- [ ] Feedback form app
- [ ] WebSocket (Django Channels) for live event stream
- [ ] Docker Compose
- [ ] Next.js frontend
