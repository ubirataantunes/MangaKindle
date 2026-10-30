FROM python:3.12.14-slim-bookworm

ARG KCC_VERSION=v12.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git p7zip-full \
    && rm -rf /var/lib/apt/lists/*

# O KCC é instalado só com as dependências da linha de comando; a interface gráfica (PySide6) não é usada.
RUN git clone --depth 1 --branch ${KCC_VERSION} https://github.com/ciromattia/kcc.git /opt/kcc \
    && pip install --no-cache-dir Pillow==12.3.0 psutil==7.2.2 requests==2.34.2 python-slugify==8.0.4 \
        mozjpeg-lossless-optimization==1.3.2 natsort==8.4.0 numpy==2.5.4 packaging==26.3 PyMuPDF==1.28.2 \
    && printf '#!/bin/sh\nexec python /opt/kcc/kcc-c2e.py "$@"\n' > /usr/local/bin/kcc-c2e \
    && chmod +x /usr/local/bin/kcc-c2e

RUN groupadd --gid 1000 mangakindle \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin mangakindle \
    && mkdir /data \
    && chown mangakindle:mangakindle /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Com o sistema de arquivos somente leitura, o /tmp (tmpfs) é o único lugar gravável além do /data.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1

USER mangakindle
EXPOSE 8000
# --no-proxy-headers: o uvicorn não pode reescrever o IP do cliente com o X-Forwarded-For; quem decide é o client_ip().
CMD ["uvicorn", "main:app_with_security_headers", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
