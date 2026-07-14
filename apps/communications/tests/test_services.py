import pytest
from django.utils import timezone

from apps.contacts.tests.factories import ContactFactory
from apps.core.models import Workspace

from ..models import (
    Channel,
    ChannelAccount,
    ConsentStatus,
    Conversation,
    Message,
    MessageDirection,
    MessageStatus,
    OutreachSequence,
    SequenceEnrollment,
    SequenceEnrollmentStatus,
    SuppressionEntry,
)
from ..services import SendBlocked, approve_message, send_message, synchronize_inbound

pytestmark = pytest.mark.django_db


def communication_fixture():
    workspace = Workspace.objects.create(name="Comms", slug="comms")
    contact = ContactFactory(workspace=workspace, email="lead@example.com")
    account = ChannelAccount.objects.create(
        workspace=workspace,
        name="Sales",
        channel=Channel.EMAIL,
        provider_key="mock_email",
        address="sales@example.com",
        config={"quiet_hours_enabled": False},
    )
    conversation = Conversation.objects.create(
        workspace=workspace, channel_account=account, subject="Hello"
    )
    message = Message.objects.create(
        workspace=workspace,
        conversation=conversation,
        direction=MessageDirection.OUTBOUND,
        channel=Channel.EMAIL,
        sender=account.address,
        recipients=[contact.email],
        subject="Hello",
        body_text="Can we help?",
        status=MessageStatus.DRAFT,
    )
    return workspace, contact, account, conversation, message


def test_first_outreach_requires_approval_then_sends():
    _, _, _, _, message = communication_fixture()

    with pytest.raises(SendBlocked, match="approval_required"):
        send_message(message)
    assert message.status == MessageStatus.PENDING_APPROVAL

    approve_message(message, None)
    send_message(message)

    assert message.status == MessageStatus.SENT
    assert message.external_message_id.startswith("email-")
    assert message.eligibility_checks.count() == 2


def test_suppression_blocks_send_even_when_approved():
    workspace, contact, _, _, message = communication_fixture()
    message.approved_at = timezone.now()
    message.save()
    SuppressionEntry.objects.create(
        workspace=workspace,
        channel=Channel.EMAIL,
        address=contact.email,
        reason="manual",
    )

    with pytest.raises(SendBlocked, match="recipient_suppressed"):
        send_message(message)

    assert message.status == MessageStatus.BLOCKED
    assert message.eligibility_checks.get().rules["suppressed_recipients"] == [contact.email]


def test_provider_failure_retries_three_times():
    _, _, _, _, message = communication_fixture()
    message.approved_at = timezone.now()
    message.save()

    with pytest.raises(RuntimeError, match="3 attempts"):
        send_message(message, simulate_failure=True)

    assert message.send_attempts == 3
    assert message.status == MessageStatus.FAILED


def test_duplicate_inbound_event_is_idempotent_and_threads():
    _, _, account, conversation, _ = communication_fixture()
    conversation.external_thread_id = "thread-1"
    conversation.save()
    payload = {
        "message_id": "provider-message-1",
        "thread_id": "thread-1",
        "sender": "lead@example.com",
        "recipients": [account.address],
        "subject": "Re: Hello",
        "body_text": "Tell me more",
    }

    first = synchronize_inbound(account=account, event_id="event-1", payload=payload)
    second = synchronize_inbound(account=account, event_id="event-1", payload=payload)

    assert first == second
    assert conversation.messages.filter(direction=MessageDirection.INBOUND).count() == 1
    assert first.reply_classification == "positive"


def test_unsubscribe_suppresses_contact_and_cancels_sequences():
    workspace, contact, account, conversation, _ = communication_fixture()
    sequence = OutreachSequence.objects.create(workspace=workspace, name="Follow up")
    enrollment = SequenceEnrollment.objects.create(
        workspace=workspace,
        sequence=sequence,
        contact=contact,
        conversation=conversation,
    )

    message = synchronize_inbound(
        account=account,
        event_id="unsubscribe-event",
        payload={
            "message_id": "unsubscribe-message",
            "sender": contact.email,
            "recipients": [account.address],
            "body_text": "Please unsubscribe me",
        },
    )

    enrollment.refresh_from_db()
    assert message.reply_classification == "unsubscribe"
    assert enrollment.status == SequenceEnrollmentStatus.CANCELED
    assert SuppressionEntry.objects.filter(address=contact.email, active=True).exists()
    assert contact.consent_records.get().status == ConsentStatus.OPTED_OUT
