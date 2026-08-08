from rest_framework import authentication, exceptions

from .models import APIKey


class APIKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate a request with a long-lived API key.

    Clients send the key in the Authorization header:

        Authorization: Api-Key <raw-key>

    On success the request's ``user`` is the key's owner (often a service
    account), so Django's group/permission machinery applies uniformly with
    JWT and session auth.
    """

    keyword = "Api-Key"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request)
        if not header:
            return None
        try:
            prefix, raw_key = header.split()
        except ValueError:
            return None
        if prefix.decode("utf-8") != self.keyword:
            return None  # Not an API-key request; let other auth classes try.
        if not raw_key:
            return None
        raw_key = raw_key.decode("utf-8")
        api_key = APIKey.lookup(raw_key)
        if api_key is None:
            raise exceptions.AuthenticationFailed("Invalid or revoked API key.")
        return (api_key.user, api_key)

    def authenticate_header(self, request):
        return self.keyword