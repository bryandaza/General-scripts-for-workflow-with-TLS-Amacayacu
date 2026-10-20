import laspy
import numpy as np
import os
import argparse
import sys
from pathlib import Path

def split_las_grid(input_file, output_dir, grid_size):
    """Divide una nube LAS/LAZ en una cuadrícula mediante streaming."""

    import os
    import numpy as np
    import laspy
    from pathlib import Path

    os.makedirs(output_dir, exist_ok=True)

    base_name = Path(input_file).stem

    # PASADA 1: obtener límites de la nube
    print("Pasada 1: Leyendo información del archivo...")

    with laspy.open(input_file) as reader:
        header = reader.header

        min_x = float(header.x_min)
        min_y = float(header.y_min)
        max_x = float(header.x_max)
        max_y = float(header.y_max)

        num_cols = int(np.ceil((max_x - min_x) / grid_size))
        num_rows = int(np.ceil((max_y - min_y) / grid_size))

        print(f"Grid: {num_rows} filas x {num_cols} columnas "
              f"({num_rows * num_cols} total)")
        print(f"Rango X: [{min_x:.2f}, {max_x:.2f}]")
        print(f"Rango Y: [{min_y:.2f}, {max_y:.2f}]")
        print(f"Total de puntos: {header.point_count:,}")

    # PASADA 2: distribuir los puntos por bloques
    print("\nPasada 2: Escribiendo archivos en streaming...")

    writers = {}
    counts = {}
    total_processed = 0
    chunk_size = 100_000

    try:
        with laspy.open(input_file) as reader:
            header = reader.header

            for chunk_idx, chunk in enumerate(
                reader.chunk_iterator(points_per_iteration=chunk_size)
            ):
                xs = np.asarray(chunk.x)
                ys = np.asarray(chunk.y)

                cols = np.floor(
                    (xs - min_x) / grid_size
                ).astype(np.int64)

                rows = np.floor(
                    (ys - min_y) / grid_size
                ).astype(np.int64)

                cols = np.clip(cols, 0, num_cols - 1)
                rows = np.clip(rows, 0, num_rows - 1)

                # Identificar las celdas presentes en el bloque
                cell_ids = rows * num_cols + cols

                for cell_id in np.unique(cell_ids):
                    mask = cell_ids == cell_id

                    row = int(cell_id // num_cols)
                    col = int(cell_id % num_cols)
                    key = (col, row)

                    if key not in writers:
                        output_file = os.path.join(
                            output_dir,
                            f"{base_name}_grid_{col}_{row}.las"
                        )

                        # Crear un archivo LAS y mantenerlo abierto.
                        # Se conserva el formato de puntos original.
                        writer = laspy.open(
                            output_file,
                            mode="w",
                            header=header
                        )

                        writers[key] = writer
                        counts[key] = 0

                    # Escribir los registros seleccionados del bloque.
                    writers[key].write_points(chunk[mask])

                    n_points = int(np.count_nonzero(mask))
                    counts[key] += n_points

                total_processed += len(chunk)

                if (chunk_idx + 1) % 100 == 0:
                    print(
                        f"  Bloques procesados: {chunk_idx + 1:,} | "
                        f"Puntos procesados: {total_processed:,}"
                    )

    finally:
        # Cerrar todos los archivos para finalizar correctamente
        # sus encabezados y liberar los recursos.
        for writer in writers.values():
            writer.close()

    print("\nPasada 3: Resumen de archivos generados...")

    for key in sorted(counts):
        col, row = key
        print(
            f"  [{col},{row}]: {counts[key]:,} puntos"
        )

    print(f"\nPuntos procesados: {total_processed:,}")
    print(f"Archivos generados: {len(writers)}")

    return len(writers)

def cut_las_bbox(input_file, output_file, xmin, xmax, ymin, ymax, zmin=None, zmax=None):
    """Recorta la nube con un bounding box específico (streaming)"""
    
    # Validar que los límites son coherentes
    if xmin >= xmax or ymin >= ymax:
        raise ValueError("Límites X o Y inválidos (min debe ser < max)")
    
    print(f"Recortando con bbox: X[{xmin}, {xmax}], Y[{ymin}, {ymax}]", end="")
    if zmin is not None and zmax is not None:
        if zmin >= zmax:
            raise ValueError("Límites Z inválidos (min debe ser < max)")
        print(f", Z[{zmin}, {zmax}]", end="")
    print()
    
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    
    point_count = 0
    chunk_size = 100000
    
    with laspy.open(input_file) as reader:
        header = reader.header
        output_las = laspy.create(point_format=header.point_format, file_version=header.version)
        output_las.header = header
        
        for chunk_idx, chunk in enumerate(reader.chunk_iterator(points_per_iteration=chunk_size)):
            xs = np.array(chunk.x, dtype=np.float64)
            ys = np.array(chunk.y, dtype=np.float64)
            zs = np.array(chunk.z, dtype=np.float64)
            
            # Crear máscara
            mask = (xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)
            
            if zmin is not None and zmax is not None:
                mask = mask & (zs >= zmin) & (zs <= zmax)
            
            # Agregar puntos seleccionados
            for i in np.where(mask)[0]:
                output_las.split_las_grid(chunk[i])
                point_count += 1
            
            if (chunk_idx + 1) % 50 == 0:
                print(f"  Procesados: {point_count:,} puntos")
    
    if point_count == 0:
        print("Advertencia: Ningún punto dentro del bbox especificado")
        return 0
    
    output_las.write(output_file)
    print(f"✓ Guardado: {output_file}")
    print(f"  Puntos totales: {point_count:,}")
    return point_count


def cut_las_from_csv(input_file, csv_file, output_dir):
    """Lee múltiples recortes desde un archivo CSV (streaming)"""
    import csv
    
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    
    # Leer CSV
    recortes = []
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                recortes.append({
                    'nombre': row['nombre'],
                    'xmin': float(row['xmin']),
                    'xmax': float(row['xmax']),
                    'ymin': float(row['ymin']),
                    'ymax': float(row['ymax']),
                    'zmin': float(row['zmin']) if 'zmin' in row and row['zmin'].strip() else None,
                    'zmax': float(row['zmax']) if 'zmax' in row and row['zmax'].strip() else None,
                })
            except Exception as e:
                print(f"Advertencia: Error leyendo CSV: {e}")
    
    print(f"Procesando {len(recortes)} recortes...")
    
    total_output = 0
    writers = {}  # {idx: {'las': LasData, 'nombre': str, 'count': N}}
    chunk_size = 100000
    
    with laspy.open(input_file) as reader:
        header = reader.header
        
        processed = 0
        for chunk_idx, chunk in enumerate(reader.chunk_iterator(points_per_iteration=chunk_size)):
            xs = np.array(chunk.x, dtype=np.float64)
            ys = np.array(chunk.y, dtype=np.float64)
            zs = np.array(chunk.z, dtype=np.float64)
            
            for i in range(len(chunk)):
                x, y, z = xs[i], ys[i], zs[i]
                
                for idx, recorte in enumerate(recortes):
                    if recorte['xmin'] <= x <= recorte['xmax'] and \
                       recorte['ymin'] <= y <= recorte['ymax']:
                        
                        if recorte['zmin'] is None or recorte['zmax'] is None or \
                           (recorte['zmin'] <= z <= recorte['zmax']):
                            
                            if idx not in writers:
                                writers[idx] = {
                                    'las': laspy.create(point_format=header.point_format, file_version=header.version),
                                    'nombre': recorte['nombre'],
                                    'count': 0
                                }
                                writers[idx]['las'].header = header
                            
                            writers[idx]['las'].split_las_grid(chunk[i])
                            writers[idx]['count'] += 1
                
                processed += 1
            
            if (chunk_idx + 1) % 50 == 0:
                total_puntos = sum(w['count'] for w in writers.values())
                print(f"  Procesados: {processed:,} puntos, guardados: {total_puntos:,}")
    
    print(f"\nGuardando archivos...")
    for idx in sorted(writers.keys()):
        data = writers[idx]
        if data['count'] > 0:
            output_file = output_dir_path / f"{data['nombre']}.las"
            data['las'].write(str(output_file))
            print(f"[{idx+1}] {data['nombre']}: {data['count']:,} puntos → {output_file}")
            total_output += 1
        else:
            print(f"[{idx+1}] {recortes[idx]['nombre']}: Advertencia: 0 puntos")
    
    print(f"\n✓ Completado: {total_output} archivos generados")
    return total_output


def print_cloud_info(input_file):
    """Muestra información sobre la nube de puntos"""
    with laspy.open(input_file) as reader:
        header = reader.header
        
        print(f"\n{'='*60}")
        print(f"Información de la nube: {input_file}")
        print(f"{'='*60}")
        print(f"Total de puntos: {header.point_count:,}")
        print(f"\nRangos de coordenadas:")
        print(f"  X: [{header.x_min:.2f}, {header.x_max:.2f}] (rango: {header.x_max - header.x_min:.2f})")
        print(f"  Y: [{header.y_min:.2f}, {header.y_max:.2f}] (rango: {header.y_max - header.y_min:.2f})")
        print(f"  Z: [{header.z_min:.2f}, {header.z_max:.2f}] (rango: {header.z_max - header.z_min:.2f})")
        print(f"\nPropiedades LAS:")
        print(f"  Versión: {header.version}")
        print(f"  Escala X: {header.x_scale}")
        print(f"  Escala Y: {header.y_scale}")
        print(f"  Escala Z: {header.z_scale}")
        print(f"  Offset X: {header.x_offset}")
        print(f"  Offset Y: {header.y_offset}")
        print(f"  Offset Z: {header.z_offset}")
        print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Herramienta para recortar nubes de puntos LAS/LAZ (optimizado para archivos grandes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:

  # Dividir en grid de 25m
  python split_las_streaming.py --input nube.laz --grid 25 --output output_dir

  # Recorte por bbox
  python split_las_streaming.py --input nube.laz --bbox 359100 359125 9578900 9578925 --output recorte.las

  # Recorte con elevación
  python split_las_streaming.py --input nube.laz --bbox 359100 359125 9578900 9578925 --zmin 0 --zmax 50 --output recorte.las

  # Leer múltiples recortes desde CSV
  python split_las_streaming.py --input nube.laz --csv recortes.csv --output output_dir

  # Ver información de la nube
  python split_las_streaming.py --info nube.laz
        """
    )
    
    parser.add_argument('-i', '--input', help='Archivo LAS/LAZ de entrada')
    parser.add_argument('-o', '--output', help='Archivo o directorio de salida')
    parser.add_argument('-g', '--grid', type=float, help='Tamaño de grid en metros')
    parser.add_argument('--bbox', nargs=4, type=float, metavar=('XMIN', 'XMAX', 'YMIN', 'YMAX'),
                       help='Recorte por bounding box')
    parser.add_argument('--zmin', type=float, help='Mínimo Z (elevación)')
    parser.add_argument('--zmax', type=float, help='Máximo Z (elevación)')
    parser.add_argument('--csv', help='Archivo CSV con múltiples recortes')
    parser.add_argument('--info', help='Mostrar información de la nube')
    
    args = parser.parse_args()
    
    # Mostrar información
    if args.info:
        print_cloud_info(args.info)
        return
    
    # Validar argumentos
    if not args.input:
        print("Error: --input es requerido")
        parser.print_help()
        sys.exit(1)
    
    if not os.path.exists(args.input):
        print(f"Error: Archivo {args.input} no encontrado")
        sys.exit(1)
    
    # Ejecutar modo seleccionado
    try:
        if args.grid:
            if not args.output:
                args.output = "output_grid"
            split_las_grid(args.input, args.output, args.grid)
        
        elif args.bbox:
            if not args.output:
                args.output = "recorte.las"
            xmin, xmax, ymin, ymax = args.bbox
            cut_las_bbox(args.input, args.output, xmin, xmax, ymin, ymax, args.zmin, args.zmax)
        
        elif args.csv:
            if not args.output:
                args.output = "output_csv"
            cut_las_from_csv(args.input, args.csv, args.output)
        
        else:
            print("Error: Debe especificar --grid, --bbox o --csv")
            parser.print_help()
            sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Parámetros por defecto para ejecución directa
    input_file = "E:/AMACAYACU_TLS/Docker_RCT/AMA_L25_ha_ROI.laz"
    
    if len(sys.argv) == 1:
        # Si no hay argumentos, usar valores por defecto
        print("Modo automático (sin argumentos)")
        output_dir = "Docker_RCT/Files_split"
        grid_size = 15
        
        if os.path.exists(input_file):
            split_las_grid(input_file, output_dir, grid_size)
        else:
            print(f"Archivo no encontrado: {input_file}")
            print("\nUso: python split_las_streaming.py [opciones]")
            print("     python split_las_streaming.py --help")
    else:
        main()
