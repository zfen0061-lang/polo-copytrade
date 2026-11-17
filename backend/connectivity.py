"""Narrow public-browser connectivity classification; never relax access guards."""
import re
import urllib.error


_NETWORK_CODES={
    'ERR_FAILED','ERR_INTERNET_DISCONNECTED','ERR_NETWORK_CHANGED',
    'ERR_CONNECTION_CLOSED','ERR_CONNECTION_RESET','ERR_CONNECTION_REFUSED',
    'ERR_CONNECTION_ABORTED','ERR_CONNECTION_TIMED_OUT','ERR_TIMED_OUT',
    'ERR_ADDRESS_UNREACHABLE','ERR_NAME_NOT_RESOLVED','ERR_DNS_TIMED_OUT',
}


def browser_network_failure(error):
    # Also accepts the sanitized historical error stored by the supervisor.
    # Match only navigation/network failures, never page content, HTTP 403/429,
    # certificates, authentication, history gaps or parser failures.
    message=str(error)
    code=re.search(r'\bnet::(ERR_[A-Z_]+)\b',message)
    return bool('Page.goto:' in message and code and code.group(1) in _NETWORK_CODES)


def transient_collector_failure(error):
    return (isinstance(error,(TimeoutError,ConnectionError,urllib.error.URLError))
            or type(error).__name__=='TimeoutError' or browser_network_failure(error))
