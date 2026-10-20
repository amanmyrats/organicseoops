FROM nginx:1.30.5-alpine-slim@sha256:32463212baf0e7d91aded2e9b843a4f2b9e017804b8c9d5bae7b51dcef64389c

RUN apk add --no-cache pcre2=10.49-r0 \
    && apk info --exists pcre2=10.49-r0 \
    && nginx -t
