from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.contacts.models import Contact
from apps.integrations.registry import get_messaging_adapter

from .models import (
    ConsentRecord,
    ConsentStatus,
    Conversation,
    FollowUpRequest,
    Message,
    MessageDirection,
    MessageStatus,
    OutreachEligibility,
    ProviderMessageEvent,
    ReplyClassification,
    SequenceEnrollment,
    SequenceEnrollmentStatus,
    SuppressionEntry,
)


class SendBlocked(RuntimeError):
    pass


def classify_reply(body: str) -> str:
    normalized = body.casefold()
    if any(term in normalized for term in ("unsubscribe", "stop emailing", "remove me", "opt out")):
        return ReplyClassification.UNSUBSCRIBE
    if any(term in normalized for term in ("book a call", "schedule", "meeting", "calendar")):
        return ReplyClassification.MEETING
    if any(term in normalized for term in ("too expensive", "not interested", "already use")):
        return ReplyClassification.OBJECTION
    if any(term in normalized for term in ("interested", "sounds good", "tell me more")):
        return ReplyClassification.POSITIVE
    return ReplyClassification.UNKNOWN


def evaluate_outreach(message: Message) -> OutreachEligibility:
    reasons: list[str] = []
    approval_reasons: list[str] = []
    rules: dict[str, Any] = {}
    recipients = [str(address).casefold() for address in message.recipients]
    suppressed = list(
        SuppressionEntry.objects.filter(
            workspace=message.workspace,
            channel=message.channel,
            address__in=recipients,
            active=True,
        ).values_list("address", flat=True)
    )
    rules["suppressed_recipients"] = suppressed
    if suppressed:
        reasons.append("recipient_suppressed")

    opted_out = ConsentRecord.objects.filter(
        workspace=message.workspace,
        contact__email__in=recipients,
        channel=message.channel,
        status=ConsentStatus.OPTED_OUT,
    ).exists()
    rules["opted_out"] = opted_out
    if opted_out:
        reasons.append("recipient_opted_out")

    recent_cutoff = timezone.now() - timedelta(hours=24)
    frequency_exceeded = Message.objects.filter(
        workspace=message.workspace,
        direction=MessageDirection.OUTBOUND,
        recipients__overlap=recipients,
        sent_at__gte=recent_cutoff,
    ).exists()
    rules["frequency_window_hours"] = 24
    if frequency_exceeded:
        reasons.append("contact_frequency_exceeded")

    hour = timezone.localtime().hour
    quiet_hours_enabled = message.conversation.channel_account.config.get(
        "quiet_hours_enabled", True
    )
    quiet_hours = quiet_hours_enabled and (hour >= 21 or hour < 8)
    rules["quiet_hours"] = {"start": 21, "end": 8, "active": quiet_hours}
    if quiet_hours:
        reasons.append("quiet_hours")

    previous_outreach = (
        Message.objects.filter(
            workspace=message.workspace,
            conversation=message.conversation,
            direction=MessageDirection.OUTBOUND,
            status__in=[MessageStatus.SENT, MessageStatus.DELIVERED],
        )
        .exclude(pk=message.pk)
        .exists()
    )
    if not previous_outreach:
        approval_reasons.append("first_outreach")
    if message.contains_pricing:
        approval_reasons.append("pricing")
    if message.contains_scope_commitment:
        approval_reasons.append("scope_commitment")
    if message.high_risk:
        approval_reasons.append("high_risk")
    if message.confidence is not None and message.confidence < Decimal("0.75"):
        approval_reasons.append("low_confidence")
    message.approval_reasons = approval_reasons
    message.save(update_fields=["approval_reasons", "updated_at"])
    return OutreachEligibility.objects.create(
        workspace=message.workspace,
        message=message,
        allowed=not reasons,
        requires_approval=bool(approval_reasons),
        reasons=reasons,
        rules=rules,
    )


def approve_message(message: Message, user) -> Message:
    message.approved_by = user
    message.approved_at = timezone.now()
    message.status = MessageStatus.APPROVED
    message.save(update_fields=["approved_by", "approved_at", "status", "updated_at"])
    record("message.approved", actor=user, object_type="Message", object_id=str(message.id))
    return message


def send_message(message: Message, *, actor=None, simulate_failure: bool = False) -> Message:
    eligibility = evaluate_outreach(message)
    if not eligibility.allowed:
        message.status = MessageStatus.BLOCKED
        message.failure_reason = ",".join(eligibility.reasons)
        message.save(update_fields=["status", "failure_reason", "updated_at"])
        record(
            "message.blocked",
            actor=actor,
            object_type="Message",
            object_id=str(message.id),
            metadata={"reasons": eligibility.reasons, "rules": eligibility.rules},
        )
        raise SendBlocked(message.failure_reason)
    if eligibility.requires_approval and message.approved_at is None:
        message.status = MessageStatus.PENDING_APPROVAL
        message.save(update_fields=["status", "updated_at"])
        raise SendBlocked("approval_required")
    adapter = get_messaging_adapter(message.conversation.channel_account.provider_key)
    if adapter is None or not adapter.is_configured():
        raise SendBlocked("provider_unavailable")
    message.status = MessageStatus.SENDING
    message.save(update_fields=["status", "updated_at"])
    result = None
    for _ in range(3):
        message.send_attempts += 1
        try:
            result = adapter.send(
                {
                    "sender": message.sender,
                    "recipients": message.recipients,
                    "subject": message.subject,
                    "body_text": message.body_text,
                    "simulate_failure": simulate_failure,
                }
            )
            break
        except RuntimeError as exc:
            message.failure_reason = exc.__class__.__name__
    if result is None:
        message.status = MessageStatus.FAILED
        message.save(update_fields=["status", "failure_reason", "send_attempts", "updated_at"])
        raise RuntimeError("Messaging provider failed after 3 attempts")
    now = timezone.now()
    message.status = MessageStatus.SENT
    message.external_message_id = result["external_message_id"]
    message.sent_at = now
    message.save(
        update_fields=[
            "status",
            "external_message_id",
            "sent_at",
            "send_attempts",
            "updated_at",
        ]
    )
    message.conversation.last_message_at = now
    message.conversation.save(update_fields=["last_message_at", "updated_at"])
    opportunity = message.conversation.opportunity
    if opportunity is not None and not opportunity.first_contacted_at:
        opportunity.first_contacted_at = now
        opportunity.save(update_fields=["first_contacted_at", "updated_at"])
    record("message.sent", actor=actor, object_type="Message", object_id=str(message.id))
    return message


@transaction.atomic
def synchronize_inbound(*, account, event_id: str, payload: dict[str, Any]) -> Message:
    event, created = ProviderMessageEvent.objects.select_for_update().get_or_create(
        channel_account=account,
        provider_event_id=event_id,
        defaults={
            "workspace": account.workspace,
            "event_type": "message.received",
            "payload": payload,
        },
    )
    if not created and event.message_id:
        existing_message = event.message
        if existing_message is not None:
            return existing_message
    thread_id = str(payload.get("thread_id", ""))
    conversation = Conversation.objects.filter(
        workspace=account.workspace, channel_account=account, external_thread_id=thread_id
    ).first()
    if conversation is None:
        conversation = Conversation.objects.create(
            workspace=account.workspace,
            channel_account=account,
            external_thread_id=thread_id,
            subject=str(payload.get("subject", "")),
        )
    body = str(payload.get("body_text", ""))
    classification = classify_reply(body)
    message, _ = Message.objects.get_or_create(
        workspace=account.workspace,
        conversation=conversation,
        external_message_id=str(payload["message_id"]),
        defaults={
            "direction": MessageDirection.INBOUND,
            "channel": account.channel,
            "sender": str(payload["sender"]).casefold(),
            "recipients": payload.get("recipients", [account.address]),
            "subject": str(payload.get("subject", "")),
            "body_text": body,
            "status": MessageStatus.RECEIVED,
            "reply_classification": classification,
        },
    )
    event.message = message
    event.save(update_fields=["message", "updated_at"])
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at", "updated_at"])
    SequenceEnrollment.objects.filter(
        workspace=account.workspace,
        conversation=conversation,
        status=SequenceEnrollmentStatus.ACTIVE,
        sequence__stop_on_reply=True,
    ).update(status=SequenceEnrollmentStatus.CANCELED, canceled_reason="reply_received")
    FollowUpRequest.objects.get_or_create(
        workspace=account.workspace,
        conversation=conversation,
        source_message=message,
        defaults={"reason": classification},
    )
    if classification == ReplyClassification.UNSUBSCRIBE:
        address = message.sender.casefold()
        SuppressionEntry.objects.update_or_create(
            workspace=account.workspace,
            channel=account.channel,
            address=address,
            defaults={"reason": "recipient_opt_out", "source_message": message, "active": True},
        )
        contact = Contact.objects.filter(workspace=account.workspace, email__iexact=address).first()
        if contact:
            ConsentRecord.objects.create(
                workspace=account.workspace,
                contact=contact,
                channel=account.channel,
                status=ConsentStatus.OPTED_OUT,
                source="inbound_message",
                effective_at=timezone.now(),
                evidence={"message_id": str(message.id)},
            )
        SequenceEnrollment.objects.filter(
            workspace=account.workspace,
            contact=contact,
            status=SequenceEnrollmentStatus.ACTIVE,
        ).update(status=SequenceEnrollmentStatus.CANCELED, canceled_reason="opt_out")
    return message
