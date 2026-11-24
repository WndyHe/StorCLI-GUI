# Changelog

All notable changes to StorCLI GUI are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Versions 1.5.5 through 1.5.7 were local development iterations and were not
> published separately. Their changes are included in the v1.5.8 GitHub
> release.

## [Unreleased]

No unreleased changes.

## [1.5.10] - 2026-11-24

This maintenance release improves log searching and page action-state handling,
and adds the full license to the About window.

### Added

- The About window now displays the full Apache License 2.0 text and provides a
  button to copy the license.

### Changed

- Invalid page buttons are now disabled automatically when no controller is
  selected, data has not loaded, no row is selected, a mode cannot be toggled,
  or an exclusive operation is running.
- Removed the export button from the Physical Drives page.

### Fixed

- The event-log search field now filters TTY raw-log lines in place, including
  severity filtering and matching-line counts.

### Release

- Official Windows builds use Python 3.15 and Tk 9.0.
- Windows executable SHA256:
  `AFE4D7ED16828797E33B753616FF63A265FFB2F44B2D28808FEAB3482B12DC26`.
- Requires a supported Windows x64 system and administrator privileges.
- Requires a compatible Broadcom `storcli64.exe`, which is supplied separately;
  this release does not include or redistribute StorCLI.

## [1.5.9] - 2026-11-23

This update adds live background-operation progress to the overview dashboard,
MSM-style BBU/CacheVault information, and multi-controller refresh hardening.

### Added

- Live progress bars for virtual-drive and physical-drive background
  operations on the overview dashboard.
- A scoped 10-second refresh cycle that appears only while the overview or
  background-operation details window is visible.
- An MSM-style **更多详情** window with per-operation target, progress,
  status, estimated time remaining and drive/array details.
- MSM-style BBU/CacheVault summary window with type, health state, temperature,
  capacitance/charge and charging status.
- Advanced BBU/CacheVault property window with grouped manufacturing, runtime,
  capacity, learning and firmware-health information.
- StorCLI progress lookup for initialization, migration, BGI, consistency
  check, rebuild, copyback, patrol read and erase operations.
- Indeterminate progress animation when an operation is active but the
  controller does not yet expose a percentage.

### Changed

- Background-operation refresh queries progress only for operations detected as
  active, avoiding unnecessary StorCLI calls when the controller is idle.
- Completed and not-in-progress operations are removed from the active view.
- Empty progress bars are hidden when no background operation is active.
- Official Windows builds and release artifacts use Python 3.15 and Tk 9.0.

### Fixed

- Controller-sidebar context menus now mark foreign-configuration changes,
  controller firmware updates and full configuration deletion as dangerous.
- BBU queries fall back to CacheVault and show the result or both raw responses
  instead of only reporting a generic success.
- Read-only alarm, patrol-read and foreign-configuration queries now open their
  structured result window instead of discarding the returned values.
- The invalid `/call rescan` action was replaced by controller re-detection.
- Right-click menus are configured once when opened instead of reconfiguring
  their active item on every mouse movement, eliminating hover refresh jitter
  while preserving custom danger colors.
- BBU/CacheVault summary and advanced windows close automatically when the
  selected controller changes.
- Firmware build date is read from the current controller properties and
  `show all` output, and the previous cached value is cleared on every refresh.
- When the command output omits the date, firmware term log is matched against
  the current firmware version and the latest matching boot record is used.
- Firmware term logs are now accepted only when their controller header matches
  the selected controller, and stale queued tab queries are discarded when the
  user switches controllers.
- Multi-controller firmware-date parsing now handles `Mon DD, YYYY`,
  `MM/DD/YYYY` and `YYYY/MM/DD` variants and tries Firmware Version, Firmware
  Revision and Firmware Package Build candidates.
- When a controller does not expose a firmware build date through StorCLI JSON,
  `show all` or firmware term log, the version table now explicitly shows
  `StorCLI 未提供` instead of omitting the row or guessing a date.
- TMM and SCAP CacheVault module fields, including serial numbers,
  manufacturing dates, PCB assembly numbers, PCB versions and battery-pack
  assembly numbers, are localized.
- Fixed a startup regression where the firmware-date cache logic was invoked
  from `DataTab` and raised `DataTab object has no attribute _rd`.

### Release

- Windows executable SHA256:
  `BAD09121F0E84ED70F02B4B31BA42ACD10CDFFCECBA8B24BAEE200FC79ACF96C`.
- Requires a supported Windows x64 system and administrator privileges.
- Requires a compatible Broadcom `storcli64.exe`, which is supplied separately;
  this release does not include or redistribute StorCLI.

## [1.5.8] - 2026-11-23

### Added

- MSM-style **Modify Drive Group** workflow with separate RAID migration and
  capacity-expansion paths.
- RAID migration and member-drive addition using
  `storcli /cx/vx start migrate type=raidx [option=add drives=...]`.
- Current member-drive and addable Unconfigured Good drive lists.
- Dynamic RAID choices based on the combined count of current and newly selected
  member drives.
- RAID0, RAID1, RAID5, RAID6, RAID10, RAID50 and RAID60 eligibility checks.
- Estimated usable capacity and command previews before migration.
- Virtual-drive capacity expansion using
  `storcli /cx/vx expand Size=<MB> [expandarray]`, including capacity-range
  guidance from `storcli show expansion`.
- Long-running progress and per-step result tracking for migration and
  expansion operations.
- Controller status indicators in the sidebar:
  - green for Optimal/OK/Normal,
  - amber for Needs Attention/Warning/Degraded/rebuild states,
  - red for Failed/Critical/Offline/Missing/Error states.
- A risk-confirmation dialog before entering the Modify Drive Group workflow.

### Changed

- Consolidated the 1.5.5, 1.5.6 and 1.5.7 development iterations into the
  v1.5.8 release.
- Official Windows builds and release artifacts now use Python 3.15 and Tk 9.0.
- GitHub Actions static checks and Windows builds use Python 3.15.
- Controller and table rows keep their custom foreground color when selected.
- Menu items preserve custom red, green and other foreground colors while
  hovered, selected or keyboard-activated.

### Fixed

- Dangerous and status menu entries no longer turn black while hovered,
  selected or keyboard-activated.

## [1.5.7] - 2026-11-23

### Added

- Controller health color tags in the sidebar.
- Warning dialog before opening the Manage Drive Group workflow.

### Changed

- All explicit menu-item foreground colors are preserved during hover.
- Treeview selection no longer forces a single foreground color.

## [1.5.6] - 2026-11-23

### Added

- Two-page Modify Drive Group interface:
  - RAID migration and drive addition,
  - capacity-only expansion.
- Current disk-group member list and addable Unconfigured Good drive list.
- RAID recommendations based on the resulting member-drive count.
- Migration command preview and long-running task tracking.

## [1.5.5] - 2026-11-23

### Added

- Virtual drive expansion using
  `storcli /cx/vx expand Size=<MB> [expandarray]`.
- `storcli show expansion` capacity-range lookup.
- Expand-array capacity guidance and target-size validation.

## [1.5.4] - 2026-11-23

### Fixed

- Dangerous menu entries retain red text while hovered and selected.
- Nested danger submenus preserve their warning color.

## [1.5.3] - 2026-11-23

### Changed

- Dropdown and menu hover/selection backgrounds changed from system black to
  pale blue.
- Popup listboxes, context menus and top-level menus use consistent colors.

## [1.5.2] - 2026-11-22

### Fixed

- Restored the Capacity Usage canvas to the same light-gray background as its
  parent panel.

## [1.5.1] - 2026-11-22

### Fixed

- Reduced black first-frame flashing when restoring the application from a
  minimized state.
- Added explicit light backgrounds for text controls, tables, entries,
  comboboxes and canvases.
- Disabled DWM transition animations for the main window and forced redraw after
  restore.

## [1.5.0] - 2026-11-22

### Added

- Controller sub-tabs: Overview, Detailed Properties and Raw JSON.
- Search, state filters, sorting indicators, horizontal scrolling and CSV export
  for controller/VD/PD/enclosure tables.
- Context-sensitive VD/PD action-button availability.
- Persistent long-task progress window with per-step results.
- Structured event log with severity filtering, search and export.
- Automatic refresh interval in the status bar.
- Last-refresh timestamps.
- Compact non-administrator warning banner with expandable details.
- StorCLI path settings dialog.
- VD creation validation and capacity estimation.
- Global or disk-group-specific hot spare support.

### Changed

- Detailed properties now receive the full controller-page height.
- Refresh-all support and an explicit last-updated indicator were added.

## [1.4.2] - 2026-11-07

### Added

- Generic localization fallback for unknown controller fields.
- Camel-case, underscore and hyphen handling for newer controller JSON keys.
- Case-insensitive and separator-insensitive state-value translation.

### Changed

- Expanded exact translations for newer controller, BBU, CacheVault, NVMe,
  PCIe, PHY, OOB and Snapdump properties.

## [1.4.1] - 2026-11-07

### Fixed

- Long controller model names no longer overflow or clip against summary-card
  borders.

### Changed

- Controller summary cards use a two-row layout with model and resource cards
  spanning two columns.

## [1.4.0] - 2026-11-07

### Added

- Grouped System Overview on the Controller page.
- Basic information, firmware/driver, hardware/cache and resource/health groups.
- Health coloring for controller, BBU, CacheVault and memory-error values.

## [1.3.9] - 2026-11-07

### Changed

- Renamed the Array Card tab to Controller.
- Localized controller properties, groups and status values while retaining
  RAID, SAS, SATA, NVMe, BBU, CacheVault, PHY, TPM and related technical terms.

## [1.3.8] - 2026-11-06

### Added

- Dedicated Controller page.
- Controller summary cards, hierarchical properties, filtering, copy actions and
  raw JSON view.
- Controller switching protection for asynchronous responses.

## [1.3.7] - 2026-11-06

### Added

- Controller ID validation for asynchronous results.
- Dialog target-controller capture for VD creation and firmware updates.
- Global mutex for hazardous and long-running operations.
- Close and elevation guards while an operation is active.

### Fixed

- Stale controller responses could overwrite another controller's page data.
- Dangerous operations could be started concurrently or lost when closing the UI.

## [1.3.6] - 2026-08-25

### Baseline

- Initial packaged Windows GUI baseline.
- Controller discovery, overview dashboard, VD/PD/enclosure tables, event log,
  command console and firmware update workflows.

[Unreleased]: https://github.com/WndyHe/StorCLI-GUI/compare/v1.5.10...HEAD
[1.5.10]: https://github.com/WndyHe/StorCLI-GUI/releases/tag/v1.5.10
[1.5.9]: https://github.com/WndyHe/StorCLI-GUI/releases/tag/v1.5.9
[1.5.8]: https://github.com/WndyHe/StorCLI-GUI/releases/tag/v1.5.8
[1.5.4]: https://github.com/WndyHe/StorCLI-GUI/releases/tag/v1.5.4
[1.5.3]: https://github.com/WndyHe/StorCLI-GUI/releases/tag/v1.5.3
