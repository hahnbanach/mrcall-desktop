"""MrCall integration package.

Currently exposes only the legacy CLI OAuth2 PKCE flow (`oauth.py`) and
the Firebase-session StarChat client factory (`starchat_firebase.py`).

The original module docstring advertised a richer "configurator" toolset
(`variable_utils`, `llm_helper`, `config_tools`, `feature_context_tool`)
re-exported from this package. Those modules were never present in this
checkout — the upstream subtree merge brought in only `__init__.py` and
`oauth.py`. The matching trainer (`MrCallConfiguratorTrainer`) is
likewise absent, and every code path that would have consumed those
symbols already short-circuits at runtime with "MrCall is not
available." So those dead imports were stripped to make the package
import cleanly; do not re-add them without the corresponding modules.
"""
