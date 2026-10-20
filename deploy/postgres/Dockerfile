FROM postgres:18.6-alpine3.24@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873

# The official entrypoint supports nonroot initialization; no gosu is needed.
# Only new Alpine volumes or verified logical restores are supported (D056).
RUN rm /usr/local/bin/gosu
USER 70:70
