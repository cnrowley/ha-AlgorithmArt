ARG BUILD_FROM=ghcr.io/home-assistant/base:latest

# ------------------------------------------------------------------
# Build Go binaries
# ------------------------------------------------------------------
FROM golang:1.24-alpine AS builder

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -o /out/dla.x ./bin/dla && \
    CGO_ENABLED=0 GOOS=linux go build -o /out/fractalgen.x ./bin/fractal && \
    CGO_ENABLED=0 GOOS=linux go build -o /out/goban.x ./bin/goban

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

# Copy compiled Go binaries
COPY --from=builder /out/dla.x /usr/local/bin/dla.x
COPY --from=builder /out/fractalgen.x /usr/local/bin/fractalgen.x
COPY --from=builder /out/goban.x /usr/local/bin/goban.x

RUN chmod +x \
    /usr/local/bin/dla.x \
    /usr/local/bin/fractalgen.x \
    /usr/local/bin/goban.x

# Flask app and supporting modules
WORKDIR /app
COPY main.py          /app/main.py
COPY art_generator.py /app/art_generator.py
COPY goban_state.py   /app/goban_state.py
COPY scheduler.py     /app/scheduler.py
COPY web_ui.py        /app/web_ui.py

# SGF game library
COPY data/go_sgf /data/go_sgf

COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8765

CMD ["/run.sh"]
