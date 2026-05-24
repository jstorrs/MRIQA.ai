"""Shared-password gate for the Streamlit UI.

Behaviour:
* If no password is configured in ``st.secrets``, the app stays open and
  shows a notice so the admin is never locked out during setup.
* If a password is configured, visitors must enter it once per session.
"""

from __future__ import annotations

import hmac

import streamlit as st


def _configured_password() -> str | None:
    """Return the shared password from Streamlit secrets, or None if unset."""
    try:
        return st.secrets.get("password")
    except (FileNotFoundError, AttributeError, KeyError):
        # No secrets file (local dev) or a missing key — treat as unset.
        return None


def check_password() -> bool:
    """Gate the app. Returns True when the user is authenticated (or no
    password is configured)."""
    configured = _configured_password()
    if not configured:
        st.caption(
            "🔓 Open access (no password set). To require a login on the deployed "
            "app, add a `password` secret in Streamlit Cloud — see DEPLOY.md."
        )
        return True

    if st.session_state.get("auth_ok", False):
        return True

    def _verify():
        entered = st.session_state.get("auth_pw", "")
        if hmac.compare_digest(str(entered), str(configured)):
            st.session_state["auth_ok"] = True
            st.session_state.pop("auth_pw", None)
        else:
            st.session_state["auth_ok"] = False

    st.markdown("#### Sign in")
    st.text_input("Password", type="password", key="auth_pw", on_change=_verify)
    if st.session_state.get("auth_ok") is False:
        st.error("Incorrect password. Please try again.")
    st.caption(
        "Access is restricted to pilot testers. Contact the app owner for the password. "
        "Please upload anonymized ACR phantom DICOMs only — no patient data."
    )
    return False
