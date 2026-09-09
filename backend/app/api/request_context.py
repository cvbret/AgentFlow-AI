"""Pure ASGI request scope, including unhandled-error responses."""
from uuid import uuid4
from app.observability import observation_context


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4()  # Never adopt an arbitrary client-supplied ID.
        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", str(request_id).encode("ascii"))]}
            await send(message)
        with observation_context(fresh=True, request_id=request_id):
            await self.app(scope, receive, send_with_id)
