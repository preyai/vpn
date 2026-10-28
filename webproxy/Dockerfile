# Telegram's WEB proxy relay (https://github.com/telegramdesktop/tproxy-server).
# Upstream publishes no image, so it is built from a pinned commit.
FROM golang:1.23-alpine AS build

ARG TPROXY_COMMIT=c8adb8b7c6b7fc46c12ae3acb68be9070c26a8e8

RUN apk add --no-cache git
RUN git clone https://github.com/telegramdesktop/tproxy-server.git /src \
    && git -C /src checkout "$TPROXY_COMMIT"
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath -o /tproxy-server ./cmd/tproxy-server


FROM alpine:3.20

COPY --from=build /tproxy-server /usr/local/bin/tproxy-server
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
