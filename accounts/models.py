from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.permissions import ALL_PERMISSIONS, PERMISSION_LABELS, Role, role_permissions


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Custom user: e-mail login, one primary role, account status fields."""

    username = None
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.INSTRUCTOR, db_index=True)
    rank = models.CharField(max_length=50, blank=True)
    service_number = models.CharField(max_length=30, blank=True, null=True, unique=True)
    phone = models.CharField(max_length=30, blank=True)

    is_suspended = models.BooleanField(default=False)
    suspended_reason = models.CharField(max_length=255, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self):
        return f"{self.get_full_name() or self.email}"

    @property
    def display_name(self):
        name = self.get_full_name() or self.email
        return f"{self.rank} {name}".strip()

    @property
    def can_sign_in(self) -> bool:
        return self.is_active and not self.is_suspended

    # -- permission helpers ------------------------------------------------
    def effective_permissions(self) -> frozenset[str]:
        if not self.is_authenticated or not self.can_sign_in:
            return frozenset()
        cache = getattr(self, "_ocms_perm_cache", None)
        if cache is None:
            granted = set(
                self.permission_grants.active().values_list("permission", flat=True)
            )
            cache = frozenset(role_permissions(self.role) | granted)
            self._ocms_perm_cache = cache
        return cache

    def has_ocms_perm(self, code: str) -> bool:
        return code in self.effective_permissions()


class PermissionGrantQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        return self.filter(revoked_at__isnull=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


class PermissionGrant(models.Model):
    """An explicit, auditable extra permission granted to one user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="permission_grants")
    permission = models.CharField(max_length=50, choices=[(p, PERMISSION_LABELS[p]) for p in ALL_PERMISSIONS])
    reason = models.CharField(max_length=255)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    objects = PermissionGrantQuerySet.as_manager()

    class Meta:
        ordering = ["-granted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "permission"],
                condition=Q(revoked_at__isnull=True),
                name="unique_active_permission_grant",
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.permission}"

    @property
    def is_active(self):
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())


class LoginAttempt(models.Model):
    """Used for login throttling. Never stores passwords."""

    email = models.CharField(max_length=254, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "created_at"]), models.Index(fields=["ip_address", "created_at"])]
