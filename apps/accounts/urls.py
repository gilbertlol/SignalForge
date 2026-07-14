from django.urls import path

from .views import accept_invitation, login_view, logout_view, password_change, profile

urlpatterns = [
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("invitations/accept/", accept_invitation, name="accept-invitation"),
    path("profile/", profile, name="profile"),
    path("password/change/", password_change, name="password-change"),
]
