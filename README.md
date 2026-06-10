# Aigües de Barcelona para Home Assistant

Custom integration for importing water consumption data from Aigües de Barcelona into Home Assistant.

## What it exposes

- A water sensor per configured contract.
- Long-term statistics suitable for the Home Assistant Energy dashboard.
- Optional historical import.
- Manual service for importing historical data again if needed.

## Login and CAPTCHA

Aigües de Barcelona protects login with reCAPTCHA. This integration uses a 2Captcha API key to solve the challenge during login. The integration stores the returned `ofexTokenJwt` token in the Home Assistant config entry and refreshes it when needed.

## Configuration

Install the integration, then add it from Home Assistant:

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=aigues_barcelona)

You need:

- DNI/NIE username.
- Aigües de Barcelona password.
- 2Captcha API key.

## Options

After setup, open the integration options to configure:

- `should_import_history`: import historical data on next update.
- `history_days`: how many historical days to import.
- `scan_period`: polling interval in seconds. Default: `3900` seconds.

The default scan period is intentionally conservative to avoid hammering the external service.

## Services

### `aigues_barcelona.import_historical_data`

Imports historical data without clearing existing statistics.

Fields:

- `contract`: optional if only one contract is configured; required if multiple contracts exist.
- `history_days`: number of days to import. Default: `365`.

### `aigues_barcelona.reset_and_refresh_data`

Legacy alias kept for backward compatibility. It does **not** clear statistics; it imports historical data only.

## Notes about historical import

Historical import is deliberately conservative:

- It imports week by week.
- It retries failed weekly fetches up to five times.
- It skips already existing daily statistics to avoid duplicate data.
- After automatic startup import, the option is switched back to `false`.

## HACS

This repository is structured for HACS as a custom integration under `custom_components/aigues_barcelona`.

## License

GPL-3.0.
