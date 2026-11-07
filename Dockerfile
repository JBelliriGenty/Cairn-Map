# cairn-map server: Python standard library only, run as nobody.
#   docker build -t cairn-map . && docker run -p 8095:8095 -v ./config.json:/etc/cairn-map/config.json:ro cairn-map
FROM alpine:3.22
RUN apk add --no-cache python3
COPY cairn-map.py page.html /app/
COPY modules/ /app/modules/
ENV PYTHONDONTWRITEBYTECODE=1
USER nobody
ENTRYPOINT ["python3", "/app/cairn-map.py", "-c"]
CMD ["/etc/cairn-map/config.json"]
