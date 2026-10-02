FROM python:3.13-alpine3.22

# Créer un utilisateur non-root
RUN addgroup -S appuser && adduser -S appuser -G appuser
WORKDIR /app

# Installer les dépendances
COPY requirements.txt /app/requirements.txt
RUN apk add --no-cache libstdc++ \
    && apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev \
    && pip install --no-cache-dir --user -r requirements.txt \
    && apk del .build-deps

# Copier le code
COPY app /app/app

# Basculer sur l'utilisateur non-root
USER appuser

# Labels pour Home Assistant
LABEL io.hass.name="TextoForHA" \
      io.hass.description="Gère les SMS et le réseau des modems Huawei HiLink et AT" \
      io.hass.type="addon" \
      io.hass.version="0.1.0" \
      io.hass.arch="amd64|aarch64"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "app.server"]
