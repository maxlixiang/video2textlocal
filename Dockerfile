FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LANG=C.UTF-8
RUN useradd --uid 1000 --create-home app
WORKDIR /app
RUN install -d -o app -g app /results /media /models /database
USER app

FROM base AS manager
COPY v2t /app/v2t
COPY config /app/config
COPY tests /app/tests
COPY build_tools /app/build_tools
CMD ["python", "-m", "v2t.manager"]

FROM denoland/deno:bin-2.5.6@sha256:2f5f9d651af33c337767c423a340f76df35e35ff8ff4734210237b9c6fed94c7 AS deno
FROM base AS download
USER root
COPY --from=deno /deno /usr/local/bin/deno
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates
COPY requirements-download.txt /app/requirements-download.txt
COPY requirements-download.lock /app/requirements-download.lock
RUN pip install --no-cache-dir -r requirements-download.txt -c requirements-download.lock && pip check
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN python -m playwright install --with-deps chromium && chmod -R a+rX /opt/playwright
COPY v2t /app/v2t
COPY config /app/config
COPY tests /app/tests
COPY build_tools /app/build_tools
USER app
ENV SERVICE_ROLE=download
CMD ["python", "-m", "v2t.service"]
