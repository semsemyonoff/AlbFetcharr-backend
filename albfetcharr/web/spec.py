"""SpecTree singleton for AlbFetcharr API documentation and request validation."""

from spectree import SpecTree

# mode="strict": only routes decorated by this instance appear in the spec.
# openapi_version pinned explicitly — sources disagree on the default for 2.0.1.
api = SpecTree(
    "flask",
    title="AlbFetcharr API",
    version="0.0.1",
    mode="strict",
    openapi_version="3.1.0",
)
