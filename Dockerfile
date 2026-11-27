# Imagem de produção: Python enxuto (os pacotes de raster vêm em wheels; NÃO precisa do QGIS para rodar o BALK).
# O motor QGIS é opcional e fica no Dockerfile.qgis. STATUS: NÃO construída nesta máquina (sem Docker).
# Teste: docker build -t balk . && docker run --env-file .env -p 8000:8000 balk
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 ENGINE=python BALK_ENV=production \
    BALK_DB=/srv/balk/data_store/balk.db BALK_WORK=/srv/balk/work MPLBACKEND=Agg
WORKDIR /srv/balk
RUN apt-get update && apt-get install -y --no-install-recommends curl libexpat1 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 10001 balk && mkdir -p /srv/balk/data_store /srv/balk/work && chown -R balk /srv/balk
COPY requirements.lock.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY --chown=balk . .
USER balk
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
# --no-access-log: o log do uvicorn gravaria os tokens de /r/, /h/ e /m/ (o app já faz o próprio log, sem token).
# Atrás de proxy, defina FORWARDED_ALLOW_IPS=<IP do proxy> para o uvicorn confiar no IP repassado; o BALK não lê X-Forwarded-For sozinho.
