ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install Python and runtime deps
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates

RUN pip3 install --no-cache-dir --break-system-packages flask requests

# ── Generator binaries ─────────────────────────────────────────────────────
# Each binary lives in its own subdirectory under bin/ in the repo.
# We copy just the executable (not the source or test output files).
COPY bin/dla/dla.x           /usr/local/bin/dla.x
COPY bin/fractal/fractalgen.x /usr/local/bin/fractalgen.x
COPY bin/goban/goban.x       /usr/local/bin/goban.x
RUN chmod +x \
    /usr/local/bin/dla.x \
    /usr/local/bin/fractalgen.x \
    /usr/local/bin/goban.x

# Flask app and supporting modules — flat in repo root
WORKDIR /app
COPY main.py           /app/main.py
COPY art_generator.py  /app/art_generator.py
COPY goban_state.py    /app/goban_state.py
COPY web_ui.py         /app/web_ui.py

# SGF game library — copied from data/go_sgf in the repo
# The directory will be at /data/go_sgf in the container
COPY data/go_sgf /data/go_sgf

COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8765

CMD ["/run.sh"]
