import hashlib
import secrets
from typing import ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields) -> "User":
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(TimeStampedModel, AbstractBaseUser, PermissionsMixin):
    """Minimal custom user model.

    Multi-user roles, workspace membership, and the full permission system
    are built in GOR-244. This exists now purely so the project never
    depends on Django's built-in `auth.User`.
    """

    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    display_name = models.CharField(max_length=255, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    def __str__(self) -> str:
        return self.email


class AccessPermission(TimeStampedModel):
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.name


class Role(TimeStampedModel):
    workspace = models.ForeignKey("core.Workspace", on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=100)
    permissions = models.ManyToManyField(AccessPermission, blank=True, related_name="roles")
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_role_workspace_name")
        ]

    def __str__(self) -> str:
        return self.name


class Membership(TimeStampedModel):
    workspace = models.ForeignKey(
        "core.Workspace", on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    roles = models.ManyToManyField(Role, blank=True, related_name="memberships")
    permission_grants = models.ManyToManyField(
        AccessPermission, blank=True, related_name="membership_grants"
    )
    permission_denials = models.ManyToManyField(
        AccessPermission, blank=True, related_name="membership_denials"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="uniq_workspace_user")
        ]

    def has_permission(self, key: str) -> bool:
        if self.user.is_superuser:
            return True
        if self.permission_denials.filter(key=key).exists():
            return False
        return (
            self.permission_grants.filter(key=key).exists()
            or AccessPermission.objects.filter(key=key, roles__memberships=self).exists()
        )


class Invitation(TimeStampedModel):
    workspace = models.ForeignKey(
        "core.Workspace", on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    roles = models.ManyToManyField(Role, blank=True, related_name="invitations")
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="sent_invitations"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, **kwargs):
        raw_token = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), **kwargs
        )
        return invitation, raw_token

    def can_accept(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()


class UserSession(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tracked_sessions")
    workspace = models.ForeignKey(
        "core.Workspace", null=True, on_delete=models.CASCADE, related_name="user_sessions"
    )
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)


class LoginAttempt(TimeStampedModel):
    email = models.EmailField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    was_successful = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=100, blank=True)


class PersonalPreference(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    active_workspace = models.ForeignKey(
        "core.Workspace", null=True, blank=True, on_delete=models.SET_NULL
    )
    settings = models.JSONField(default=dict, blank=True)


class APIKey(TimeStampedModel):
    workspace = models.ForeignKey(
        "core.Workspace", on_delete=models.CASCADE, related_name="api_keys"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=255)
    prefix = models.CharField(max_length=12, db_index=True)
    secret_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, **kwargs):
        secret = secrets.token_urlsafe(32)
        prefix = secrets.token_hex(6)
        instance = cls.objects.create(
            prefix=prefix, secret_hash=hashlib.sha256(secret.encode()).hexdigest(), **kwargs
        )
        return instance, f"sf_{prefix}_{secret}"

    def is_usable(self) -> bool:
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > timezone.now()
        )


class SecurityAuditEvent(TimeStampedModel):
    workspace = models.ForeignKey(
        "core.Workspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="security_events",
    )
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="security_events"
    )
    event = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
