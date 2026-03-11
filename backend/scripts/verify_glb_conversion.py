
import sys
import tempfile
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import trimesh

from processing.glb_converter import (
    convert_mesh_to_glb,
    get_glb_stats,
    compare_mesh_sizes,
)


def create_test_mesh() -> trimesh.Trimesh:
    """Create a simple test mesh (sphere)."""
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=50.0)
    return mesh


def run_verification():
    """Run the GLB conversion verification."""
    print("=" * 60)
    print("GLB Conversion Verification")
    print("=" * 60)
    
    # Create temp directory for testing
    with tempfile.TemporaryDirectory(prefix="glb_test_") as temp_dir:
        temp_path = Path(temp_dir)
        
        # Step 1: Create test mesh
        print("\n[1] Creating test mesh...")
        mesh = create_test_mesh()
        print(f"    Vertices: {len(mesh.vertices)}")
        print(f"    Faces: {len(mesh.faces)}")
        print(f"    Has normals: {mesh.vertex_normals is not None}")
        
        # Step 2: Export to OBJ for comparison
        print("\n[2] Exporting to OBJ (baseline)...")
        obj_path = temp_path / "test_mesh.obj"
        mesh.export(str(obj_path))
        obj_size = obj_path.stat().st_size
        print(f"    OBJ size: {obj_size / 1024:.2f} KB")
        
        # Step 3: Convert to GLB with Draco
        print("\n[3] Converting to Draco-compressed GLB...")
        glb_path = temp_path / "test_mesh.glb"
        success, message = convert_mesh_to_glb(mesh, glb_path, apply_draco=True)
        
        print(f"    Success: {success}")
        print(f"    Message: {message}")
        
        if success and glb_path.exists():
            stats = get_glb_stats(glb_path)
            print(f"    GLB size: {stats['size_kb']:.2f} KB")
            
            # Calculate reduction
            comparison = compare_mesh_sizes(obj_path, glb_path)
            if comparison:
                print(f"\n[4] Compression Results:")
                print(f"    OBJ: {comparison['obj_size_kb']:.2f} KB")
                print(f"    GLB: {comparison['glb_size_kb']:.2f} KB")
                print(f"    Reduction: {comparison['reduction_percent']:.1f}%")
                print(f"    Compression ratio: {comparison['compression_ratio']:.1f}x")
                
                # Verify target reduction
                if comparison['reduction_percent'] >= 50:
                    print("\n✓ PASS: Compression achieved >50% reduction")
                else:
                    print("\n! WARN: Compression <50%, but file is valid")
        else:
            print("\n[ERROR] GLB conversion failed")
            return False
        
        # Step 4: Verify GLB can be loaded back
        print("\n[5] Verifying GLB can be loaded...")
        try:
            loaded = trimesh.load(str(glb_path))
            if hasattr(loaded, 'geometry'):
                # GLB may load as Scene
                mesh_count = len(loaded.geometry)
                print(f"    Loaded as Scene with {mesh_count} meshes")
            else:
                print(f"    Loaded as Trimesh: {len(loaded.vertices)} vertices")
            print("    ✓ GLB is valid and loadable")
        except Exception as e:
            print(f"    ✗ Failed to load GLB: {e}")
            return False
    
    print("\n" + "=" * 60)
    print("✓ All verifications passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = run_verification()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
