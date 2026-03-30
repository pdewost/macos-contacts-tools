import subprocess
import os
import logging

logger = logging.getLogger(__name__)

def get_image_resolution(image_path: str) -> tuple[int, int]:
    """Returns (width, height) of the image using sips."""
    try:
        cmd_dim = ["sips", "-g", "pixelWidth", "-g", "pixelHeight", image_path]
        res = subprocess.run(cmd_dim, capture_output=True, text=True)
        width, height = 0, 0
        for line in res.stdout.splitlines():
            if ":" not in line: continue
            parts = line.split(":", 1)
            val = parts[1].strip()
            if val == "<nil>" or not val: continue
            
            if "pixelWidth" in line:
                width = int(val)
            if "pixelHeight" in line:
                height = int(val)
        return width, height
    except:
        return 0, 0

def optimize_image(image_path: str, max_dimension: int = 1024) -> str:  # v4.9.1 A1: 768→1024 (AUDIT_2026-03-11)
    """
    Optimizes an image using the macOS native 'sips' command.
    Ensures the image is HEIC and fits within a max dimension without upscaling.
    
    Returns the path to the optimized image.
    """
    output_path = os.path.splitext(image_path)[0] + "_opt.heic"
    
    try:
        # 1. Get current dimensions
        width, height = get_image_resolution(image_path)
        
        # 2. Determine if resize is needed (no upscaling)
        if width > max_dimension or height > max_dimension:
            # Resize while maintaining aspect ratio
            cmd_opt = [
                "sips", 
                "--setProperty", "format", "heic",
                "--resampleHeightWidthMax", str(max_dimension),
                image_path, 
                "--out", output_path
            ]
        else:
            # Just convert to HEIC
            cmd_opt = [
                "sips", 
                "--setProperty", "format", "heic",
                image_path, 
                "--out", output_path
            ]
            
        subprocess.run(cmd_opt, check=True, capture_output=True)
        logger.info(f"Image optimized: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Image optimization failed: {e}")
        return image_path

if __name__ == "__main__":
    # Quick sanity check/test if run directly
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 2:
        optimize_image(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python image_optim.py <input> <output>")
