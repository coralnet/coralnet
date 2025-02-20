# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.10.16
FROM python:${PYTHON_VERSION}-slim as base

RUN apt-get update -y && apt-get install -y \
    git \
 && rm -rf /var/lib/apt/lists/*

# Prevent Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keep Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-privileged user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --no-create-home \
    --shell "/sbin/nologin" \
    --uid "${UID}" \
    mainuser

# Download dependencies as a separate step to take advantage of Docker's caching.
# Leverage a cache mount to /root/.cache/pip to speed up subsequent builds.
# Leverage a bind mount to requirements.txt to avoid having to copy them into
# into this layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements/,target=requirements/ \
    python -m pip install -r requirements/local.txt

# Switch to the non-privileged user.
USER mainuser

# Copy the source code into the container.
COPY . .

# Expose the port that the application listens on.
EXPOSE 8000

# Run the application.
CMD python project/manage.py runserver 0.0.0.0:8000
