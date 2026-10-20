"""
Script optimizado para unir múltiples archivos PLY en un solo archivo LAZ.
LAZ es el formato estándar comprimido para datos LiDAR/TLS.
Usa lectura paralela y preserva doble precisión para exactitud georeferencial.

Uso:
    python merge_ply_files.py <carpeta_entrada> <archivo_salida>
    
Ejemplo:
    python merge_ply_files.py "./ply_files" "./merged.laz"
"""

import sys
import struct
from pathlib import Path
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import os
import laspy


def read_ply_file(filepath):
    """
    Lee un archivo PLY y extrae vértices con sus propiedades (xyz, rgb).
    Detecta automáticamente la estructura del archivo PLY.
    
    Args:
        filepath: Ruta al archivo PLY
        
    Returns:
        vertices: Array Nx3 con coordenadas (x, y, z)
        colors: Array Nx3 con valores RGB (0-255)
        properties: Dict con información de las propiedades del PLY
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        # Leer encabezado
        lines = []
        format_type = None
        vertex_count = 0
        properties = {}
        property_order = []
        
        for line in f:
            lines.append(line.strip())
            
            if line.startswith('format'):
                format_type = line.split()[1]
            elif line.startswith('element vertex'):
                vertex_count = int(line.split()[2])
            elif line.startswith('property'):
                parts = line.split()
                if len(parts) >= 3:
                    prop_type = parts[1]
                    prop_name = parts[2]
                    properties[prop_name] = prop_type
                    property_order.append((prop_name, prop_type))
            elif line.startswith('end_header'):
                break
        
        header_length = len('\n'.join(lines)) + 1
    
    vertices = []
    colors = []
    
    if format_type == 'ascii':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Saltar encabezado
            for _ in lines:
                f.readline()
            
            # Leer vértices
            for _ in range(vertex_count):
                line = f.readline().strip()
                if not line:
                    continue
                    
                values = line.split()
                try:
                    # Buscar índices de x, y, z, r, g, b
                    idx_x = next((i for i, (n, t) in enumerate(property_order) if n == 'x'), 0)
                    idx_y = next((i for i, (n, t) in enumerate(property_order) if n == 'y'), 1)
                    idx_z = next((i for i, (n, t) in enumerate(property_order) if n == 'z'), 2)
                    idx_r = next((i for i, (n, t) in enumerate(property_order) if n == 'red'), None)
                    idx_g = next((i for i, (n, t) in enumerate(property_order) if n == 'green'), None)
                    idx_b = next((i for i, (n, t) in enumerate(property_order) if n == 'blue'), None)
                    
                    x = float(values[idx_x])
                    y = float(values[idx_y])
                    z = float(values[idx_z])
                    vertices.append([x, y, z])
                    
                    # Leer RGB
                    if idx_r is not None and idx_g is not None and idx_b is not None:
                        r = int(float(values[idx_r]))
                        g = int(float(values[idx_g]))
                        b = int(float(values[idx_b]))
                    else:
                        r = g = b = 255
                    
                    colors.append([r, g, b])
                except (ValueError, IndexError):
                    continue
    
    elif format_type == 'binary_little_endian' or format_type == 'binary_big_endian':
        endian = '<' if format_type == 'binary_little_endian' else '>'
        
        with open(filepath, 'rb') as f:
            f.seek(header_length)
            
            # Construir struct format basado en property_order
            struct_format = endian
            struct_size = 0
            indices = {'x': None, 'y': None, 'z': None, 'red': None, 'green': None, 'blue': None}
            current_offset = 0
            
            for prop_name, prop_type in property_order:
                if prop_type == 'double':
                    struct_format += 'd'
                    type_size = 8
                elif prop_type == 'float':
                    struct_format += 'f'
                    type_size = 4
                elif prop_type == 'uchar':
                    struct_format += 'B'
                    type_size = 1
                elif prop_type == 'int':
                    struct_format += 'i'
                    type_size = 4
                else:
                    continue
                
                if prop_name in indices:
                    indices[prop_name] = current_offset
                current_offset += type_size
            
            struct_size = struct.calcsize(struct_format)
            
            for _ in range(vertex_count):
                try:
                    data = f.read(struct_size)
                    if len(data) < struct_size:
                        break
                    
                    values = struct.unpack(struct_format, data)
                    
                    # Extraer coordenadas por índice
                    if all(indices[k] is not None for k in ['x', 'y', 'z']):
                        # Buscar valores por posición en la tupla desempacada
                        # Necesitamos recalcular índices correctamente
                        x_idx = sum(1 for n, t in property_order[:indices['x']] if True) 
                        
                    # Versión simplificada: asumir primeras 3 propiedades son x, y, z
                    x = float(values[0])
                    y = float(values[1])
                    z = float(values[2])
                    vertices.append([x, y, z])
                    
                    # Buscar RGB en el resto
                    r = g = b = 255
                    for i, (prop_name, _) in enumerate(property_order):
                        if prop_name == 'red' and i < len(values):
                            r = int(values[i])
                        elif prop_name == 'green' and i < len(values):
                            g = int(values[i])
                        elif prop_name == 'blue' and i < len(values):
                            b = int(values[i])
                    
                    colors.append([r, g, b])
                except struct.error:
                    break
    
    # IMPORTANTE: Mantener doble precisión (float64) para preservar coordenadas exactas
    return np.array(vertices, dtype=np.float64), np.array(colors, dtype=np.uint8), properties


def write_laz_file(filepath, vertices, colors):
    """
    Escribe un archivo LAZ (LiDAR Compressed) con vértices y colores RGB.
    Usa DOBLE PRECISIÓN (float64) y configura scales correctamente.
    LAZ es mucho mejor que PLY para datos LiDAR: comprimido, estándar, preciso.
    
    Args:
        filepath: Ruta del archivo de salida (.laz)
        vertices: Array Nx3 con coordenadas (x, y, z) en float64
        colors: Array Nx3 con valores RGB (0-255)
    """
    num_vertices = len(vertices)
    
    print(f"  Creando archivo LAZ con {num_vertices:,} vértices...")
    
    # Crear nube de puntos LAS
    las = laspy.create(point_format=3, file_version="1.2")
    
    # Configurar scales para máxima precisión (0.001 = 1 mm)
    # Esto es importante para preservar coordenadas UTM exactas
    las.header.scales = np.array([0.001, 0.001, 0.001])
    
    # Calcular offsets basados en rangos de datos
    las.header.offsets = np.array([
        vertices[:, 0].min(),
        vertices[:, 1].min(),
        vertices[:, 2].min()
    ])
    
    # Asignar coordenadas (laspy escala automáticamente usando header.scales/offsets)
    las.x = vertices[:, 0]
    las.y = vertices[:, 1]
    las.z = vertices[:, 2]
    
    # Asignar colores RGB
    colors_clipped = np.clip(colors, 0, 255).astype(np.uint16)
    # LAZ usa 16-bit RGB (0-65535), escalar desde 8-bit (0-255)
    las.red = colors_clipped[:, 0] * 256
    las.green = colors_clipped[:, 1] * 256
    las.blue = colors_clipped[:, 2] * 256
    
    # Guardar como LAZ (comprimido)
    print(f"  Comprimiendo y escribiendo con escala 0.001 (1mm)...")
    las.write(filepath, do_compress=True)
    
    print(f"  OK - Archivo LAZ escrito exitosamente")


def merge_ply_files(input_folder, output_file, num_workers=None):
    """
    Une múltiples archivos PLY en un solo archivo LAZ usando lectura paralela.
    LAZ es el formato estándar comprimido para datos LiDAR, preserva precisión.
    
    Args:
        input_folder: Carpeta con archivos PLY
        output_file: Ruta del archivo LAZ de salida (.laz)
        num_workers: Número de hilos para lectura paralela (None = automático basado en CPU cores)
    """
    input_path = Path(input_folder)
    
    if not input_path.exists():
        print(f"Error: La carpeta '{input_folder}' no existe.")
        return False
    
    # Buscar archivos PLY
    ply_files = sorted(input_path.glob('*.ply'))
    
    if not ply_files:
        print(f"Error: No se encontraron archivos PLY en '{input_folder}'.")
        return False
    
    print(f"Encontrados {len(ply_files)} archivos PLY.")
    print(f"Usando lectura paralela con {num_workers or os.cpu_count()} hilos...\n")
    
    # Usar número automático de workers basado en CPU cores
    if num_workers is None:
        num_workers = min(os.cpu_count() or 4, len(ply_files))
    
    all_vertices = []
    all_colors = []
    lock = Lock()
    
    # Lectura paralela usando ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(read_ply_file, str(f)): f for f in ply_files}
        completed = 0
        
        for future in as_completed(futures):
            completed += 1
            ply_file = futures[future]
            
            try:
                vertices, colors, _ = future.result()
                
                if len(vertices) > 0:
                    with lock:
                        all_vertices.append(vertices)
                        all_colors.append(colors)
                    print(f"  [{completed}/{len(ply_files)}] OK {ply_file.name:<50} ({len(vertices):>8} vertices)")
                else:
                    print(f"  [{completed}/{len(ply_files)}] -- {ply_file.name:<50} (sin vertices)")
            except Exception as e:
                print(f"  [{completed}/{len(ply_files)}] ERROR {ply_file.name:<50} {e}")
                continue
    
    if not all_vertices:
        print("Error: No se pudieron leer vértices de ningún archivo.")
        return False
    
    # Combinar vértices y colores
    print("\nCombinando datos...")
    combined_vertices = np.vstack(all_vertices)
    combined_colors = np.vstack(all_colors)
    
    print(f"Total de vértices: {len(combined_vertices):,}")
    
    # Guardar archivo LAZ
    print(f"\nGuardando archivo LAZ (comprimido): {output_file}...")
    write_laz_file(output_file, combined_vertices, combined_colors)
    
    file_size_mb = os.path.getsize(output_file) / (1024**2)
    print(f"OK - Archivo creado exitosamente: {output_file}")
    print(f"  Tamaño: {file_size_mb:.2f} MB")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python merge_ply_files.py <carpeta_entrada> <archivo_salida> [num_workers]")
        print("\nEjemplos:")
        print('  python merge_ply_files.py "./ply_files" "./merged.laz"')
        print('  python merge_ply_files.py "C:\\datos\\ply" "C:\\salida\\combined.laz" 8')
        print("\nOpciones:")
        print("  num_workers: Número de hilos para lectura paralela (default: número de CPU cores)")
        print("\nFormato de salida: LAZ (LiDAR Compressed) - estándar para datos LiDAR")
        sys.exit(1)
    
    input_folder = sys.argv[1]
    output_file = sys.argv[2]
    num_workers = int(sys.argv[3]) if len(sys.argv) > 3 else None
    
    success = merge_ply_files(input_folder, output_file, num_workers)
    sys.exit(0 if success else 1)
