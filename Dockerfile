FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

COPY . /app
ENV UV_NO_DEV=1

WORKDIR /app
RUN uv sync --locked

CMD [ "uv", "run", "main.py" ]
