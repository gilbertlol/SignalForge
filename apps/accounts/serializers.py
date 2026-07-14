import hashlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import APIKey, Invitation, Membership, Role, UserSession

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "display_name", "is_active", "created_at"]
        read_only_fields = ["id", "email", "is_active", "created_at"]


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    role_names: serializers.Field = serializers.SlugRelatedField(
        source="roles", many=True, read_only=True, slug_field="name"
    )

    class Meta:
        model = Membership
        fields = ["id", "user", "role_names", "is_active", "created_at"]


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    expires_in_hours = serializers.IntegerField(default=72, min_value=1, max_value=720)

    def create(self, validated_data):
        workspace = self.context["workspace"]
        role_ids = validated_data.pop("role_ids", [])
        roles = list(Role.objects.filter(workspace=workspace, id__in=role_ids))
        if len(roles) != len(set(role_ids)):
            raise serializers.ValidationError(
                {"role_ids": "Every role must belong to the active workspace."}
            )
        invitation, raw_token = Invitation.issue(
            workspace=workspace,
            email=validated_data["email"].lower(),
            invited_by=self.context["request"].user,
            expires_at=timezone.now() + timedelta(hours=validated_data["expires_in_hours"]),
        )
        invitation.roles.set(roles)
        invitation.raw_token = raw_token
        return invitation

    def to_representation(self, instance):
        return {
            "id": str(instance.id),
            "email": instance.email,
            "token": instance.raw_token,
            "expires_at": instance.expires_at,
        }


class InvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=12)
    display_name = serializers.CharField(required=False, allow_blank=True)

    @transaction.atomic
    def save(self):
        token_hash = hashlib.sha256(self.validated_data["token"].encode()).hexdigest()
        invitation = Invitation.objects.select_for_update().filter(token_hash=token_hash).first()
        if not invitation or not invitation.can_accept():
            raise serializers.ValidationError(
                {"token": "Invitation is invalid, expired, or already used."}
            )
        user, created = User.objects.get_or_create(
            email=invitation.email,
            defaults={"display_name": self.validated_data.get("display_name", "")},
        )
        if not created and user.has_usable_password():
            raise serializers.ValidationError(
                {"token": "An active account already uses this email."}
            )
        user.set_password(self.validated_data["password"])
        user.is_active = True
        user.save()
        membership, _ = Membership.objects.get_or_create(workspace=invitation.workspace, user=user)
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
        membership.roles.set(invitation.roles.all())
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at", "updated_at"])
        return user


class APIKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIKey
        fields = [
            "id",
            "name",
            "prefix",
            "scopes",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = ["id", "prefix", "last_used_at", "revoked_at", "created_at"]


class UserSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSession
        fields = [
            "id",
            "session_key",
            "ip_address",
            "user_agent",
            "last_seen_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields
