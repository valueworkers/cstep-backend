# analytics/services.py
from datetime import timedelta, datetime, time

from django.db.models import Count, Avg, Sum, Q, F
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.utils import timezone
from accounts.models import User,Gender,OrganisationType
from events.models import Event, BroadcastSession, ViewerSession, Feedback, ScheduleItem, ScheduleItemType, EventDay
from registrations.models import Registration, RegistrationDay, RegistrationSession
from registrations.constants import RegistrationStatus, AttendanceMode

GENDER_LABELS = dict(Gender.choices)
ORG_TYPE_LABELS = dict(OrganisationType.choices)


# --------------------------------------------------------------- scoping ---

def _scope_registrations(event_id=None):
    qs = Registration.objects.all()
    return qs.filter(event_id=event_id) if event_id else qs


def _scope_viewer_sessions(event_id=None):
    qs = ViewerSession.objects.all()
    return qs.filter(event_id=event_id) if event_id else qs


def _scope_broadcast_sessions(event_id=None):
    qs = BroadcastSession.objects.all()
    return qs.filter(event_id=event_id) if event_id else qs


def _share(count, total):
    return round((count / total) * 100, 1) if total else 0.0


# ---------------------------------------------------------------- trends ---

TRUNC_MAP = {"daily": TruncDate, "weekly": TruncWeek, "monthly": TruncMonth}

DEFAULT_LOOKBACK = {
    "daily": timedelta(days=7),
    "weekly": timedelta(weeks=8),
    "monthly": timedelta(days=365),
}


def _default_trend_range(event_id, granularity):
    """
    Scoped to one event: default the range to that event's own lifespan -
    created_at (registration open) through scheduled_end (or today, if the
    event has no end date yet / is still ongoing).

    Overall view (no event_id): fall back to a rolling window, since there's
    no single "event lifespan" to anchor to across many events.
    """
    if event_id:
        event = Event.objects.filter(pk=event_id).values("created_at", "scheduled_end").first()
        if event:
            start = event["created_at"].date()
            end = event["scheduled_end"].date() if event["scheduled_end"] else timezone.localdate()
            return start, end

    end = timezone.localdate()
    start = (timezone.now() - DEFAULT_LOOKBACK.get(granularity, DEFAULT_LOOKBACK["daily"])).date()
    return start, end


def registration_trend(event_id=None, granularity="daily", date_from=None, date_to=None):
    """Registration Trend chart: count of new registrations per day/week/month.

    Pass explicit date_from/date_to to override the range. Without them:
      - scoped to an event  -> defaults to that event's created_at through
        scheduled_end (its full registration-to-event window)
      - overall (no event)  -> defaults to a rolling window per granularity

    Days/weeks/months with zero registrations are still included (as 0) so
    the chart doesn't have gaps.
    """
    trunc_fn = TRUNC_MAP.get(granularity, TruncDate)
    default_start, default_end = _default_trend_range(event_id, granularity)
    start = date_from or default_start
    end = date_to or default_end

    rows = (
        _scope_registrations(event_id)
        .filter(created_at__date__gte=start, created_at__date__lte=end)
        .annotate(period=trunc_fn("created_at"))
        .values("period")
        .annotate(count=Count("id"))
        .order_by("period")
    )
    counts_by_period = {r["period"]: r["count"] for r in rows}

    if granularity == "daily":
        # Gap-fill every calendar day in range, e.g. {"date": "2026-07-01", "count": 20}
        results = []
        current = start
        while current <= end:
            results.append({"date": current.isoformat(), "count": counts_by_period.get(current, 0)})
            current += timedelta(days=1)
        return results

    # weekly/monthly: return DB-grouped periods as-is (gap-filling arbitrary
    # week/month boundaries is a lot more code for little practical benefit -
    # add it here if the chart needs it later)
    return [{"date": r["period"].isoformat(), "count": r["count"]} for r in rows]


def _bucket_timestamps(timestamps, interval_minutes):
    """Bucket datetimes into interval_minutes-sized time-of-day slots, e.g. '09:15'."""
    buckets = {}
    for ts in timestamps:
        local_ts = timezone.localtime(ts) if timezone.is_aware(ts) else ts
        minutes_since_midnight = local_ts.hour * 60 + local_ts.minute
        bucket_start = (minutes_since_midnight // interval_minutes) * interval_minutes
        label = f"{bucket_start // 60:02d}:{bucket_start % 60:02d}"
        buckets[label] = buckets.get(label, 0) + 1
    return buckets


def participation_trend(event_id=None, mode="all", interval_minutes=15, day=None):
    """Participation Trend chart: joins bucketed by time-of-day, filterable by mode."""
    target_day = day or timezone.localdate()

    sessions = _scope_viewer_sessions(event_id).filter(joined_at__date=target_day)
    if mode != "all":
        user_ids = RegistrationDay.objects.filter(
            registration__event_id=event_id,
            attendance_mode__iexact=mode,
        ).values("registration__user_id")
        sessions = sessions.filter(user_id__in=user_ids)

    buckets = _bucket_timestamps(sessions.values_list("joined_at", flat=True), interval_minutes)
    return [{"time_slot": label, "count": count} for label, count in sorted(buckets.items())]


# ---------------------------------------------------------- registrations --

def registration_counts(event_id=None):
    """Registrations summary cards: Total / Accepted / Pending / On Hold / Rejected / Undecided Mode."""
    qs = _scope_registrations(event_id)

    status_counts = dict(qs.values_list("status").annotate(count=Count("id")))
    undecided_mode = qs.annotate(day_count=Count("days")).filter(day_count=0).count()

    return {
        "total": qs.count(),
        "accepted": status_counts.get(RegistrationStatus.ACCEPTED, 0),
        "pending": status_counts.get(RegistrationStatus.PENDING, 0),
        "on_hold": status_counts.get(RegistrationStatus.HOLD, 0),
        "rejected": status_counts.get(RegistrationStatus.REJECTED, 0),
        "undecided_mode": undecided_mode,
    }


def registration_insights(event_id=None, date=None):
    """Registration Insights panel: status table, attendance mode table
    (overall + per-date), participation-time table, participation-dates table.

    `date` scopes the day-based tables (attendance_mode, attendance_mode_by_date,
    participation_dates, participation_time) to a single EventDay's date.
    Registration Status is unaffected - it's a Registration-level status, not
    tied to any one day.
    """
    counts = registration_counts(event_id)
    reg_total = counts["total"]

    registration_status = [
        {"status": "Accepted", "count": counts["accepted"], "share": _share(counts["accepted"], reg_total)},
        {"status": "Pending", "count": counts["pending"], "share": _share(counts["pending"], reg_total)},
        {"status": "On Hold", "count": counts["on_hold"], "share": _share(counts["on_hold"], reg_total)},
        {"status": "Rejected", "count": counts["rejected"], "share": _share(counts["rejected"], reg_total)},
        {"status": "Total", "count": reg_total, "share": 100.0 if reg_total else 0.0},
    ]

    day_qs = RegistrationDay.objects.all()
    if event_id:
        day_qs = day_qs.filter(registration__event_id=event_id)
    if date:
        day_qs = day_qs.filter(day__date=date)

    # People, not day-selections: a registrant can appear under more than one
    # mode if they picked Physical on one day and Virtual on another - that's
    # captured explicitly as "Mixed" rather than silently inflating both counts.
    # When `date` is passed, each person has at most one row, so Mixed is
    # always 0 for a single-date view - that's expected, not a bug.
    modes_by_registration = {}
    for reg_id, mode in day_qs.values_list("registration_id", "attendance_mode").distinct():
        modes_by_registration.setdefault(reg_id, set()).add(mode)

    total_people = len(modes_by_registration)

    mode_person_counts = {value: 0 for value, _ in AttendanceMode.choices}
    mixed_count = 0
    for modes in modes_by_registration.values():
        if len(modes) > 1:
            mixed_count += 1
        else:
            only_mode = next(iter(modes))
            mode_person_counts[only_mode] = mode_person_counts.get(only_mode, 0) + 1

    attendance_mode = [
        {
            "mode": label,
            "count": mode_person_counts.get(value, 0),
            "share": _share(mode_person_counts.get(value, 0), total_people),
        }
        for value, label in AttendanceMode.choices
    ]
    if mixed_count:
        attendance_mode.append(
            {"mode": "Mixed (Physical + Virtual)", "count": mixed_count, "share": _share(mixed_count, total_people)}
        )
    attendance_mode.append(
        {"mode": "Total", "count": total_people, "share": 100.0 if total_people else 0.0}
    )

    # Per-date mode breakdown - within a single date each person has one row,
    # so this is a plain count, no "mixed" concept needed at this granularity.
    mode_by_date_rows = (
        day_qs.values("day__date", "attendance_mode")
        .annotate(count=Count("id"))
        .order_by("day__date")
    )
    attendance_mode_by_date = {}
    for r in mode_by_date_rows:
        date_key = r["day__date"]
        attendance_mode_by_date.setdefault(date_key, {"date": date_key, "total": 0})
        mode_label = dict(AttendanceMode.choices).get(r["attendance_mode"], r["attendance_mode"])
        attendance_mode_by_date[date_key][mode_label] = r["count"]
        attendance_mode_by_date[date_key]["total"] += r["count"]
    attendance_mode_by_date = sorted(attendance_mode_by_date.values(), key=lambda row: row["date"])

    session_qs = RegistrationSession.objects.all()
    if event_id:
        session_qs = session_qs.filter(registration__event_id=event_id)
    if date:
        session_qs = session_qs.filter(session__day__date=date)
    session_total = session_qs.count()
    time_rows = (
        session_qs.values("session__start_time", "session__end_time")
        .annotate(count=Count("id"))
        .order_by("session__start_time")
    )
    participation_time = [
        {
            "time_slot": f"{r['session__start_time']}–{r['session__end_time']}",
            "count": r["count"],
            "share": _share(r["count"], session_total),
        }
        for r in time_rows
    ]

    day_selection_total = day_qs.count()  # total (registration, day) rows, not distinct people
    date_rows = day_qs.values("day__date").annotate(count=Count("id")).order_by("day__date")
    participation_dates = [
        {"date": r["day__date"], "count": r["count"], "share": _share(r["count"], day_selection_total)}
        for r in date_rows
    ]

    return {
        "registration_status": registration_status,
        "attendance_mode": attendance_mode,
        "attendance_mode_by_date": attendance_mode_by_date,
        "participation_time": participation_time,
        "participation_dates": participation_dates,
    }


def _breakdown(qs, field, total, label_map=None):
    """Group a Registration queryset by a `user__<field>` and return label/count/share rows, sorted highest first."""
    rows = (
        qs.values(field)
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    label_map = label_map or {}
    return [
        {
            "label": label_map.get(r[field], r[field] or "Unspecified"),
            "count": r["count"],
            "share": _share(r["count"], total),
        }
        for r in rows
    ]


def registration_demographics(event_id=None, top_n_cities=None):
    """Who registered: breakdown by gender, org_type, state, and city.

    One row per Registration is counted (one registration = one user =
    one event, per the unique_user_event_registration constraint), so
    counts here line up with registration_counts()'s "total".

    `top_n_cities` optionally caps the city list to the N largest, with
    the rest folded into an "Other" row - city names are free text and can
    fan out into a very long tail, unlike gender/org_type/state.
    """
    qs = _scope_registrations(event_id).select_related("user")
    total = qs.count()

    gender = _breakdown(qs, "user__gender", total, GENDER_LABELS)
    org_type = _breakdown(qs, "user__org_type", total, ORG_TYPE_LABELS)
    designation = _breakdown(qs, "user__designation", total)
    state = _breakdown(qs, "user__state", total)
    city = _breakdown(qs, "user__city", total)
    country = _breakdown(qs, "user__country", total)

    if top_n_cities and len(city) > top_n_cities:
        kept, dropped = city[:top_n_cities], city[top_n_cities:]
        other_count = sum(row["count"] for row in dropped)
        kept.append({"label": "Other", "count": other_count, "share": _share(other_count, total)})
        city = kept

    return {
        "total": total,
        "by_gender": gender,
        "by_org_type": org_type,
        "by_designation":designation,
        "by_state": state,
        "by_city": city,
        "by_country": country,
    }


# -------------------------------------------------------------- streaming --

def _peak_concurrent_viewers(viewer_qs):
    """Sweep-line over [joined_at, left_at-or-now) intervals -> max overlap."""
    now = timezone.now()
    events = []
    for joined_at, left_at in viewer_qs.values_list("joined_at", "left_at"):
        events.append((joined_at, 1))
        events.append((left_at or now, -1))
    events.sort(key=lambda e: (e[0], e[1]))  # process departures before arrivals on ties

    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def _format_minutes(seconds):
    return f"{seconds // 60}m"


def streaming_summary(event_id=None):
    """Streaming Details table + the quick Streaming cards."""
    viewer_qs = _scope_viewer_sessions(event_id)
    broadcast_qs = _scope_broadcast_sessions(event_id)

    watch_stats = viewer_qs.aggregate(
        avg_watch=Avg("watch_duration_seconds"),
        total_watch=Sum("watch_duration_seconds"),
    )
    avg_seconds = int(watch_stats["avg_watch"] or 0)
    total_seconds = int(watch_stats["total_watch"] or 0)

    return {
        "currently_watching": viewer_qs.filter(left_at__isnull=True).count(),
        "unique_viewers": viewer_qs.values("user_id").distinct().count(),
        "broadcast_sessions": broadcast_qs.count(),
        "peak_concurrent_viewers": _peak_concurrent_viewers(viewer_qs),
        "avg_watch_time_seconds": avg_seconds,
        "avg_watch_time_display": _format_minutes(avg_seconds),
        "total_watch_time_seconds": total_seconds,
        "total_watch_time_display": _format_minutes(total_seconds),
        "live_broadcast": broadcast_qs.filter(is_active=True).exists(),
    }

# --------------------------------------------------------------- feedback ---

def get_feedback_analytics(event_id, event_day_id=None, schedule_item_id=None):
    """Generic filtered analytics — used for session-level and day-level queries."""
    qs = Feedback.objects.filter(event_id=event_id)

    if schedule_item_id:
        qs = qs.filter(schedule_item_id=schedule_item_id)
    elif event_day_id:
        qs = qs.filter(event_date_id=event_day_id)

    agg = qs.aggregate(total_feedback=Count("id"), avg_rating=Avg("rating"))

    distribution = (
        qs.values("rating").annotate(count=Count("id")).order_by("rating")
    )

    date_breakdown = (
        qs.annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    return {
        "total_feedback": agg["total_feedback"] or 0,
        "average_rating": round(agg["avg_rating"], 2) if agg["avg_rating"] else None,
        "rating_distribution": {str(r["rating"]): r["count"] for r in distribution},
        "feedback_by_date": [
            {"date": d["date"].isoformat(), "count": d["count"]} for d in date_breakdown
        ]
    }


def get_event_feedback_summary(event_id):
    """Event-level rollup with per-day and per-session breakdowns."""
    base = Feedback.objects.filter(event_id=event_id)

    overall = get_feedback_analytics(event_id)

    by_day = (
        base.exclude(event_date__isnull=True)
        .values("event_date_id", "event_date__day_number","event_date__date")
        .annotate(total=Count("id"), avg_rating=Avg("rating"))
        .order_by("event_date__day_number")
    )

    by_session = (
        base.filter(is_overall_rating=False)
        .values("schedule_item_id", "schedule_item__title")
        .annotate(total=Count("id"), avg_rating=Avg("rating"))
        .order_by("schedule_item_id")
    )

    return {
        "event_id": event_id,
        "overall": overall,
        "by_day": [
            {
                "event_day_id": d["event_date_id"],
                "day_number": d["event_date__day_number"],
                "event_date": d["event_date__date"],
                "total_feedback": d["total"],
                "average_rating": round(d["avg_rating"], 2) if d["avg_rating"] else None,
            }
            for d in by_day
        ],
        "by_session": [
            {
                "schedule_item_id": s["schedule_item_id"],
                "title": s["schedule_item__title"],
                "total_feedback": s["total"],
                "average_rating": round(s["avg_rating"], 2) if s["avg_rating"] else None,
            }
            for s in by_session
        ],
    }

# --------------------------------------------------------------- Live event analytics ---
class LiveAnalyticsService:
    """
    Builds the live-analytics payload for a single event. Construct one
    instance per push (per event) — `now` and the DB caches below are
    frozen at __init__ time so every table in one payload reads a
    consistent snapshot instead of drifting mid-build.
    """

    VISUAL_KEYS = frozenset({
        "statewise_login",
        "countrywise_login",
        "daywise_login",
        "session_wise_max_virtual",
        "no_show",
        "session_wise_feedback",
        "daywise_feedback",
        "chats",
        "participation_rate",
        "participation_time",
        "participation_duration",
    })

    def __init__(self, event):
        self.event = event
        self.now = timezone.now()
        self._sessions = None
        self._viewer_sessions_by_session = None

    # ---------- lazy caches, shared across methods ----------

    @property
    def sessions(self):
        if self._sessions is None:
            self._sessions = list(
                ScheduleItem.objects.filter(
                    day__event=self.event, item_type=ScheduleItemType.SESSION
                ).select_related("day").order_by("day__day_number", "order")
            )
        return self._sessions

    @property
    def viewer_sessions_by_session(self):
        if self._viewer_sessions_by_session is None:
            by_session = {}
            qs = ViewerSession.objects.filter(
                event=self.event, session__in=self.sessions
            ).only("session_id", "user_id", "joined_at", "left_at", "watch_duration_seconds")
            for vs in qs:
                by_session.setdefault(vs.session_id, []).append(vs)
            self._viewer_sessions_by_session = by_session
        return self._viewer_sessions_by_session

    def _sessions_filtered(self, session_id=None):
        """Filters a local copy so callers that need the full `sessions`
        cache (e.g. session_wise_max_virtual sharing a rate_table with
        participation_rate) aren't affected by another call's filter."""
        if session_id is None:
            return self.sessions
        return [s for s in self.sessions if s.id == session_id]

    # ---------- helpers ----------

    @staticmethod
    def _aware(dt):
        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

    def _duration_seconds(self, vs):
        if vs.left_at:
            return vs.watch_duration_seconds or int((vs.left_at - vs.joined_at).total_seconds())
        return int((self.now - vs.joined_at).total_seconds())

    @staticmethod
    def _session_duration_minutes(s):
        raw = (
            datetime.combine(s.day.date, s.end_time) - datetime.combine(s.day.date, s.start_time)
        ).total_seconds() / 60
        rounded = 5 * round(raw / 5)
        return rounded or 5  # floor at 5 min so a 0-length degenerate row never breaks bucketing

    @staticmethod
    def _duration_buckets(duration_min):
        """5-minute tick marks up to this session's scheduled length,
        e.g. duration_min=45 -> [5, 10, 15, 20, 25, 30, 35, 40, 45]."""
        return list(range(5, duration_min, 5)) + [duration_min]

    @staticmethod
    def _bucket_index(minutes_watched, num_buckets):
        idx = int(minutes_watched // 5)
        return min(idx, num_buckets - 1)  # anyone who outlasts the session lands in the last tick

    # ---------- Visual 1: Participation Time ----------
    def participation_time_table(self, session_id=None):
        rows = []
        combined_totals = {}
 
        for s in self._sessions_filtered(session_id):
            duration_min = self._session_duration_minutes(s)
            ticks = self._duration_buckets(duration_min)
            counts = {tick: 0 for tick in ticks}
 
            vs_list = self.viewer_sessions_by_session.get(s.id, [])
            unique_users = {vs.user_id for vs in vs_list}
            for vs in vs_list:
                minutes = self._duration_seconds(vs) / 60
                tick = ticks[self._bucket_index(minutes, len(ticks))]
                counts[tick] += 1
 
            rows.append({
                "session_id": s.id,
                "session_name": s.title,
                "session_duration_min": duration_min,
                "unique_participants": len(unique_users),
                # string keys: msgpack (WS broadcast) and JSON both reject
                # int dict keys, so convert here rather than downstream.
                "buckets": {str(tick): count for tick, count in counts.items()},
            })
 
            for tick, count in counts.items():
                combined_totals[tick] = combined_totals.get(tick, 0) + count
 
        return {"rows": rows}
 
    # ---------- Visual 2: Participation Rate ----------
    def participation_rate_table(self, interval_minutes=5, session_id=None):
        rows = []
        for s in self._sessions_filtered(session_id):
            start_dt = self._aware(datetime.combine(s.day.date, s.start_time))
            end_dt = self._aware(datetime.combine(s.day.date, s.end_time))
            last_point = min(self.now, end_dt)

            points, t = [], start_dt
            while t <= last_point:
                points.append(t)
                t += timedelta(minutes=interval_minutes)

            vs_list = self.viewer_sessions_by_session.get(s.id, [])
            series = [
                {
                    "time": t.strftime("%H:%M"),
                    "count": sum(
                        1 for vs in vs_list
                        if vs.joined_at <= t and (vs.left_at is None or vs.left_at >= t)
                    ),
                }
                for t in points
            ]

            rows.append({
                "session_id": s.id,
                "session_name": s.title,
                "session_duration_min": int((end_dt - start_dt).total_seconds() / 60),
                "points": series,
                "max_concurrent": max((p["count"] for p in series), default=0),
            })
        return {"rows": rows}

    # ---------- Visual 4: Session Wise Max Virtual Participant Count ----------
    def session_wise_max_virtual(self, rate_table=None, session_id=None):
        rate_table = rate_table or self.participation_rate_table(session_id=session_id)
        return [
            {
                "session_id": r["session_id"],
                "session_name": r["session_name"],
                "max_participants": r["max_concurrent"],
            }
            for r in rate_table["rows"]
        ]

    # ---------- Visual 5: Statewise Login ----------
    def statewise_login(self, day_id=None):
        """
        Unique viewers by state — sourced only from ViewerSession.state (captured
        per join), so this only counts users who actually joined a viewer session.
        No Registration/user lookup, since physical registrants may never join
        a ViewerSession at all and shouldn't be counted as a "login".
        """
        qs = ViewerSession.objects.filter(event=self.event).exclude(state="")
        if day_id:
            qs = qs.filter(day_id=day_id)
        return list(
            qs.values("state").annotate(count=Count("user", distinct=True)).order_by("-count")
        )

    # ---------- Visual 6: Countrywise Login (virtual only) ----------
    def countrywise_login(self, day_id=None):
        qs = ViewerSession.objects.filter(event=self.event).exclude(country="")
        if day_id:
            qs = qs.filter(day_id=day_id)
        return list(qs.values("country").annotate(count=Count("user", distinct=True)).order_by("-count"))

    def daywise_login(self, day_id=None):
        """Unique viewers per day — includes lobby/general watching, not just session watchers."""
        qs = ViewerSession.objects.filter(event=self.event, day__isnull=False)
        if day_id:
            qs = qs.filter(day_id=day_id)
        return list(
            qs.values("day_id", "day__day_number", "day__date")
            .annotate(count=Count("user", distinct=True))
            .order_by("day__day_number")
        )

    # ---------- Visual 7: No Show (per day) ----------
    def no_show(self, day_id=None):
        """Per-day no-show: virtual registrants for that day vs anyone who actually watched it."""
        rows = []
        days = EventDay.objects.filter(event=self.event)
        if day_id:
            days = days.filter(id=day_id)
        for day in days.order_by("day_number"):
            registered = set(
                RegistrationDay.objects.filter(day=day, attendance_mode=AttendanceMode.VIRTUAL)
                .values_list("registration__user_id", flat=True)
            )
            attended = set(ViewerSession.objects.filter(day=day).values_list("user_id", flat=True))
            rows.append({
                "day_id": day.id,
                "day_number": day.day_number,
                "registered": len(registered),
                "attended": len(registered & attended),
                "no_show": len(registered - attended),
            })
        return rows

    # ---------- Visual 8: Feedback ---------- 
    def session_wise_feedback(self, session_id=None, day_id=None):
        qs = Feedback.objects.filter(event=self.event, is_overall_rating=False)
        if session_id:
            qs = qs.filter(schedule_item_id=session_id)
        if day_id:
            qs = qs.filter(schedule_item__day_id=day_id)
        rows = list(
            qs.values("schedule_item_id", "schedule_item__title")
            .annotate(avg_rating=Avg("rating"), count=Count("id"))
            .order_by("schedule_item__day__day_number", "schedule_item__order")
        )
        # Avg() on a DecimalField returns Decimal, which msgpack can't
        # serialize for the WS broadcast path. Convert once here.
        for row in rows:
            if row["avg_rating"] is not None:
                row["avg_rating"] = float(row["avg_rating"])
        return rows
 
    def daywise_feedback(self, day_id=None):
        qs = Feedback.objects.filter(event=self.event, event_date__isnull=False)
        if day_id:
            qs = qs.filter(event_date_id=day_id)
        rows = list(
            qs.values("event_date_id", "event_date__day_number")
            .annotate(avg_rating=Avg("rating"), count=Count("id"))
            .order_by("event_date__day_number")
        )
        for row in rows:
            if row["avg_rating"] is not None:
                row["avg_rating"] = float(row["avg_rating"])
        return rows
 
    # ---------- Visual 9: # of Chats ----------
    def chat_count(self):
        """
        TODO: no ChatMessage model exists in what you've shared. Point this at
        it (or a Redis counter your chat consumer increments) once it exists.
        Stubbed at 0 so the payload shape stays stable for the frontend.
        """
        return {"total": 0}

    # ---------- Visual 10: Participation Duration (per-user) ----------
    def participation_duration(self, session_id=None, day_id=None):
        """
        Per-user watch record: who joined, when, for how long. Unlike
        participation_time_table (bucketed counts for a chart), this is a
        flat row-per-ViewerSession listing — meant for a table/export view.
        select_related('user') to avoid N+1 on full_name/email per row.
        """
        qs = ViewerSession.objects.filter(event=self.event).select_related("user")
        if session_id:
            qs = qs.filter(session_id=session_id)
        if day_id:
            qs = qs.filter(day_id=day_id)

        rows = []
        for vs in qs:
            user = vs.user
            rows.append({
                "user_id": user.id,
                "full_name": user.full_name(),
                "email": user.email,
                "joined_at": vs.joined_at.isoformat(),
                "left_at": vs.left_at.isoformat() if vs.left_at else None,
                "watch_duration_seconds": self._duration_seconds(vs),
            })
        return rows

    # ---------- Payload assembly ----------
    def build_payload(self, visuals=None):
        """visuals: None -> build everything. Otherwise an iterable of visual
        names -> build only those (intersected against VISUAL_KEYS, so a bad
        name from a client can't blow this up)."""
        wanted = self.VISUAL_KEYS if visuals is None else (self.VISUAL_KEYS & set(visuals))
        payload = {"event_id": self.event.id, "generated_at": self.now.isoformat()}
 
        rate_table = None
        if "session_wise_max_virtual" in wanted or "participation_rate" in wanted:
            rate_table = self.participation_rate_table()
 
        if "statewise_login" in wanted:
            payload["statewise_login"] = self.statewise_login()
        if "countrywise_login" in wanted:
            payload["countrywise_login"] = self.countrywise_login()
        if "daywise_login" in wanted:
            payload["daywise_login"] = self.daywise_login()
        if "session_wise_max_virtual" in wanted:
            payload["session_wise_max_virtual"] = self.session_wise_max_virtual(rate_table=rate_table)
        if "no_show" in wanted:
            payload["no_show"] = self.no_show()
        if "session_wise_feedback" in wanted:
            payload["session_wise_feedback"] = self.session_wise_feedback()
        if "daywise_feedback" in wanted:
            payload["daywise_feedback"] = self.daywise_feedback()
        if "chats" in wanted:
            payload["chats"] = self.chat_count()
        if "participation_rate" in wanted:
            payload["participation_rate"] = rate_table
        if "participation_duration" in wanted:
            payload["participation_duration"] = self.participation_duration()
 
        return payload
 