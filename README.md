# Scripts para flujos de trabajo TLS - Amacayacu

Colección de scripts en Python y R para procesar nubes de puntos TLS/LiDAR, segmentar árboles, relacionar árboles con archivos PLY y preparar datos geométricos.

## Contenido

```text
.
├── Python/
│   ├── match_tree_locations.py
│   ├── merge_ply_files.py
│   ├── ply_to_txt.py
│   └── split_las_streaming.py
└── R/
    ├── Camb_nomb_ply.R
    ├── findOverlappingHulls.R
    └── Prueba_arbor.R
```

## Requisitos

### Python

Se recomienda usar un entorno virtual. Desde PowerShell, en la carpeta del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install numpy geopandas scipy open3d "laspy[lazrs]"
```

Las dependencias varían según el script:

| Paquete | Uso |
|---|---|
| `numpy` | Operaciones con coordenadas y puntos |
| `geopandas` | Lectura de datos vectoriales para encontrar correspondencias |
| `scipy` | Búsqueda espacial acelerada en `match_tree_locations.py` (opcional; hay alternativa sin SciPy) |
| `open3d` | Conversión entre TXT y PLY |
| `laspy` | Lectura y escritura de archivos LAS/LAZ |
| `lazrs` | Backend de compresión LAZ para `laspy` |

### R

Se requieren los paquetes usados por cada script:

```r
install.packages(c("lidR", "Rvcg", "sf", "terra"))
install.packages(
  "arbor",
  repos = c("https://r-lidar.r-universe.dev", "https://cloud.r-project.org")
)
```

`Prueba_arbor.R` usa `lidR` y `arbor`; `findOverlappingHulls.R` usa `Rvcg`, `sf`, `terra` y `lidR`; `Camb_nomb_ply.R` solo usa funciones base de R.

## Scripts

### Python

#### `match_tree_locations.py`

Asocia puntos de un archivo vectorial (shapefile u otro formato que pueda leer GeoPandas) con archivos PLY según sus posiciones XY. Estima la ubicación XY de cada PLY a partir de sus puntos más bajos en Z, omite por defecto árboles con altura inferior a 8 m y escribe los resultados en un CSV.

Ejemplo:

```powershell
python .\Python\match_tree_locations.py `
  --shape "C:\datos\arboles.shp" `
  --id-column StemTag `
  --ply-dir "C:\datos\Trees_ply" `
  --output "C:\datos\matches.csv" `
  --buffer 1.5 `
  --min-height 8 `
  --method median `
  --unique `
  --ply-locations-output "C:\datos\ubicaciones_ply.csv" `
  --errors-output "C:\datos\errores_ply.csv"
```

Parámetros útiles:

- `--buffer`: distancia máxima para aceptar una correspondencia. El valor debe usar las mismas unidades que las coordenadas; si son metros, `1.5` equivale a 1,5 m.
- `--id-column`: columna del vector que identifica cada árbol.
- `--unique`: solicita una correspondencia uno-a-uno.
- `--bottom-percent` o `--bottom-height`: define cómo seleccionar los puntos bajos del PLY para estimar su ubicación.
- `--method`: resumen XY de los puntos bajos: `median`, `mean` o `min_z_point`.
- `--recursive`: busca PLY también en subcarpetas.
- `--skipped-height-output`: CSV opcional con PLY omitidos por altura.

El CSV principal incluye el identificador del árbol, el PLY asignado, la distancia y estadísticas de altura y puntos. Revise que los archivos PLY y el vector estén en el mismo sistema de coordenadas antes de comparar posiciones.

#### `merge_ply_files.py`

Combina los archivos `.ply` de una carpeta en una sola nube comprimida `.laz`. Acepta un número opcional de hilos de lectura.

```powershell
python .\Python\merge_ply_files.py `
  "C:\datos\segmentos_ply" `
  "C:\datos\segmentos_unidos.laz" `
  8
```

Si se omite el último argumento, el script calcula el número de hilos a partir de los núcleos disponibles. El archivo de salida contiene coordenadas y colores RGB; los puntos PLY que no incluyan color se escriben en blanco.

#### `ply_to_txt.py`

Convierte archivos TXT con al menos tres columnas XYZ a PLY binario, y archivos PLY a TXT con columnas XYZ. Admite archivos individuales o carpetas (no busca recursivamente en subcarpetas).

```powershell
# Convertir archivos de una carpeta
python .\Python\ply_to_txt.py --input-dir "C:\datos\entrada" --output-dir "C:\datos\convertidos"

# Convertir un archivo o una carpeta específica
python .\Python\ply_to_txt.py "C:\datos\arbol.ply" -o "C:\datos\txt"
python .\Python\ply_to_txt.py "C:\datos\txt" -o "C:\datos\ply"
```

La conversión TXT a PLY utiliza solo las primeras tres columnas y espera que representen X, Y y Z. Si no se especifica la entrada, el script usa las rutas predeterminadas codificadas en el propio archivo; es preferible pasar `--input-dir` y `--output-dir` explícitamente.

#### `split_las_streaming.py`

Divide archivos LAS/LAZ grandes por cuadrícula mediante lectura por bloques, permite recortes por caja delimitadora o a partir de un CSV, y puede mostrar los metadatos de una nube.

```powershell
# Dividir en celdas de 15 unidades (por ejemplo, metros)
python .\Python\split_las_streaming.py --input "C:\datos\nube.laz" --grid 15 --output "C:\datos\grid"

# Mostrar información
python .\Python\split_las_streaming.py --info "C:\datos\nube.laz"

# Recortes definidos en un CSV
python .\Python\split_las_streaming.py --input "C:\datos\nube.laz" --csv "C:\datos\recortes.csv" --output "C:\datos\recortes"
```

El CSV de recortes debe incluir `nombre`, `xmin`, `xmax`, `ymin` y `ymax`; `zmin` y `zmax` son opcionales. La opción `--bbox XMIN XMAX YMIN YMAX` también está presente en el script, pero su implementación requiere validación antes de usarla: actualmente intenta escribir puntos mediante una llamada que no corresponde a la API de `laspy`. Sin argumentos, el script intenta usar rutas predeterminadas específicas del entorno original.

### R

#### `Prueba_arbor.R`

Flujo de segmentación de una nube TLS con `lidR` y `arbor`: clasifica suelo, prepara el terreno, segmenta semánticamente, extrae instancias de árboles, colorea la nube y calcula modelos QSM.

Antes de ejecutarlo, adapte el `setwd()`, el nombre del LAZ de entrada y el `treeID` de ejemplo en el archivo. Ejecute desde R:

```powershell
Rscript .\R\Prueba_arbor.R
```

Genera `AMA_L25_arbor2.laz` y `qsm_arbor.ply` en el directorio de trabajo. Los parámetros y nombres de salida están definidos directamente en el script.

#### `findOverlappingHulls.R`

Calcula metadatos y envolventes cóncavas para archivos de segmentos `.ply` o `.las` del directorio de trabajo. Exporta los polígonos a GeoPackage y shapefile; luego permite localizar segmentos que intersectan la envolvente de un segmento focal y copiarlos o moverlos a una carpeta.

Antes de ejecutarlo:

1. Abra el archivo desde la carpeta que contiene los segmentos y configure `fileType` (`".ply"` o `".las"`) y `lidarCRS` con el formato y CRS correctos para los datos.
2. Ejecute inicialmente el bloque de creación de envolventes, que genera `segmentData.csv`, `segmentHulls.gpkg` y `segmentHulls.shp`.
3. Ajuste `segmentFile`, `bufferDist`, `newDirName` y `moveOrCopy` en el bloque de aplicación.
4. Ejecute el bloque de aplicación para guardar los segmentos relacionados en la carpeta configurada.

`moveOrCopy <- "move"` elimina los archivos originales tras copiarlos; use `"copy"` para conservarlos. Las salidas espaciales pueden reemplazar las versiones anteriores. Verifique siempre el CRS y la carpeta de trabajo antes de correr el script.

#### `Camb_nomb_ply.R`

Lee y combina tres CSV de correspondencias de palmas, conserva las filas marcadas como `matched == "True"` y copia cada PLY a una ruta de destino con el nombre indicado por `shape_id`.

Antes de ejecutarlo, adapte las rutas y los nombres de CSV (`match_stemtag_palms_*.csv`) en el script. Se esperan las columnas `matched`, `ply_file` y `shape_id`. La copia no sobrescribe archivos de destino existentes.

```powershell
Rscript .\R\Camb_nomb_ply.R
```

## Orden de trabajo sugerido

El orden depende del conjunto de datos. Una secuencia posible es:

1. Preparar o dividir nubes grandes con `split_las_streaming.py`.
2. Segmentar árboles y crear modelos QSM con `Prueba_arbor.R`.
3. Convertir formatos o unir segmentos con `ply_to_txt.py` y `merge_ply_files.py`, según se requiera.
4. Relacionar los PLY con identificadores del vector mediante `match_tree_locations.py`.
5. Renombrar/copiarlos con `Camb_nomb_ply.R` y analizar envolventes/intersecciones con `findOverlappingHulls.R`.

Los scripts son herramientas independientes, no un pipeline automatizado: las rutas, nombres de archivo, CRS, parámetros y directorios de entrada/salida deben configurarse para cada ejecución.

## Consideraciones

- Los scripts contienen rutas absolutas predeterminadas del entorno donde se desarrollaron. Pase rutas explícitas cuando la herramienta lo permita y edite las variables de configuración en los scripts R.
- Las unidades espaciales deben ser consistentes: distancias de buffers y tamaños de cuadrícula se interpretan en las unidades de las coordenadas.
- Mantenga copias de los datos originales antes de ejecutar operaciones de movimiento o sobrescritura.
- No se incluye un conjunto de datos de ejemplo ni pruebas automatizadas; valide los resultados con una muestra antes de procesar lotes completos.
