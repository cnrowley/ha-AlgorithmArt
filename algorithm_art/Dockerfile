ARG BUILD_FROM=ghcr.io/home-assistant/base:latest

# ------------------------------------------------------------------
# Build Go binaries
# ------------------------------------------------------------------
FROM golang:1.25-alpine AS builder

WORKDIR /build/dla
COPY src/dla/ ./
RUN go build -o /out/dla.x .

WORKDIR /build/fractal
COPY src/fractal/ ./
RUN go build -o /out/fractal.x .

WORKDIR /build/moire
COPY src/moire/ ./
RUN go build -o /out/moire.x .


WORKDIR /build/goban
COPY src/goban/ ./
RUN go mod download && go build -o /out/goban.x .

WORKDIR /build/chess
COPY src/chess/ ./
RUN go mod download && go build -o /out/chess2bmp.x .

# ------------------------------------------------------------------
# Runtime image
# ------------------------------------------------------------------
FROM ${BUILD_FROM}

# Install Python and runtime deps
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates

RUN pip3 install --no-cache-dir --break-system-packages flask requests

# Go binaries built above
COPY --from=builder /out/dla.x        /usr/local/bin/dla.x
COPY --from=builder /out/fractal.x /usr/local/bin/fractal.x
COPY --from=builder /out/goban.x      /usr/local/bin/goban.x
COPY --from=builder /out/moire.x      /usr/local/bin/moire.x
COPY --from=builder /out/chess2bmp.x  /usr/local/bin/chess2bmp.x

RUN chmod +x \
    /usr/local/bin/dla.x \
    /usr/local/bin/fractal.x \
    /usr/local/bin/goban.x \
    /usr/local/bin/moire.x \
    /usr/local/bin/chess2bmp.x

# Flask app and supporting modules
WORKDIR /app
COPY main.py          /app/main.py
COPY art_generator.py /app/art_generator.py
COPY goban_state.py   /app/goban_state.py
COPY chess_state.py   /app/chess_state.py
COPY scheduler.py     /app/scheduler.py
COPY web_ui.py        /app/web_ui.py
COPy sgf_directory.py /app/sgf_directory.py
COPY const.py /app/const.py
COPY coordinator.py /app/coordinator.py
COPY main.py /app/main.py
COPY services.py /app/services.py

# SGF game library
COPY data/go_sgf /app/go_sgf

# PGN game library (used by the "library" chess_source — see chess_state.py)
COPY data/chess_pgn /app/chess_pgn

# Bundled chess piece SVGs (Cburnett set — see data/chess_svg/ATTRIBUTION.md).
# This is what -piece-style svg / chess_svg_dir points at by default.
COPY data/chess_svg /app/chess_svg

COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8765

CMD ["/run.sh"]
