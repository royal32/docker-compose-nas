FROM python:3.13-alpine

RUN apk add --no-cache avahi avahi-tools bash curl dbus docker-cli docker-cli-compose iproute2 openssl

WORKDIR /stack

CMD ["/bin/bash", "/stack/compose-setup.sh"]
