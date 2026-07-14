from django.conf import settings
from django.db import models

from apps.contacts.models import Contact
from apps.core.models import WorkspaceScopedModel
from apps.opportunities.models import Opportunity


class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"


class ChannelAccount(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    provider_key = models.SlugField(max_length=100, default="mock")
    address = models.CharField(max_length=320)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "channel", "address"], name="uniq_channel_address_workspace"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.channel})"


class Conversation(WorkspaceScopedModel):
    subject = models.CharField(max_length=500, blank=True)
    opportunity = models.ForeignKey(
        Opportunity, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations"
    )
    channel_account = models.ForeignKey(
        ChannelAccount, on_delete=models.PROTECT, related_name="conversations"
    )
    external_thread_id = models.CharField(max_length=255, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]

    def __str__(self) -> str:
        return self.subject or str(self.id)


class MessageParticipant(WorkspaceScopedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="participants"
    )
    contact = models.ForeignKey(Contact, null=True, blank=True, on_delete=models.SET_NULL)
    address = models.CharField(max_length=320)
    display_name = models.CharField(max_length=255, blank=True)
    is_internal = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "address"], name="uniq_conversation_participant_address"
            )
        ]

    def __str__(self) -> str:
        return self.display_name or self.address


class MessageDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"


class MessageStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    SCHEDULED = "scheduled", "Scheduled"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    RECEIVED = "received", "Received"
    BLOCKED = "blocked", "Blocked"


class ReplyClassification(models.TextChoices):
    POSITIVE = "positive", "Positive intent"
    OBJECTION = "objection", "Objection"
    MEETING = "meeting", "Meeting request"
    UNSUBSCRIBE = "unsubscribe", "Unsubscribe"
    UNKNOWN = "unknown", "Unknown"


class Message(WorkspaceScopedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    direction = models.CharField(max_length=20, choices=MessageDirection.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    sender = models.CharField(max_length=320)
    recipients = models.JSONField(default=list)
    subject = models.CharField(max_length=500, blank=True)
    body_text = models.TextField()
    status = models.CharField(max_length=30, choices=MessageStatus.choices)
    external_message_id = models.CharField(max_length=255, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    approval_reasons = models.JSONField(default=list, blank=True)
    reply_classification = models.CharField(
        max_length=30, choices=ReplyClassification.choices, blank=True
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    contains_pricing = models.BooleanField(default=False)
    contains_scope_commitment = models.BooleanField(default=False)
    high_risk = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=255, blank=True)
    send_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "external_message_id"],
                condition=~models.Q(external_message_id=""),
                name="uniq_external_message_conversation",
            )
        ]

    def __str__(self) -> str:
        return self.subject or f"{self.direction} {self.channel} message"


class ConsentStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    OPTED_IN = "opted_in", "Opted in"
    OPTED_OUT = "opted_out", "Opted out"


class ConsentRecord(WorkspaceScopedModel):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="consent_records")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(max_length=20, choices=ConsentStatus.choices)
    source = models.CharField(max_length=255)
    effective_at = models.DateTimeField()
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-effective_at"]


class SuppressionEntry(WorkspaceScopedModel):
    channel = models.CharField(max_length=20, choices=Channel.choices)
    address = models.CharField(max_length=320)
    reason = models.CharField(max_length=255)
    source_message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "channel", "address"], name="uniq_suppression_address"
            )
        ]


class OutreachEligibility(WorkspaceScopedModel):
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="eligibility_checks"
    )
    allowed = models.BooleanField()
    requires_approval = models.BooleanField(default=False)
    reasons = models.JSONField(default=list)
    rules = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]


class OutreachSequence(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    stop_on_reply = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class SequenceStep(WorkspaceScopedModel):
    sequence = models.ForeignKey(OutreachSequence, on_delete=models.CASCADE, related_name="steps")
    position = models.PositiveSmallIntegerField()
    channel = models.CharField(max_length=20, choices=Channel.choices)
    delay_minutes = models.PositiveIntegerField(default=0)
    subject_template = models.CharField(max_length=500, blank=True)
    body_template = models.TextField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["sequence", "position"], name="uniq_sequence_position")
        ]


class SequenceEnrollmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    CANCELED = "canceled", "Canceled"


class SequenceEnrollment(WorkspaceScopedModel):
    sequence = models.ForeignKey(
        OutreachSequence, on_delete=models.CASCADE, related_name="enrollments"
    )
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="sequence_enrollments"
    )
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20,
        choices=SequenceEnrollmentStatus.choices,
        default=SequenceEnrollmentStatus.ACTIVE,
    )
    current_step = models.PositiveSmallIntegerField(default=0)
    canceled_reason = models.CharField(max_length=255, blank=True)


class ProviderMessageEvent(WorkspaceScopedModel):
    channel_account = models.ForeignKey(ChannelAccount, on_delete=models.CASCADE)
    provider_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel_account", "provider_event_id"], name="uniq_provider_message_event"
            )
        ]


class FollowUpRequest(WorkspaceScopedModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    source_message = models.ForeignKey(Message, on_delete=models.CASCADE)
    reason = models.CharField(max_length=255)
    completed_at = models.DateTimeField(null=True, blank=True)
