FROM python:3.13-alpine

LABEL org.label-schema.maintainer="Voxpupuli Team <info@voxpupuli.org>" \
      org.label-schema.vendor="Voxpupuli" \
      org.label-schema.url="https://github.com/voxpupuli/puppetboard" \
      org.label-schema.license="Apache-2.0" \
      org.label-schema.vcs-url="https://github.com/voxpupuli/puppetboard" \
      org.label-schema.schema-version="1.0" \
      org.label-schema.dockerfile="/Dockerfile"

ENV PUPPETBOARD_PORT=8088
ENV PUPPETBOARD_HOST=0.0.0.0
ENV PUPPETBOARD_STATUS_ENDPOINT=/status
ENV PUPPETBOARD_SETTINGS=docker_settings.py
EXPOSE 8088

HEALTHCHECK --interval=2m --timeout=10s --start-period=30s CMD python3 -c "import gevent.monkey; gevent.monkey.patch_all(); import requests; import sys; rc = 0 if requests.get('http://localhost:${PUPPETBOARD_PORT}${PUPPETBOARD_URL_PREFIX:-}${PUPPETBOARD_STATUS_ENDPOINT}').ok else 255; sys.exit(rc)"

RUN apk add --no-cache gcc libmemcached-dev libc-dev zlib-dev
RUN mkdir -p /usr/src/app/
WORKDIR /usr/src/app/
COPY . /usr/src/app
RUN pip install --no-cache-dir -r requirements-docker.txt .

COPY Dockerfile /

RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

CMD gunicorn -b ${PUPPETBOARD_HOST}:${PUPPETBOARD_PORT} --preload --workers="${PUPPETBOARD_WORKERS:-3}" --timeout=120 --worker-class=gevent -e SCRIPT_NAME="${PUPPETBOARD_URL_PREFIX:-}" --access-logfile=- puppetboard.app:app
