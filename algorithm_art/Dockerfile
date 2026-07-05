ARG BUILD_FROM=ghcr.io/home-assistant/base:latest

# ------------------------------------------------------------------
# Build Go binaries
# ------------------------------------------------------------------
FROM golang:1.24-alpine AS builder

WORKDIR /build

COPY src/ ./src/

RUN go build -o /out/dla.x ./src/dla/dla.go
RUN go build -o /out/fractalgen.x ./src/fractal/fractalgen.go
RUN go mod download
RUN go build -o /out/goban.x ./src/goban/goban.go

# ------------------------------------------------------------------
# Runtime image
# ------------------------------------------------------------------
FROM ${BUILD_FROM}

# Install Python and runtime dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates

RUN pip3 install --no-cache-dir --break-system-packages \
    flask \
    requests

# Copy compiled generators from builder stage
COPY --from=builder /out/dla.x /usr/local/bin/dla.x
COPY --from=builder /out/fractalgen.x /usr/local/bin/fractalgen.x
COPY --from=builder /out/goban.x /usr/local/bin/goban.x

RUN chmod +x \
    /usr/local/bin/dla.x \
    /usr/local/bin/fractalgen.x \
    /usr/local/bin/goban.x

# Application files
COPY main.py /app/main.py
COPY art_generator.py /app/art_generator.py
COPY generative_art.py /app/generative_art.py
COPY services.py /app/services.py

COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app

EXPOSE 8765

CMD ["/run.sh"]
