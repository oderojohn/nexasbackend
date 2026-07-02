import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed


TOKEN_SALT = "pos.api.auth"
DEFAULT_MAX_AGE = 60 * 60


def make_pos_token(user):
    return signing.dumps(
        {
            "user_id": user.pk,
            "auth_hash": user.get_session_auth_hash(),
        },
        salt=TOKEN_SALT,
        compress=True,
    )


def make_token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class POSBearerAuthentication(BaseAuthentication):
    keyword = b"Bearer"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth:
            return None
        if auth[0] != self.keyword:
            return None
        if len(auth) != 2:
            raise AuthenticationFailed("Invalid authorization header.")

        try:
            token = auth[1].decode("utf-8")
            payload = signing.loads(
                token,
                salt=TOKEN_SALT,
                max_age=getattr(settings, "POS_AUTH_TOKEN_MAX_AGE", DEFAULT_MAX_AGE),
            )
        except signing.SignatureExpired as exc:
            raise AuthenticationFailed("POS session expired.") from exc
        except signing.BadSignature as exc:
            raise AuthenticationFailed("Invalid POS session.") from exc

        from .models import BlacklistedToken
        if BlacklistedToken.is_blacklisted(make_token_hash(token)):
            raise AuthenticationFailed("POS session has been revoked.")

        user = get_user_model().objects.filter(pk=payload.get("user_id")).first()
        if not user or not user.is_active:
            raise AuthenticationFailed("User inactive or deleted.")
        profile = getattr(user, "pos_profile", None)
        if profile and not profile.is_active:
            raise AuthenticationFailed("POS profile inactive.")
        if payload.get("auth_hash") != user.get_session_auth_hash():
            raise AuthenticationFailed("POS session is no longer valid.")
        return (user, token)
