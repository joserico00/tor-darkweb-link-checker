# A minimal Tor SOCKS proxy.
#
# Built from the official Alpine image and Alpine's own tor package, so this
# does not depend on some third-party proxy image staying maintained. curl is
# here for the health check in docker-compose.yml, which only reports the
# container healthy once Tor has finished bootstrapping.
FROM alpine:3.20

RUN apk add --no-cache tor curl

COPY torrc /etc/tor/torrc

USER tor
EXPOSE 9050
ENTRYPOINT ["tor", "-f", "/etc/tor/torrc"]
