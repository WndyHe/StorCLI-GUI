# StorCLI GUI v1.5.9

This update adds live background-operation progress to the overview dashboard.

## Highlights

- Added separate progress bars for virtual-drive and physical-drive operations.
- Added a scoped 10-second refresh while the overview or details window is
  visible.
- Added MSM-style BBU/CacheVault summary and advanced-property windows with
  health, temperature, capacitance, charging, manufacturing and learning data.
- Added an MSM-style **更多详情** window with operation target, progress,
  status, estimated time remaining and drive/array details.
- Added progress lookup for initialization, RAID migration, BGI, consistency
  check, rebuild, copyback, patrol read and erase operations.
- Active operations without a reported percentage show an indeterminate
  animation instead of a misleading fixed value.
- Progress requests are issued only for operations detected as active.
- Empty progress bars are hidden while no background operation is active.
- Controller context-menu hazards are marked in red, read-only query results are
  displayed directly, BBU/CacheVault queries use fallback detection, and the
  invalid rescan command was replaced by controller re-detection.
- Removed per-hover menu reconfiguration that caused right-click menus to jitter
  while moving between entries.
- Firmware build date now follows current controller data and uses the latest
  term-log record matching the active firmware version as a fallback.
- Term logs are rejected when their controller header does not match the
  selected controller, and stale queued tab queries are discarded while
  switching controllers.
- Firmware-date parsing now supports additional date formats and version fields
  used by secondary/newer controllers.
- Controllers that do not expose a build date through StorCLI now display
  `StorCLI 未提供`; the application does not invent or infer a date.
- CacheVault TMM/SCAP component fields are localized.
- Fixed the startup `DataTab object has no attribute _rd` regression introduced
  while refreshing the firmware build date.

Official Windows builds use Python 3.15 and Tk 9.0.

See the [complete changelog](https://github.com/WndyHe/StorCLI-GUI/blob/main/CHANGELOG.md)
for earlier releases and detailed changes.

## Requirements

- A supported Windows x64 system
- Administrator privileges
- A compatible Broadcom `storcli64.exe` supplied separately

This release does not include Broadcom StorCLI or redistribute
`storcli64.exe`.

SHA256: `BAD09121F0E84ED70F02B4B31BA42ACD10CDFFCECBA8B24BAEE200FC79ACF96C`
