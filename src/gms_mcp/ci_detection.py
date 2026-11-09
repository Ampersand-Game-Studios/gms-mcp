from __future__ import annotations

import os
from typing import Mapping

# Boolean-style flags set by CI providers; an explicit false value means "not CI".
_CI_FLAG_KEYS = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI", "TRAVIS", "TF_BUILD")
# Providers that only expose identifying values rather than a boolean flag.
_CI_PRESENCE_KEYS = ("BUILD_BUILDID", "JENKINS_URL", "TEAMCITY_VERSION")
_FALSE_VALUES = {"", "0", "false", "no", "off"}


def is_ci_environment(env: Mapping[str, str] | None = None) -> bool:
    """Return True when the process appears to run under a CI system."""
    source = os.environ if env is None else env
    if any(source.get(key, "").strip().lower() not in _FALSE_VALUES for key in _CI_FLAG_KEYS):
        return True
    return any(source.get(key, "").strip() for key in _CI_PRESENCE_KEYS)
