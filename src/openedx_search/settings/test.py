"""
Test settings for the openedx_search application.
"""

from openedx_search.settings.common import plugin_settings as common_settings


def plugin_settings(settings):
    """
    Set up test-specific settings.

    Args:
        settings (dict): Django settings object
    """

    # Apply common settings
    common_settings(settings)
