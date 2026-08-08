from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import APIKey

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user, including their authorization scope."""

    groups = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_service_account",
            "groups",
            "permissions",
        )
        read_only_fields = ("id", "is_service_account")

    def get_permissions(self, obj):
        # Effective permissions (own + inherited from groups), as
        # "app_label.codename" strings.
        return sorted(obj.get_all_permissions())


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for the registration endpoint.

    Writes the password through Django's password hashing on ``create``.
    """

    password = serializers.CharField(write_only=True, required=True)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "password", "first_name", "last_name")
        read_only_fields = ("id",)

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class APIKeySerializer(serializers.ModelSerializer):
    """Read serializer for API keys (never exposes the raw key)."""

    class Meta:
        model = APIKey
        fields = ("id", "name", "prefix", "created", "revoked", "expires_at")
        read_only_fields = ("id", "prefix", "created", "revoked", "expires_at")


class APIKeyCreateSerializer(serializers.ModelSerializer):
    """Create serializer; returns the raw key exactly once in ``key``."""

    class Meta:
        model = APIKey
        fields = ("id", "name", "prefix", "created", "expires_at", "key")
        read_only_fields = ("id", "prefix", "created", "key")

    key = serializers.CharField(read_only=True)

    def create(self, validated_data):
        request = self.context["request"]
        name = validated_data["name"]
        expires_at = validated_data.get("expires_at")
        instance, raw_key = APIKey.create(request.user, name, expires_at=expires_at)
        instance.key = raw_key  # ephemeral attribute for the response
        return instance