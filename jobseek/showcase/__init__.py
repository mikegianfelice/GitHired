"""Public README showcase: top advertised Canada-eligible salaries."""

from jobseek.showcase.readme import (
    END_MARKER,
    START_MARKER,
    render_section,
    replace_section,
    update_readme_file,
)
from jobseek.showcase.refresh import refresh_readme
from jobseek.showcase.top_paying import (
    COMPARISON_RULE,
    DEFAULT_FX_USD_CAD,
    ShowcaseJob,
    select_top_paying_jobs,
    snapshot_payload,
)

__all__ = [
    "COMPARISON_RULE",
    "DEFAULT_FX_USD_CAD",
    "END_MARKER",
    "START_MARKER",
    "ShowcaseJob",
    "refresh_readme",
    "render_section",
    "replace_section",
    "select_top_paying_jobs",
    "snapshot_payload",
    "update_readme_file",
]
