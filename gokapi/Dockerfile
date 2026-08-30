FROM alpine:latest
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY bin/gokapi /app/gokapi
RUN mkdir -p /app/data /app/config
EXPOSE 53842
ENTRYPOINT ["/app/gokapi"]
