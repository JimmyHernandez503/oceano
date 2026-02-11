FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv git \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip

WORKDIR /app
COPY ./app/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

RUN mkdir -p /logs /state /data/thumbs /models

COPY ./app /app
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7860
ENTRYPOINT ["/entrypoint.sh"]
