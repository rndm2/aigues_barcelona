"""Constants definition."""

DOMAIN = "aigues_barcelona"

CONF_CONTRACT = "contract"
CONF_VALUE = "value"
CONF_2CAPTCHA_APIKEY = "twocaptcha_api_key"
CONF_SHOULD_IMPORT_HISTORY = "should_import_history"
CONF_HISTORY_DAYS = "history_days"

ATTR_LAST_MEASURE = "Last measure"

DEFAULT_SCAN_PERIOD = 3600 + 300
CONF_SCAN_PERIOD = "scan_period"
MIN_SCAN_PERIOD = 15 * 60
MAX_SCAN_PERIOD = 24 * 60 * 60

HISTORY_DAYS_DEFAULT = 365 * 5

API_HOST = "api.aiguesdebarcelona.cat"
API_COOKIE_TOKEN = "ofexTokenJwt"

API_ERROR_TOKEN_REVOKED = "JWT Token Revoked"

RECAPTCHA_V2_PAGEURL = "https://www.aiguesdebarcelona.cat/es/area-clientes#/login"
RECAPTCHA_V2_SITEKEY = "6LfPoasUAAAAAL5M1txzF5PJ91udHgE5PMm0JWWS"
