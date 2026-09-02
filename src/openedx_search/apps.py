"""
openedx_search Django application initialization.
"""

from django.apps import AppConfig


class OpenEdxSearchConfig(AppConfig):
    """
    Django App Plugin configuration for Open edX platform integration.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "openedx_search"
