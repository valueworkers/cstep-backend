from django.db import models

class ChatReactionType(models.TextChoices):
    LIKE = "like", "👍"
    LOVE = "love", "❤️"
    CLAP = "clap", "🙌"

MIN_SECONDS_BETWEEN_MESSAGES = 1.0
MAX_MESSAGE_LENGTH = 500
EDIT_WINDOW_SECONDS = 15 * 60        # 15 minutes to edit, like WhatsApp
DELETE_WINDOW_SECONDS = 60 * 60      # 1 hour to delete your own message

class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SCHEDULED = "SCHEDULED", "Scheduled"
    LIVE = "LIVE", "Live"
    ENDED = "ENDED", "Ended"
    CANCELLED = "CANCELLED", "Cancelled"

class EventScheduleType(models.TextChoices):
    WHOLE_DAY = "WHOLE_DAY", "Whole Day (single session per date)"
    MULTI_SESSION = "MULTI_SESSION", "Multiple Sessions (custom schedule per date)"

class ScheduleItemType(models.TextChoices):
    SESSION = "SESSION", "Session"
    BREAKFAST_BREAK = "BREAKFAST_BREAK", "Breakfast Break"
    TEA_BREAK = "TEA_BREAK", "Tea Break"
    LUNCH_BREAK = "LUNCH_BREAK", "Lunch Break"
    DINNER_BREAK = "DINNER_BREAK", "Dinner Break"
    NETWORKING_BREAK = "NETWORKING_BREAK", "Networking Break"
    CUSTOM_BREAK = "CUSTOM_BREAK", "Custom Break"

class RecordingStatus(models.TextChoices):
    RECORDING = "RECORDING", "Recording"
    PROCESSING = "PROCESSING", "Processing"
    READY = "READY", "Ready"
    FAILED = "FAILED", "Failed"


def default_attendance_modes():
    return ["PHYSICAL", "VIRTUAL"]

