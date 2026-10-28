"""Redirects must not move local state or authorization to another origin."""
from urllib.request import HTTPRedirectHandler, Request


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: object, code: int,
                         msg: str, headers: object, newurl: str) -> None:
        return None
