
import cv2
import numpy as np
from PIL import Image, ExifTags
import os

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REQUIRED_IDS = [1, 18, 43, 14]            # reference ArUco tags
ARUCO_DICT   = cv2.aruco.DICT_7X7_250     # dictionary used on printed markers
BOTTOM_EXTRA_PX = 300                     # extra space added below cropped slab

# ---------------------------------------------------------------------------
# Helper: friendly EXIF dump
# ---------------------------------------------------------------------------
def _dump_exif(pil_img):
    exif_raw = pil_img._getexif()
    if not exif_raw:
        return "No EXIF data found."
    lines = []
    for tag_id, val in exif_raw.items():
        tag = ExifTags.TAGS.get(tag_id, str(tag_id))
        lines.append(f"{tag}: {val}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Main processing routine
# ---------------------------------------------------------------------------
def process_slab_image(
    input_path,
    output_path,
    stone_thickness_mm: float = 30.0,     # accepted but unused
    frame_width_mm:  float = 4064,
    frame_height_mm: float = 2286,
    resize_ppi:      int   = 72,
    debug_path: str | None = 'static/debug_markers.jpg'
) -> bool:
    """
    Detects four reference ArUco markers (IDs 1,18,43,14) in the 7×7‑250 family,
    warps the slab to a rectangle of *frame_width_mm* × *frame_height_mm*,
    crops off the marker border (so the final image is marker‑free), then
    **extends the bottom edge by 300 px** to give extra space for custom
    cropping/annotations. The processed image is saved at *output_path* and a
    companion text file "*_info.txt" summarises the original DPI, chosen PPI
    and all EXIF tags.
    """
    # ---------------------------------------------------------------------
    # 1. Load via Pillow to capture EXIF & DPI
    # ---------------------------------------------------------------------
    pil_orig = Image.open(input_path)
    dpi_x, dpi_y = pil_orig.info.get("dpi", (resize_ppi, resize_ppi))
    exif_text = _dump_exif(pil_orig)
    pil_orig.close()

    # Load again in OpenCV for processing
    image = cv2.imread(input_path)
    if image is None:
        raise ValueError(f"Cannot load image: {input_path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # ---------------------------------------------------------------------
    # 2. Detect ArUco markers
    # ---------------------------------------------------------------------
    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector   = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None or len(ids) < 4:
        raise ValueError("No ArUco markers detected.")

    ids_flat = ids.flatten().tolist()
    missing  = [mid for mid in REQUIRED_IDS if mid not in ids_flat]
    if missing:
        raise ValueError(f"Missing marker IDs: {missing}")

    # Debug overlay
    if debug_path:
        dbg = image.copy()
        cv2.aruco.drawDetectedMarkers(dbg, corners, ids)
        os.makedirs(os.path.dirname(debug_path), exist_ok=True)
        cv2.imwrite(debug_path, dbg)

    # ---------------------------------------------------------------------
    # 3. Perspective transform
    # ---------------------------------------------------------------------
    id_to_corners = {id_[0]: c.reshape(4,2) for c,id_ in zip(corners, ids)}

    src_pts = np.array([
        id_to_corners[1][0],   # ID1  TL
        id_to_corners[18][1],  # ID18 TR
        id_to_corners[43][2],  # ID43 BR
        id_to_corners[14][3]   # ID14 BL
    ], dtype=np.float32)

    ppi = max(dpi_x, dpi_y, resize_ppi)
    px_per_mm = ppi / 25.4
    dst_w = int(frame_width_mm  * px_per_mm)
    dst_h = int(frame_height_mm * px_per_mm)

    dst_pts = np.array([
        [0, 0],
        [dst_w - 1, 0],
        [dst_w - 1, dst_h - 1],
        [0, dst_h - 1]
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(image, M, (dst_w, dst_h))

    # ---------------------------------------------------------------------
    # 4. Compute interior crop (remove markers)
    # ---------------------------------------------------------------------
    transformed = {}
    for mid, pts in id_to_corners.items():
        pts_reshaped = pts.reshape(-1,1,2).astype(np.float32)
        warped_pts   = cv2.perspectiveTransform(pts_reshaped, M).reshape(-1,2)
        transformed[mid] = warped_pts

    left_boundary   = max([np.max(transformed[m][:,0]) for m in (1,14)])
    right_boundary  = min([np.min(transformed[m][:,0]) for m in (18,43)])
    top_boundary    = max([np.max(transformed[m][:,1]) for m in (1,18)])
    bottom_boundary = max([np.max(transformed[m][:,1]) for m in (14,43)])

    h, w = warped.shape[:2]
    left   = int(np.clip(left_boundary,   0, w-1))
    right  = int(np.clip(right_boundary,  0, w-1))
    top    = int(np.clip(top_boundary,    0, h-1))
    bottom = int(np.clip(bottom_boundary + BOTTOM_EXTRA_PX, 0, h-1))

    if left >= right or top >= bottom:
        raise ValueError("Invalid crop boundaries after perspective transform.")

    cropped = warped[top:bottom, left:right]

    # ---------------------------------------------------------------------
    # 5. Save image
    # ---------------------------------------------------------------------
    out_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
    out_pil.save(output_path, dpi=(ppi, ppi))

    # ---------------------------------------------------------------------
    # 6. Save info text
    # ---------------------------------------------------------------------
    info_path = os.path.splitext(output_path)[0] + "_info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"Original DPI X: {dpi_x}\n")
        f.write(f"Original DPI Y: {dpi_y}\n")
        f.write(f"PPI used for processing: {ppi}\n\n")
        f.write("EXIF Information:\n")
        f.write(exif_text + "\n")

    return True
