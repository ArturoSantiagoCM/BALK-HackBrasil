"""Cadeia PyQGIS: inicia o QGIS UMA vez e roda todos os algoritmos com processing.run.

Uso (dentro da imagem qgis/qgis, QT_QPA_PLATFORM=offscreen):
    python3 app/engine/run_chain.py work/<id> <lat> <lon>
Última linha da saída padrão = JSON com os campos de SpatialStats.

!!! STATUS: ESQUELETO NÃO TESTADO nesta máquina (sem Docker/QGIS no ambiente de desenvolvimento). !!!
Antes de usar, confirme cada ID e parâmetro com:  qgis_process list  e  qgis_process help <id>
(os códigos de STATISTICS do zonalstatisticsfb e o resampling do gdal:warp, em especial).
Rode o teste de equivalência (tests/test_equivalencia.py) contra o motor Python.
Este arquivo não importa nada do pacote app para rodar solto.
"""
import json
import sys
from pathlib import Path


def utm_epsg(lat, lon):
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def main(work, lat, lon, radius=150.0):
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
                           QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer, QgsVectorLayer)
    qgs = QgsApplication([], False)
    qgs.initQgis()
    sys.path.append("/usr/share/qgis/python/plugins")
    import processing
    from processing.core.Processing import Processing
    from qgis.analysis import QgsNativeAlgorithms
    Processing.initialize()
    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

    work = Path(work)
    red = QgsRasterLayer(str(work / "red.tif"))
    crs = red.crs()
    ext = red.extent()
    extent = f"{ext.xMinimum()},{ext.xMaximum()},{ext.yMinimum()},{ext.yMaximum()} [{crs.authid()}]"

    # 1) ponto em UTM (metros) e buffer de 150 m
    pt = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), crs, QgsProject.instance()
                                ).transform(QgsPointXY(lon, lat))
    lyr = QgsVectorLayer(f"Point?crs={crs.authid()}", "ponto", "memory")
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPointXY(pt))
    lyr.dataProvider().addFeatures([feat])
    aoi = processing.run("native:buffer", {"INPUT": lyr, "DISTANCE": radius, "SEGMENTS": 24,
                                           "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]

    # 2) SCL (20 m) e DEM para a grade de 10 m do vermelho
    def warp(name, out, resampling):
        processing.run("gdal:warp", {"INPUT": str(work / name), "TARGET_CRS": crs, "RESAMPLING": resampling,
                                     "TARGET_RESOLUTION": 10, "TARGET_EXTENT": extent,
                                     "OUTPUT": str(work / out)})
    warp("scl.tif", "q_scl10.tif", 0)  # 0 = vizinho mais próximo (conferir)
    warp("dem.tif", "q_dem_utm.tif", 1)  # 1 = bilinear (conferir)

    # 3) NDVI mascarado por SCL 4/5 e declividade em %
    processing.run("gdal:rastercalculator", {
        "INPUT_A": str(work / "red.tif"), "BAND_A": 1, "INPUT_B": str(work / "nir.tif"), "BAND_B": 1,
        "INPUT_C": str(work / "q_scl10.tif"), "BAND_C": 1,
        "FORMULA": "where(((C==4)+(C==5))>0, (B-A)/(B+A), -9999)", "NO_DATA": -9999,
        "RTYPE": 5, "OUTPUT": str(work / "q_ndvi.tif")})
    processing.run("gdal:slope", {"INPUT": str(work / "q_dem_utm.tif"), "BAND": 1, "AS_PERCENT": True,
                                  "OUTPUT": str(work / "q_slope.tif")})

    # 4) estatísticas por zona no círculo (o recorte é feito pela própria zona)
    def zonal(poly, raster, prefix):
        return processing.run("native:zonalstatisticsfb", {
            "INPUT": poly, "INPUT_RASTER": raster, "RASTER_BAND": 1, "COLUMN_PREFIX": prefix,
            "STATISTICS": [2, 4, 5, 6],  # média, desvio, mín, máx (conferir com qgis_process help)
            "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]
    z = zonal(aoi, str(work / "q_ndvi.tif"), "ndvi_")
    z = zonal(z, str(work / "q_slope.tif"), "slope_")
    z = zonal(z, str(work / "q_dem_utm.tif"), "dem_")
    f = next(z.getFeatures())

    # 5) argila no ponto (SoilGrids ~250 m: leitura pontual, não estatística por zona)
    clay = None
    clay_path = work / "clay.tif"
    if clay_path.exists():
        cl = QgsRasterLayer(str(clay_path))
        p2 = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), cl.crs(),
                                    QgsProject.instance()).transform(QgsPointXY(lon, lat))
        v, ok = cl.dataProvider().sample(p2, 1)
        clay = float(v) if ok else None

    st = processing.run("native:rasterlayerstatistics", {"INPUT": str(work / "q_ndvi.tif"), "BAND": 1})
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8")) if (work / "meta.json").exists() else {}
    out = {"ndvi_mean": f["ndvi_mean"], "ndvi_std": f["ndvi_stdev"], "slope_mean_pct": f["slope_mean"],
           "slope_max_pct": f["slope_max"], "elevation_m": f["dem_mean"], "clay_pct": clay,
           "area_ha": round(aoi.getFeature(1).geometry().area() / 10000.0, 2) if hasattr(aoi, "getFeature") else None,
           "scene_date": meta.get("scene_date"), "ndvi_ref_mean": st.get("MEAN"), "ndvi_ref_std": st.get("STD_DEV")}
    print(json.dumps(out))
    qgs.exitQgis()


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
