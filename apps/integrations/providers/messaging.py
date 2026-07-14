import uuid
from typing import Any

from apps.integrations.adapters import MessagingAdapter


class MockEmailAdapter(MessagingAdapter):
    provider_key = "mock_email"

    def is_configured(self) -> bool:
        return True

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        if message.get("simulate_failure"):
            raise RuntimeError("Mock email failure")
        return {"external_message_id": f"email-{uuid.uuid4()}", "status": "sent"}


class MockSMSAdapter(MessagingAdapter):
    provider_key = "mock_sms"

    def is_configured(self) -> bool:
        return True

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        if message.get("simulate_failure"):
            raise RuntimeError("Mock SMS failure")
        return {"external_message_id": f"sms-{uuid.uuid4()}", "status": "sent"}
