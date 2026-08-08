from django.urls import path

from .views import (
    APIKeyDetailView,
    APIKeyListView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    TokenObtainView,
    TokenRefresh,
)

app_name = "accounts"

urlpatterns = [
    # Session auth (admin / browser).
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    # JWT auth (external clients).
    path("token/", TokenObtainView.as_view(), name="token_obtain"),
    path("token/refresh/", TokenRefresh.as_view(), name="token_refresh"),
    # API keys ("app secrets") management.
    path("api-keys/", APIKeyListView.as_view(), name="apikey-list"),
    path("api-keys/<int:pk>/", APIKeyDetailView.as_view(), name="apikey-detail"),
]