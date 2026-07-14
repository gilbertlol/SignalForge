from django.contrib import admin

from .models import (
    ChannelAccount,
    ConsentRecord,
    Conversation,
    FollowUpRequest,
    Message,
    MessageParticipant,
    OutreachEligibility,
    OutreachSequence,
    ProviderMessageEvent,
    SequenceEnrollment,
    SequenceStep,
    SuppressionEntry,
)

for model in (
    ChannelAccount,
    Conversation,
    MessageParticipant,
    Message,
    ConsentRecord,
    SuppressionEntry,
    OutreachEligibility,
    OutreachSequence,
    SequenceStep,
    SequenceEnrollment,
    ProviderMessageEvent,
    FollowUpRequest,
):
    admin.site.register(model)
