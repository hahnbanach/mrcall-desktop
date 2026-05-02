"""Google integrations for the desktop sidecar.

Currently exposes the Calendar OAuth2 flow used by the Electron app's
"Connect Google Calendar" action. Lives in its own subpackage so future
Google services (Drive, Contacts, Gmail-via-API) can sit alongside
without touching the Calendar code.
"""
