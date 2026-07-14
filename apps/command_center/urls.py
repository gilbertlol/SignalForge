from django.urls import path

from . import views

app_name = "command_center"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("review/", views.review_queue, name="review-queue"),
    path("runs/", views.run_monitor, name="runs"),
    path("organizations/", views.organizations, name="organizations"),
    path("organizations/<uuid:pk>/", views.organization_detail, name="organization-detail"),
    path("inbox/", views.inbox, name="inbox"),
    path("inbox/<uuid:pk>/approve/", views.approve_outbound, name="approve-message"),
    path("inbox/<uuid:pk>/send/", views.send_outbound, name="send-message"),
    path("search/", views.global_search, name="search"),
]
