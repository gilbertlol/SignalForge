from django import forms

from apps.hunting.models import HuntProfileStatus
from apps.opportunities.models import OpportunityStatus


class HuntProfileForm(forms.Form):
    name = forms.CharField(max_length=255)
    description = forms.CharField(widget=forms.Textarea, required=False)
    require_domain = forms.BooleanField(required=False, initial=True)
    minimum_score = forms.IntegerField(min_value=0, initial=10)
    maximum_records = forms.IntegerField(min_value=1, max_value=1000, initial=25)
    activate_now = forms.BooleanField(required=False, initial=True)


class ProfileActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            (HuntProfileStatus.ACTIVE, "Activate"),
            (HuntProfileStatus.PAUSED, "Pause"),
            (HuntProfileStatus.ARCHIVED, "Archive"),
        ]
    )


class OpportunityStatusForm(forms.Form):
    status = forms.ChoiceField(choices=OpportunityStatus.choices)
