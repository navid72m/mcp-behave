# strace is Linux-only, so even on macOS the spike runs in this container.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends strace \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Run inside the repo so planted canaries in ./sandbox_home are used as $HOME.
ENTRYPOINT ["bash", "run.sh"]
