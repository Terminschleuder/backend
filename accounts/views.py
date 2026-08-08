from django.contrib.auth import authenticate, login, logout
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import APIKey
from .serializers import (
    APIKeyCreateSerializer,
    APIKeySerializer,
    RegisterSerializer,
    UserSerializer,
)

# Re-export the simplejwt views so the URL conf can mount them from here.
TokenObtainView = TokenObtainPairView
TokenRefresh = TokenRefreshView


class RegisterView(APIView):
    """POST /api/auth/register/ — create a new user account."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class MeView(APIView):
    """GET /api/auth/me/ — return the currently authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)


class LoginView(APIView):
    """POST /api/auth/login/ — session-based login (admin / browser)."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    """POST /api/auth/logout/ — end the session."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        logout(request)
        return Response({"detail": "Logged out."})


class APIKeyListView(generics.ListCreateAPIView):
    """GET/POST /api/auth/api-keys/ — list and create your own API keys.

    The raw key is returned only on creation (never on list).
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.request.user.api_keys.all()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return APIKeyCreateSerializer
        return APIKeySerializer

    def perform_create(self, serializer):
        serializer.save()


class APIKeyDetailView(generics.RetrieveDestroyAPIView):
    """GET/DELETE /api/auth/api-keys/<id>/ — revoke (delete) one of your keys."""

    permission_classes = [IsAuthenticated]
    serializer_class = APIKeySerializer

    def get_queryset(self):
        return self.request.user.api_keys.all()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.revoked = True
        instance.save(update_fields=["revoked"])
        return Response(status=status.HTTP_204_NO_CONTENT)