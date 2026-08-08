"""
Django settings for the terminschleuder backend (local events / meetups).

Configuration is loaded from environment variables via django-environ.
Copy ``.env.example`` to ``.env`` and adjust the values.
"""

import environ
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Read .env into the environment.
env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "django-insecure-change-me"),
    ALLOWED_HOSTS=(list, []),
    # Default trusted origins are the production domain this project lives on,
    # so CSRF works out of the box even if the env var is unset on the server.
    # The ``https://*.terminschleuder.online`` wildcard (Django matches it via
    # ``is_same_domain``) covers the apex, www, and every subdomain over HTTPS.
    # Override via the environment for a different/staging domain.
    CSRF_TRUSTED_ORIGINS=(list, [
        "https://terminschleuder.online",
        "https://www.terminschleuder.online",
        "https://*.terminschleuder.online",
    ]),
    DATABASE_URL=(str, "postgis://terminschleuder:terminschleuder@127.0.0.1:5432/terminschleuder"),
)
environ.Env.read_env(BASE_DIR / ".env")

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
# Origins allowed to issue cross-origin unsafe requests (POST/PUT/DELETE) under
# CSRF. In production (DEBUG=False) Django checks the request ``Origin`` header
# against this list; a browser on https://www.example.com sending a login POST
# will be rejected unless https://www.example.com is listed here. Comma-separated,
# including the scheme. A ``https://*.example.com`` entry is a subdomain wildcard
# (matched via Django's ``is_same_domain``) covering the apex and all subdomains.
# The default (set in the Env schema above) already trusts terminschleuder.online,
# www, and *.terminschleuder.online — override here only for a different domain.
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',

    # Third-party
    'rest_framework',
    'django_filters',

    # Local
    'admin.apps.AdminConfig',  # backoffice (custom AdminSite); label "backoffice"
    'accounts',
    'events',
    'locations',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': env.db_url("DATABASE_URL"),
}


# Custom user model
AUTH_USER_MODEL = 'accounts.User'


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'


# Auth redirects — the backoffice (custom AdminSite) is mounted at "/".
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}


# Django REST Framework
# https://www.django-rest-framework.org/api-guide/settings/

REST_FRAMEWORK = {
    # JWT is first so DRF's get_authenticate_header() consults it for the
    # WWW-Authenticate value; without a header DRF coerces auth failures to
    # 403 instead of 401. Session stays available for the admin/browsable API
    # (it still authenticates via cookie regardless of list order).
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'accounts.authentication.APIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'config.pagination.StandardPagination',
    'PAGE_SIZE': 25,
}


# Simple JWT
# https://django-rest-framework-simplejwt.readthedocs.io/
# The signing key defaults to SECRET_KEY; set a separate DJANGO_JWT_SIGNING_KEY
# in the environment for production.

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer',),
}