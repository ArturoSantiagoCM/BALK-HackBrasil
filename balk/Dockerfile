# API a partir da imagem oficial do QGIS (sem Docker dentro de Docker): a API roda
# `python3 app/engine/run_chain.py` como subprocesso. Confirme a tag LTR no Docker Hub (qgis/qgis).
# STATUS: não construída nesta máquina (sem Docker). Para só rodar o MVP, use o Python local (README).
FROM qgis/qgis:ltr
ENV QT_QPA_PLATFORM=offscreen PYTHONUNBUFFERED=1 ENGINE=qgis
WORKDIR /srv/balk
COPY requirements.txt .
# rasterio/numpy/pyproj já podem vir na imagem; o resto instala aqui (Debian recente exige --break-system-packages)
RUN apt-get update && apt-get install -y --no-install-recommends python3-pip && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
