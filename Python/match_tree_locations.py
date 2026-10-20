import argparse
import csv
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

try:
    from scipy.spatial import cKDTree
except Exception:
    cKDTree = None


DEFAULT_BUFFER = 1.5
DEFAULT_BOTTOM_PERCENT = 5.0
DEFAULT_METHOD = "median"
DEFAULT_MIN_HEIGHT = 8.0


PLY_NUMPY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


def read_ply_header(ply_file):
    """Read PLY header and return format, vertex count, properties, and data offset."""
    properties = []
    vertex_count = None
    ply_format = None
    current_element = None

    with open(ply_file, "rb") as f:
        first = f.readline().decode("ascii", errors="replace").strip()
        if first != "ply":
            raise ValueError("No parece ser un archivo PLY")

        while True:
            line_bytes = f.readline()
            if not line_bytes:
                raise ValueError("Header PLY incompleto: falta end_header")

            line = line_bytes.decode("ascii", errors="replace").strip()
            parts = line.split()

            if line == "end_header":
                return ply_format, vertex_count, properties, f.tell()

            if not parts or parts[0] == "comment":
                continue

            if parts[0] == "format" and len(parts) >= 2:
                ply_format = parts[1]
            elif parts[0] == "element" and len(parts) >= 3:
                current_element = parts[1]
                if current_element == "vertex":
                    vertex_count = int(parts[2])
            elif parts[0] == "property" and current_element == "vertex":
                if len(parts) >= 5 and parts[1] == "list":
                    raise ValueError("No se soportan propiedades tipo list en vertices PLY")
                if len(parts) >= 3:
                    properties.append((parts[2], parts[1]))


def build_vertex_dtype(properties, endian):
    dtype_fields = []
    for name, ply_type in properties:
        if ply_type not in PLY_NUMPY_TYPES:
            raise ValueError(f"Tipo PLY no soportado: {ply_type}")
        dtype_fields.append((name, endian + PLY_NUMPY_TYPES[ply_type]))
    return np.dtype(dtype_fields)


def read_ply_xyz(ply_file):
    """Read x, y, z arrays from an ASCII or binary PLY file."""
    ply_format, vertex_count, properties, data_offset = read_ply_header(ply_file)

    if ply_format is None:
        raise ValueError("El header no indica format")
    if vertex_count is None:
        raise ValueError("El header no indica element vertex")

    prop_names = [name for name, _ in properties]
    for required in ("x", "y", "z"):
        if required not in prop_names:
            raise ValueError(f"El PLY no contiene la propiedad {required}")

    if ply_format == "binary_little_endian":
        dtype = build_vertex_dtype(properties, "<")
        with open(ply_file, "rb") as f:
            f.seek(data_offset)
            vertices = np.fromfile(f, dtype=dtype, count=vertex_count)
        return vertices["x"], vertices["y"], vertices["z"]

    if ply_format == "binary_big_endian":
        dtype = build_vertex_dtype(properties, ">")
        with open(ply_file, "rb") as f:
            f.seek(data_offset)
            vertices = np.fromfile(f, dtype=dtype, count=vertex_count)
        return vertices["x"], vertices["y"], vertices["z"]

    if ply_format == "ascii":
        usecols = [prop_names.index("x"), prop_names.index("y"), prop_names.index("z")]
        data = np.loadtxt(ply_file, skiprows=count_header_lines(ply_file), max_rows=vertex_count, usecols=usecols)
        return data[:, 0], data[:, 1], data[:, 2]

    raise ValueError(f"Formato PLY no soportado: {ply_format}")


def count_header_lines(ply_file):
    with open(ply_file, "rb") as f:
        for idx, line in enumerate(f, start=1):
            if line.strip() == b"end_header":
                return idx
    raise ValueError("Header PLY incompleto: falta end_header")


def aggregate_xy(xs, ys, method):
    if method == "mean":
        return float(np.mean(xs)), float(np.mean(ys))
    if method == "min_z_point":
        return float(xs[0]), float(ys[0])
    return float(np.median(xs)), float(np.median(ys))


def get_ply_bottom_location(ply_file, bottom_percent, bottom_height, method):
    xs, ys, zs = read_ply_xyz(ply_file)
    if len(xs) == 0:
        raise ValueError("PLY sin vertices")

    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)

    valid = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(zs)
    xs, ys, zs = xs[valid], ys[valid], zs[valid]
    if len(xs) == 0:
        raise ValueError("PLY sin vertices validos")

    z_min = float(np.min(zs))
    z_max = float(np.max(zs))

    if method == "min_z_point":
        idx = int(np.argmin(zs))
        bottom_x, bottom_y = aggregate_xy(xs[[idx]], ys[[idx]], method)
        bottom_count = 1
    else:
        if bottom_height is not None:
            z_limit = z_min + bottom_height
        else:
            z_limit = float(np.percentile(zs, bottom_percent))

        mask = zs <= z_limit
        if not np.any(mask):
            idx = int(np.argmin(zs))
            mask = np.zeros(len(zs), dtype=bool)
            mask[idx] = True

        bottom_x, bottom_y = aggregate_xy(xs[mask], ys[mask], method)
        bottom_count = int(np.count_nonzero(mask))

    return {
        "ply_file": Path(ply_file).name,
        "ply_path": str(Path(ply_file)),
        "ply_x": bottom_x,
        "ply_y": bottom_y,
        "z_min": z_min,
        "z_max": z_max,
        "height_m": z_max - z_min,
        "point_count": int(len(xs)),
        "bottom_point_count": bottom_count,
    }


def read_shape_points(shape_file, id_column):
    gdf = gpd.read_file(shape_file)
    if id_column not in gdf.columns:
        available = ", ".join(gdf.columns)
        raise ValueError(f"La columna '{id_column}' no existe en el shape. Columnas: {available}")

    rows = []
    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type != "Point":
            geom = geom.centroid
        shape_x = float(geom.x)
        shape_y = float(geom.y)

        rows.append(
            {
                "shape_index": idx,
                "shape_id": row[id_column],
                "shape_x": shape_x,
                "shape_y": shape_y,
            }
        )
    return rows


def list_ply_files(ply_dir, pattern, recursive):
    root = Path(ply_dir)
    iterator = root.rglob(pattern) if recursive else root.glob(pattern)
    return sorted(path for path in iterator if path.is_file())


def extract_ply_locations(ply_files, bottom_percent, bottom_height, method):
    locations = []
    errors = []

    for idx, ply_file in enumerate(ply_files, start=1):
        try:
            locations.append(get_ply_bottom_location(ply_file, bottom_percent, bottom_height, method))
        except Exception as exc:
            errors.append({"ply_file": Path(ply_file).name, "ply_path": str(ply_file), "error": str(exc)})

        if idx % 100 == 0:
            print(f"  PLY procesados: {idx:,}/{len(ply_files):,}")

    return locations, errors


def match_nearest(shape_points, ply_locations, max_distance, unique=False):
    if not shape_points or not ply_locations:
        return []

    shape_xy = np.array([[row["shape_x"], row["shape_y"]] for row in shape_points], dtype=np.float64)
    ply_xy = np.array([[row["ply_x"], row["ply_y"]] for row in ply_locations], dtype=np.float64)

    if unique:
        return match_unique(shape_points, ply_locations, shape_xy, ply_xy, max_distance)

    if cKDTree is not None:
        tree = cKDTree(ply_xy)
        distances, indices = tree.query(shape_xy, k=1, distance_upper_bound=max_distance)
    else:
        distances = []
        indices = []
        for point in shape_xy:
            dist = np.sqrt(np.sum((ply_xy - point) ** 2, axis=1))
            idx = int(np.argmin(dist))
            distances.append(dist[idx])
            indices.append(idx if dist[idx] <= max_distance else len(ply_locations))
        distances = np.asarray(distances)
        indices = np.asarray(indices)

    matches = []
    for shape_row, distance, ply_idx in zip(shape_points, distances, indices):
        if np.isfinite(distance) and int(ply_idx) < len(ply_locations):
            ply_row = ply_locations[int(ply_idx)]
            matches.append(build_match_row(shape_row, ply_row, float(distance), True))
        else:
            matches.append(build_match_row(shape_row, None, None, False))
    return matches


def match_unique(shape_points, ply_locations, shape_xy, ply_xy, max_distance):
    pairs = []
    for shape_idx, shape_point in enumerate(shape_xy):
        dist = np.sqrt(np.sum((ply_xy - shape_point) ** 2, axis=1))
        candidate_indices = np.where(dist <= max_distance)[0]
        for ply_idx in candidate_indices:
            pairs.append((float(dist[ply_idx]), shape_idx, int(ply_idx)))

    pairs.sort(key=lambda item: item[0])
    used_shapes = set()
    used_plys = set()
    chosen = {}

    for distance, shape_idx, ply_idx in pairs:
        if shape_idx in used_shapes or ply_idx in used_plys:
            continue
        used_shapes.add(shape_idx)
        used_plys.add(ply_idx)
        chosen[shape_idx] = (ply_idx, distance)

    matches = []
    for shape_idx, shape_row in enumerate(shape_points):
        if shape_idx in chosen:
            ply_idx, distance = chosen[shape_idx]
            matches.append(build_match_row(shape_row, ply_locations[ply_idx], distance, True))
        else:
            matches.append(build_match_row(shape_row, None, None, False))
    return matches


def build_match_row(shape_row, ply_row, distance, matched):
    row = {
        "matched": matched,
        "shape_index": shape_row["shape_index"],
        "shape_id": shape_row["shape_id"],
        "shape_x": shape_row["shape_x"],
        "shape_y": shape_row["shape_y"],
        "ply_file": "",
        "ply_path": "",
        "ply_x": "",
        "ply_y": "",
        "distance_m": "",
        "ply_z_min": "",
        "ply_z_max": "",
        "ply_height_m": "",
        "ply_point_count": "",
        "ply_bottom_point_count": "",
    }

    if ply_row is not None:
        row.update(
            {
                "ply_file": ply_row["ply_file"],
                "ply_path": ply_row["ply_path"],
                "ply_x": ply_row["ply_x"],
                "ply_y": ply_row["ply_y"],
                "distance_m": distance,
                "ply_z_min": ply_row["z_min"],
                "ply_z_max": ply_row["z_max"],
                "ply_height_m": ply_row["height_m"],
                "ply_point_count": ply_row["point_count"],
                "ply_bottom_point_count": ply_row["bottom_point_count"],
            }
        )
    return row


def filter_ply_by_height(ply_locations, min_height):
    kept = []
    skipped = []
    for row in ply_locations:
        if row["height_m"] >= min_height:
            kept.append(row)
        else:
            skipped.append(row)
    return kept, skipped


def write_csv(output_file, rows):
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Relaciona puntos de un shapefile con nubes PLY segun posicion XY.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:

  python match_tree_locations.py --shape Data/Match_qgis_trees/AMA_stemtag_pos_TLS.shp --id-column StemTag --ply-dir Data/Match_qgis_trees/Trees_ply --output Data/Match_qgis_trees/match_stemtag_ply.csv

  python match_tree_locations.py --shape puntos.shp --id-column StemTag --ply-dir Trees_ply --buffer 1.5 --min-height 10 --bottom-percent 3 --method median --unique

Notas:
  - El buffer esta en las mismas unidades del sistema de coordenadas del shape y los PLY.
  - Para coordenadas proyectadas en metros, --buffer 1 equivale a 1 m.
  - La posicion del shape se toma siempre desde la geometria de cada punto.
  - La ubicacion del PLY se calcula con los puntos de menor Z, pensando en la base del tallo.
  - Los PLY con altura menor que --min-height se omiten antes del matching.
        """,
    )
    parser.add_argument("--shape", required=True, help="Archivo shapefile de puntos")
    parser.add_argument("--id-column", required=True, help="Columna del shape que identifica el arbol")
    parser.add_argument("--ply-dir", required=True, help="Carpeta con archivos PLY")
    parser.add_argument("--output", required=True, help="CSV de salida con las relaciones encontradas")
    parser.add_argument("--buffer", type=float, default=DEFAULT_BUFFER, help=f"Distancia maxima de match (default: {DEFAULT_BUFFER})")
    parser.add_argument("--pattern", default="*.ply", help="Patron de archivos PLY (default: *.ply)")
    parser.add_argument("--recursive", action="store_true", help="Buscar PLY dentro de subcarpetas")
    parser.add_argument("--unique", action="store_true", help="Forzar match uno-a-uno entre shape y PLY")
    parser.add_argument("--min-height", type=float, default=DEFAULT_MIN_HEIGHT, help=f"Altura minima del PLY para entrar al matching (default: {DEFAULT_MIN_HEIGHT})")
    parser.add_argument("--bottom-percent", type=float, default=DEFAULT_BOTTOM_PERCENT, help=f"Porcentaje inferior en Z usado para estimar XY (default: {DEFAULT_BOTTOM_PERCENT})")
    parser.add_argument("--bottom-height", type=float, help="Altura sobre z_min usada para estimar XY; reemplaza --bottom-percent")
    parser.add_argument("--method", choices=("median", "mean", "min_z_point"), default=DEFAULT_METHOD, help=f"Metodo para resumir XY inferior (default: {DEFAULT_METHOD})")
    parser.add_argument("--ply-locations-output", help="CSV opcional con ubicaciones estimadas de cada PLY")
    parser.add_argument("--skipped-height-output", help="CSV opcional con PLY omitidos por altura")
    parser.add_argument("--errors-output", help="CSV opcional con PLY que no pudieron leerse")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.buffer <= 0:
        raise ValueError("--buffer debe ser mayor que 0")
    if args.min_height < 0:
        raise ValueError("--min-height debe ser mayor o igual que 0")
    if args.bottom_percent <= 0 or args.bottom_percent > 100:
        raise ValueError("--bottom-percent debe estar entre 0 y 100")
    if args.bottom_height is not None and args.bottom_height <= 0:
        raise ValueError("--bottom-height debe ser mayor que 0")

    print("Leyendo shapefile...")
    shape_points = read_shape_points(args.shape, args.id_column)
    print(f"  Puntos del shape: {len(shape_points):,}")

    print("Buscando archivos PLY...")
    ply_files = list_ply_files(args.ply_dir, args.pattern, args.recursive)
    if not ply_files:
        raise ValueError(f"No se encontraron PLY en {args.ply_dir} con patron {args.pattern}")
    print(f"  Archivos PLY: {len(ply_files):,}")

    print("Estimando ubicacion XY inferior de cada PLY...")
    ply_locations, errors = extract_ply_locations(
        ply_files,
        args.bottom_percent,
        args.bottom_height,
        args.method,
    )
    print(f"  PLY validos: {len(ply_locations):,}")
    if errors:
        print(f"  PLY con error: {len(errors):,}")

    matching_ply_locations, skipped_by_height = filter_ply_by_height(ply_locations, args.min_height)
    print(
        f"  PLY usados para matching: {len(matching_ply_locations):,} "
        f"(omitidos por altura < {args.min_height}: {len(skipped_by_height):,})"
    )

    if args.ply_locations_output:
        write_csv(args.ply_locations_output, ply_locations)
        print(f"Ubicaciones PLY guardadas en: {args.ply_locations_output}")

    if args.skipped_height_output and skipped_by_height:
        write_csv(args.skipped_height_output, skipped_by_height)
        print(f"PLY omitidos por altura guardados en: {args.skipped_height_output}")

    if args.errors_output and errors:
        write_csv(args.errors_output, errors)
        print(f"Errores guardados en: {args.errors_output}")

    print(f"Comparando ubicaciones con buffer de {args.buffer}...")
    matches = match_nearest(shape_points, matching_ply_locations, args.buffer, args.unique)
    write_csv(args.output, matches)

    matched_count = sum(1 for row in matches if row["matched"])
    print(f"Matches encontrados: {matched_count:,}/{len(matches):,}")
    print(f"Resultado guardado en: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)
