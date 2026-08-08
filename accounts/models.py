import hashlib
import hmac
import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Custom user model for terminschleuder.

    Supports both human users and **service/system accounts** (non-interactive
    clients). A service account is a normal Django user — so it carries groups
    and permissions and works with JWT — flagged with ``is_service_account``.
    Its generated password is the "app secret" used to obtain a JWT.
    """

    is_service_account = models.BooleanField(
        default=False,
        help_text="Designates this as a non-interactive service/system account.",
    )
    description = models.TextField(blank=True)

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return self.username


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class APIKey(models.Model):
    """A long-lived API key ("app secret") tied to a user.

    The raw key is shown to the caller only once, at creation. Only the sha256
    hash is stored; lookups hash the incoming key and compare in constant time.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=120, help_text="Label for this key.")
    prefix = models.CharField(
        max_length=16, db_index=True, help_text="Public prefix to identify the key."
    )
    hashed_key = models.CharField(max_length=64, unique=True)
    created = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_apikey"
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…) for {self.user.username}"

    @classmethod
    def create(cls, user, name, expires_at=None) -> tuple["APIKey", str]:
        """Create a key and return (instance, raw_key). Raw key is shown once."""
        raw_key = secrets.token_urlsafe(32)
        prefix = raw_key[:12]
        instance = cls.objects.create(
            user=user,
            name=name,
            prefix=prefix,
            hashed_key=_hash_key(raw_key),
            expires_at=expires_at,
        )
        return instance, raw_key

    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True

    @classmethod
    def lookup(cls, raw_key: str):
        """Return a valid APIKey for the raw key, or None."""
        if not raw_key:
            return None
        candidate = _hash_key(raw_key)
        # Constant-time compare against stored hashes. Prefix narrows the set
        # but is not trusted on its own.
        for key in cls.objects.filter(prefix=raw_key[:12]).select_related("user"):
            if hmac.compare_digest(key.hashed_key, candidate) and key.is_valid():
                return key
        return None