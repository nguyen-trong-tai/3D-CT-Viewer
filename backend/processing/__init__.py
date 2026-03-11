"""
Processing Package

Contains all data processing modules for the CT Imaging Platform:
- loader: DICOM and NIfTI file loading with HU conversion
- segmentation: Volume segmentation algorithms
- sdf: Signed Distance Function computation
- mesh: Surface mesh generation via Marching Cubes
"""

from .loader import (
    load_dicom_series,
    load_dicom_from_files,
    load_dicom_from_bytes_list,
    load_nifti,
    parse_dicom_bytes,
    process_dicom_slice,
    extract_dicom_metadata,
)

from .segmentation import (
    segment_volume_baseline,
    segment_lung,
    segment_tissue,
    segment_bone,
    segment_with_morphology,
    get_largest_connected_component,
    compute_segmentation_stats,
)

from .sdf import (
    compute_sdf,
    compute_sdf_fast,
    compute_sdf_downsampled,
    compute_sdf_chunked,
    get_optimal_downsample_factor,
    normalize_sdf,
)

from .mesh import (
    extract_mesh,
    extract_mesh_from_mask,
    smooth_mesh_laplacian,
    decimate_mesh,
    compute_mesh_stats,
    export_mesh,
    combine_meshes,
)

from .glb_converter import (
    convert_mesh_to_glb,
    get_glb_stats,
    compare_mesh_sizes,
)

__all__ = [
    # Loader
    "load_dicom_series",
    "load_dicom_from_files",
    "load_dicom_from_bytes_list",
    "load_nifti",
    "parse_dicom_bytes",
    "process_dicom_slice",
    "extract_dicom_metadata",
    # Segmentation
    "segment_volume_baseline",
    "segment_lung",
    "segment_tissue",
    "segment_bone",
    "segment_with_morphology",
    "get_largest_connected_component",
    "compute_segmentation_stats",
    # SDF
    "compute_sdf",
    "compute_sdf_fast",
    "compute_sdf_downsampled",
    "compute_sdf_chunked",
    "get_optimal_downsample_factor",
    "normalize_sdf",
    # Mesh
    "extract_mesh",
    "extract_mesh_from_mask",
    "smooth_mesh_laplacian",
    "decimate_mesh",
    "compute_mesh_stats",
    "export_mesh",
    "combine_meshes",
    # GLB Converter
    "convert_mesh_to_glb",
    "get_glb_stats",
    "compare_mesh_sizes",
]

