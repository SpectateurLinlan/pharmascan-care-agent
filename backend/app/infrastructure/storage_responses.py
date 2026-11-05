"""Normalize only explicit object-absence responses from private Storage."""

import httpx


def object_is_absent(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True
    if response.status_code != 400:
        return False
    try:
        error = response.json()
    except ValueError:
        return False
    return (isinstance(error, dict) and str(error.get("statusCode")) == "404"
            and error.get("code") == "NoSuchKey")
