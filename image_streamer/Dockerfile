ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install Python + deps (Alpine-based base image)
RUN apk add --no-cache python3 py3-pip

# Install Python libraries for image generation + web serving
RUN pip3 install --no-cache-dir pillow numpy flask

COPY run.sh /run.sh
RUN chmod a+x /run.sh

COPY app /app

CMD [ "/run.sh" ]
