import httpx

API_BASE_URL = "https://api.addisassistant.com"
RETRIABLE_STATUS_CODES = {
    httpx.codes.REQUEST_TIMEOUT,
    httpx.codes.TOO_MANY_REQUESTS,
    httpx.codes.INTERNAL_SERVER_ERROR,
    httpx.codes.BAD_GATEWAY,
    httpx.codes.SERVICE_UNAVAILABLE,
    522,
    524,
}

