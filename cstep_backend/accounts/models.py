from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class UserRole(models.TextChoices):
    BASE_USER = "BASE_USER", "User"
    MODERATOR = "MODERATOR", "Moderator"
    EVENT_ADMIN = "EVENT_ADMIN", "Event Administrator"
    SUPER_ADMIN = "SUPER_ADMIN", "Super Administrator"


class Salutation(models.TextChoices):
    MR = "Mr", "Mr"
    MRS = "Mrs", "Mrs"
    MS = "Ms", "Ms"
    DR = "Dr", "Dr"
    PROF = "Prof", "Prof"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"
    PREFER_NOT_TO_SAY = "PREFER_NOT_TO_SAY", "Prefer Not To Say"


class OrganisationType(models.TextChoices):
    ORGANISATION = "ORGANISATION", "Institution or Organisation"
    INDEPENDENT = "INDEPENDENT", "Independent"


class UserManager(BaseUserManager):
    def create_user(self, email, phone_number, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, phone_number=phone_number, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, phone_number, password=None, **extra):
        extra.setdefault("role", UserRole.SUPER_ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, phone_number, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    salutation = models.CharField(max_length=10, choices=Salutation.choices, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    country_code = models.CharField(max_length=5,default="+91")
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(unique=True)
    gender = models.CharField(
        max_length=20, choices=Gender.choices, default=Gender.PREFER_NOT_TO_SAY
    )
    role = models.CharField(
        max_length=20, choices=UserRole.choices, default=UserRole.BASE_USER
    )

    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)

    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100,null=True,blank=True)
    country = models.CharField(max_length=100,default="India")

    designation = models.CharField(max_length=150)
    org_type = models.CharField(
        max_length=20,
        choices=OrganisationType.choices,
        default=OrganisationType.ORGANISATION,
    )
    org_name = models.CharField(max_length=250, blank=True)
    motivation = models.CharField(
        max_length=150,
        blank=True,
        help_text="What motivates you to attend this event?",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone_number", "first_name", "last_name"]

    objects = UserManager()

    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.full_name()} ({self.email})"

