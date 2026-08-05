from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserRole


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "salutation",
            "first_name",
            "middle_name",
            "last_name",
            "country_code",
            "phone_number",
            "email",
            "gender",
            "city",
            "state",
            "country",
            "designation",
            "org_type",
            "org_name",
            "motivation",
            "password",
        ]
    
    def create(self, validated_data):
        password = validated_data.pop("password")
        if validated_data.get("country_code",None)!="+91":
            validated_data["phone_verified"] = True
            validated_data["email_verified"] = True

        validated_data["is_active"] = True
        validated_data["role"] = UserRole.BASE_USER
        
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        username = attrs["username"]
        password = attrs["password"]

        user = (
            User.objects.filter(email=username).first()
            or User.objects.filter(phone_number=username).first()
        )

        if not user or not user.check_password(password):
            raise serializers.ValidationError("Invalid credentials")

        if not user.is_active:
            raise serializers.ValidationError("User account is inactive")

        if not user.phone_verified:
            raise serializers.ValidationError(
                "Please verify your phone number first."
            )

        attrs["user"] = user
        return attrs


class SendOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField()


class OTPVerifySerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    otp = serializers.CharField(min_length=4, max_length=10)


class ResetPasswordSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    otp = serializers.CharField(min_length=4, max_length=10)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match")
        return attrs


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "id", "salutation", "first_name", "middle_name", "last_name",
            "city", "state", "country_code","phone_number", "email", "role",
            "country", "designation", "org_type", "org_name", "motivation",
            "phone_verified","email_verified", "is_active","password","updated_at", "created_at",
        ]
        read_only_fields = ["id", "phone_verified","email_verified","is_active", "created_at"]

    def create(self, validated_data):
        validated_data["phone_verified"] = True
        validated_data["email_verified"] = True
        validated_data["is_active"] = True
        password = validated_data.pop("password")

        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

class UserRoleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["role"]

class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)

    @classmethod
    def get_tokens(cls, user):
        refresh = RefreshToken.for_user(user)
        return {"access": str(refresh.access_token), "refresh": str(refresh)}
    
class BulkUserUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        if not value.name.endswith((".xlsx", ".xls")):
            raise serializers.ValidationError("Only .xlsx or .xls files are supported.")
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("File size must not exceed 5MB.")
        return value