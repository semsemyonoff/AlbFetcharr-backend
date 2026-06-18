"""SpecTree singleton for AlbFetcharr API documentation and request validation."""

from spectree import SpecTree

from albfetcharr.version import APP_VERSION

# mode="strict": only routes decorated by this instance appear in the spec.
# openapi_version pinned explicitly — sources disagree on the default for 2.0.1.
# version=APP_VERSION: the build-time service version is the OpenAPI info.version,
# the same value GET /api/version reports under "albfetcharr".
api = SpecTree(
    "flask",
    title="AlbFetcharr API",
    version=APP_VERSION,
    mode="strict",
    openapi_version="3.1.0",
)
