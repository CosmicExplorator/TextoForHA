FROM python:3.13-alpine3.22
ARG BUILD_VERSION=0.1.0
LABEL io.hass.name="TextoForHA" \
      io.hass.description="Multi-modem SMS and network console" \
      io.hass.type="addon" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="amd64|aarch64"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN apk add --no-cache libstdc++ \
    && apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps
COPY app /app/app
CMD ["python", "-m", "app.server"]
