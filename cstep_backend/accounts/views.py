import openpyxl
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import User
from .permissions import IsModerator, IsSuperAdmin,IsEventAdmin
from .utils import Fast2SMSError,Fast2SMSService

from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny,IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
        RegisterSerializer,
        OTPVerifySerializer,
        UserSerializer,
        UserRoleUpdateSerializer,
        LoginSerializer,
        ResetPasswordSerializer,
        SendOTPSerializer,
        BulkUserUploadSerializer
    )


class AuthViewSet(viewsets.GenericViewSet):
    permission_classes = [AllowAny]
    

    @action(detail=False, methods=["post"], serializer_class=LoginSerializer)
    def login(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "message": "Login successful",
                "user": UserSerializer(user).data,
                "tokens": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                },
            }
        )

    @action(detail=False, methods=["post"])
    def logout(self, request):
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"message": "Refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            RefreshToken(refresh_token).blacklist()
        except Exception:
            return Response(
                {"message": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"message": "Logged out successfully"})

    @action(detail=False, methods=["post"], serializer_class=RegisterSerializer)
    def sign_up(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                user = serializer.save()
                
                if user.country_code == "+91":
                    try:
                        Fast2SMSService.send_otp(user.phone_number)
                    except Fast2SMSError as exc:
                        raise ValueError(str(exc))

                return Response(
                    {
                        "message": "Registration successful. OTP sent.",
                        "user": UserSerializer(user).data,
                    },
                    status=status.HTTP_201_CREATED,
                )
        except ValueError as exc:
            # OTP send failed — roll back the created user so they can retry sign_up cleanly
            return Response(
                {"message": "Registration failed. Could not send OTP.", "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"message": "Registration failed.", "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"], serializer_class=SendOTPSerializer,url_path="otp-login",)
    def request_login_otp(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone_number"]
       
        if not phone:
            return Response(
                {"message": "phone_number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(phone_number=phone).first()
        if not user:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if not user.phone_verified:
            return Response(
                {"message": "Phone number is not verified. Please complete sign up first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            Fast2SMSService.send_otp(phone)
        except Fast2SMSError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "OTP sent successfully"})

    @action(
        detail=False,
        methods=["post"],
        serializer_class=OTPVerifySerializer,
        url_path="verify-otp",
    )
    def verify_otp(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        phone_number = data["phone_number"]

        user = User.objects.filter(phone_number=phone_number).first()
        if not user:
            return Response(
                {"message": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            Fast2SMSService.verify_otp(phone_number, data["otp"])
        except ValidationError as exc:
            return Response({"message": str(exc.detail[0])}, status=status.HTTP_400_BAD_REQUEST)

        user.phone_verified = True
        user.email_verified = True
        user.save(update_fields=["phone_verified", "email_verified"])

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "message": "Phone number verified. Login successfully",
                "user": UserSerializer(user).data,
                "tokens": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                },
            }
        )

    @action(detail=False, methods=["post"], url_path="resend-otp",serializer_class=SendOTPSerializer)
    def resend_otp(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        phone = data["phone_number"]

        if not phone:
            return Response(
                {"message": "phone_number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(phone_number=phone).first()
        if not user:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            Fast2SMSService.send_otp(phone)
        except Fast2SMSError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "OTP resent successfully"})

    @action(detail=False, methods=["post"], url_path="forgot-password")
    def forgot_password(self, request):
        phone = request.data.get("phone_number")

        if not phone:
            return Response(
                {"message": "phone_number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(phone_number=phone).first()
        if not user:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            Fast2SMSService.send_otp(phone)
        except Fast2SMSError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "Password reset OTP sent"})

    @action(
        detail=False,
        methods=["post"],
        serializer_class=ResetPasswordSerializer,
        url_path="reset-password",
    )
    def reset_password(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        phone_number = data["phone_number"]

        user = User.objects.filter(phone_number=phone_number).first()
        if not user:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            Fast2SMSService.verify_otp(phone_number, data["otp"])
        except ValidationError as exc:
            return Response({"message": str(exc.detail[0])}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data["new_password"])
        user.save(update_fields=["password"])

        return Response({"message": "Password reset successfully"})

class UserViewSet(viewsets.ModelViewSet):
   
    queryset = User.objects.all()

    def get_permissions(self):
        if self.action == "me":
            return [IsAuthenticated()]
        return [IsModerator()]

    def get_serializer_class(self): # type: ignore[override]
        if self.action == "update_role":
            return UserRoleUpdateSerializer
        return UserSerializer

    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        if request.method == "GET":
            return Response(UserSerializer(request.user).data)

        serializer = UserSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)

    @action(detail=True, methods=["patch"], url_path="role")
    def update_role(self, request, pk=None):
        user = self.get_object()

        serializer = UserRoleUpdateSerializer(
            user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)

    @action(detail=True, methods=["delete"])
    def deactivate(self, request, pk=None):
        user = self.get_object()

        user.is_active = False
        user.save(update_fields=["is_active"])

        return Response(
            {"message": "User deactivated successfully"}
        )


class BulkUserCreateView(APIView):
    permission_classes = [IsEventAdmin]
    parser_classes = [MultiPartParser]
    required_headers = {
        "first_name","last_name","phone_number",
        "email","city","state","designation"
    }

    def post(self, request):
        upload = BulkUserUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        file = upload.validated_data["file"]

        try:
            wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
            sheet = wb.active
        except Exception:
            return Response(
                {"detail": "Could not read the Excel file. Ensure it is a valid .xlsx file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            return Response({"detail": "The uploaded file is empty."}, status=status.HTTP_400_BAD_REQUEST)

        headers = [str(h).strip().lower() if h else "" for h in header_row]
        missing = self.required_headers - set(headers)
        if missing:
            return Response(
                {"detail": f"Missing required columns: {', '.join(sorted(missing))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created, failed = [], []
        seen_emails, seen_phones = set(), set()

        for i, row in enumerate(rows, start=2):  # row 1 is header
            if row is None or all(cell in (None, "") for cell in row):
                continue

            data = {k: (str(v).strip() if v is not None else "") for k, v in zip(headers, row) if k}

            email = data.get("email", "").lower()
            phone_number = data.get("phone_number", "")

            if not email or not phone_number or not data.get("first_name") or not data.get("last_name"):
                failed.append({"row": i, "email": email, "error": "Missing required field(s)."})
                continue

            if email in seen_emails or phone_number in seen_phones:
                failed.append({"row": i, "email": email, "error": "Duplicate entry within the file."})
                continue

            if User.objects.filter(email=email).exists():
                failed.append({"row": i, "email": email, "error": "Email already registered."})
                continue

            if User.objects.filter(phone_number=phone_number).exists():
                failed.append({"row": i, "email": email, "error": "Phone number already registered."})
                continue

            user = User(
                salutation=data.get("salutation", ""),
                first_name=data["first_name"],
                middle_name=data.get("middle_name", ""),
                last_name=data["last_name"],
                phone_number=phone_number,
                email=email,
                gender=data.get("gender") or User._meta.get_field("gender").default,
                role=data.get("role") or User._meta.get_field("role").default,
                city=data.get("city", ""),
                state=data.get("state", ""),
                designation=data.get("designation", ""),
                org_type=data.get("org_type") or User._meta.get_field("org_type").default,
                org_name=data.get("org_name", ""),
                motivation=data.get("motivation", ""),
            )

            try:
                user.full_clean(exclude=["password"])
            except DjangoValidationError as e:
                failed.append({"row": i, "email": email, "error": "; ".join(sum(e.message_dict.values(), []))})
                continue

            user.set_unusable_password()

            try:
                with transaction.atomic():
                    user.save()
            except Exception as e:
                failed.append({"row": i, "email": email, "error": str(e)})
                continue

            seen_emails.add(email)
            seen_phones.add(phone_number)
            created.append({"row": i, "email": email, "id": user.id})

        return Response(
            {
                "total_rows_processed": len(created) + len(failed),
                "created_count": len(created),
                "failed_count": len(failed),
                "created": created,
                "failed": failed,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST,
        )


