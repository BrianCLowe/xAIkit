# Changelog

All notable changes to xaikit-py. Newest entry on top.

## Unreleased

### Added

- Non-default `base_url` hosts restrict best and economy to that host's `GET /v1/models` list (fetched once per client, roles from the static catalog). An unpinned role with no listed model raises `RoleUnavailableOnHost` before the request. A failed model list warns and uses the static catalog, still on the configured host. The default host is unchanged.
- The usage meter applies the documented 10% US endpoint token premium on `us.api.x.ai` to input, cached input, output, and image input tokens. The rate is one hardcoded host table. Server `cost_in_usd_ticks` stay unchanged. Other hosts and per-unit fees stay at the base price.

## 0.3.0

Best-model picks change in this release. If you rely on `best` or `economy` model selection, review the ranking notes below.

### Changed

- Best-model ranking: snapshot-dated ids now rank behind the plain id and `-latest` alias for both `best` and `economy`. Undotted `grok-4` and `grok-5` date suffixes are no longer parsed as a minor version. (#90)
- Best-model ranking: `-lite` models rank last for `best` in every role unless a lite model is the only option. The extend, edit, and r2v extras are offered only on the unversioned `grok-imagine-video`. (#91)
- Best-model ranking: stable models rank ahead of preview models for `best` (XK-AC-RANK-4..6). (#89)
- Best-model ranking: plain Imagine Video 1.5 ranks above its snapshots, and transcribe ids are kept off voice. (#87)

### Fixed

- Imagine image generation returns every image when `n` is greater than 1, and usage metering counts the images actually returned. (#88)

### Dependencies

- Bump multidict from 6.7.1 to 6.9.1. (#86)
