ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install build and runtime dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates \
    go \
    git \
    build-base

RUN pip3 install --no-cache-dir --break-system-packages \
    flask \
    requests

# ------------------------------------------------------------------
# Build Go generators
# ------------------------------------------------------------------

# DLA
COPY src/dla /tmp/src/dla
RUN cd /tmp/src/dla && \
    go build -o /usr/local/bin/dla.x

# Fractal
COPY src/fractal /tmp/src/fractal
RUN cd /tmp/src/fractal && \
    go build -o /usr/local/bin/fractalgen.x

# Goban
COPY src/goban /tmp/src/goban
RUN cd /tmp/src/goban && \
    go build -o /usr/local/bin/goban.x

RUN chmod +x \
    /usr/local/bin/dla.x \
    /usr/local/bin/fractalgen.x \
    /usr/local/bin/goban.x

# ------------------------------------------------------------------
# Python application
# ------------------------------------------------------------------

WORKDIR /app

COPY main.py          /app/main.py
COPY art_generator.py /app/art_generator.py
COPY goban_state.py   /app/goban_state.py
COPY web_ui.py        /app/web_ui.py

# ------------------------------------------------------------------
# SGF library
# ------------------------------------------------------------------

COPY data/go_sgf /data/go_sgf

# ------------------------------------------------------------------
# Startup
# ------------------------------------------------------------------

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8765

CMD ["/run.sh"]
