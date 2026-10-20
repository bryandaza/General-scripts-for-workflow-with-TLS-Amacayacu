import argparse
from pathlib import Path

import numpy as np
import open3d as o3d


DEFAULT_INPUT_DIR = Path(r"E:/AMACAYACU_TLS/Data_TLS/Palmas/Clean_all")
DEFAULT_OUTPUT_DIR = Path(r"E:/AMACAYACU_TLS/Data_TLS/Palmas/Clean_all_txt")
SUPPORTED_SUFFIXES = {".txt", ".ply"}


def read_xyz_txt(txt_file):
    points = np.loadtxt(txt_file, comments="#")

    if points.ndim == 1:
        points = points.reshape(1, -1)

    if points.shape[1] < 3:
        raise ValueError(
            f"{txt_file} debe tener al menos 3 columnas: X Y Z"
        )

    return points[:, :3].astype(np.float64)


def txt_to_binary_ply(txt_file, output_dir):
    print(f"Convirtiendo TXT a PLY: {txt_file.name}")

    points = read_xyz_txt(txt_file)

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)

    out_file = output_dir / f"{txt_file.stem}.ply"
    o3d.io.write_point_cloud(str(out_file), pcd, write_ascii=False)

    return out_file


def ply_to_txt(ply_file, output_dir):
    print(f"Convirtiendo PLY a TXT: {ply_file.name}")

    pcd = o3d.io.read_point_cloud(str(ply_file))
    points = np.asarray(pcd.points)

    if points.size == 0:
        raise ValueError(f"{ply_file} no contiene puntos XYZ.")

    out_file = output_dir / f"{ply_file.stem}.txt"
    np.savetxt(out_file, points, fmt="%.8f")

    return out_file


def convert_file(input_file, output_dir):
    suffix = input_file.suffix.lower()

    if suffix == ".txt":
        return txt_to_binary_ply(input_file, output_dir)

    if suffix == ".ply":
        return ply_to_txt(input_file, output_dir)

    print(f"Saltando archivo con extension no soportada: {input_file}")
    return None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convierte archivos TXT con columnas XYZ a PLY binario, o archivos PLY a TXT."
    )
    parser.add_argument(
        "input_files",
        nargs="*",
        type=Path,
        help="Lista de archivos .txt/.ply o carpetas completas a convertir.",
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        default=None,
        help="Carpeta con archivos .txt o .ply. Si se omite y no se pasan archivos, usa la carpeta por defecto.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Carpeta donde se guardaran los archivos convertidos.",
    )
    return parser.parse_args()


def get_input_files(args):
    if args.input_files:
        input_files = []
        for input_path in args.input_files:
            if input_path.is_dir():
                input_files.extend(get_supported_files(input_path))
            else:
                input_files.append(input_path)

        return sorted(input_files)

    input_dir = args.input_dir or DEFAULT_INPUT_DIR
    return get_supported_files(input_dir)


def get_supported_files(input_dir):
    input_files = []
    for suffix in SUPPORTED_SUFFIXES:
        input_files.extend(input_dir.glob(f"*{suffix}"))

    return sorted(input_files)


def main():
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    input_files = get_input_files(args)
    if not input_files:
        raise FileNotFoundError("No se encontraron archivos .txt o .ply para convertir.")

    converted = 0
    for input_file in input_files:
        if not input_file.exists():
            print(f"Saltando archivo inexistente: {input_file}")
            continue

        out_file = convert_file(input_file, output_dir)
        if out_file is not None:
            converted += 1

    print(f"Conversion terminada. Archivos convertidos: {converted}")


if __name__ == "__main__":
    main()
