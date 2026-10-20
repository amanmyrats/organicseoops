FROM python:3.13.15-alpine3.24@sha256:1a63a53928ce53d2b0baf08092a703f4840ac5dfbd61fd48802dbf48e08c801e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN python -m pip uninstall --yes pip \
    && addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app app
WORKDIR /app
COPY --chown=10001:10001 analyze.py /app/analyze.py
USER 10001:10001
CMD ["python", "-I", "/app/analyze.py"]
