FROM python:3.12-alpine
WORKDIR /app
COPY server.py .
ENV DATA_DIR=/data
ENV PORT=8000
EXPOSE 8000
CMD ["python3", "server.py"]
