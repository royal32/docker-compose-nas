FROM python:3.13-alpine

RUN apk add --no-cache bash curl docker-cli docker-cli-compose

WORKDIR /stack

CMD ["/bin/bash", "/stack/compose-setup.sh"]
