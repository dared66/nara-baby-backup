# Security and private data

Do not post credentials, exports or migration reports in public issues. If the repository enables private vulnerability reporting, use that channel. Otherwise contact the repository maintainer privately before sharing sensitive details.

The scripts do not save credentials or offer password arguments/environment variables. Credentials necessarily exist in process memory during authentication; reference clearing is not guaranteed memory erasure. Optional dependencies execute on your computer and must be trusted separately.

TLS verification remains enabled. Import writes require the explicit interactive IMPORT confirmation. Backups/reports contain private health and family information and are not encrypted by this project. Windows file access follows local folder permissions.

Please report unintended writes, unsafe retries, duplicate creation, incorrect units/timezones, or credential exposure. A release is not proof of exhaustive extraction or flawless third-party API behavior.
