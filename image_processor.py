import cv2
import numpy as np
from PIL import Image, ExifTags
import os

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REQUIRED_IDS     = [1, 18, 43, 14]           # reference ArUco tags
ARUCO_DICT       = cv2.aruco.DICT_7X7_250    # dictionary used on printed markers
BOTTOM_EXTRA_PX  = 300                       # final extra space (same as before)
PRE_MARGIN_PX    = 244                       # bottom margin after pre‑crop
TARGET_PPI       = 25.4                      # 1 px ≈ 1 mm  (fixed output DPI)

# ---------------------------------------------------------------------------
# Helpers
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


def _detect_markers(gray):
    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector   = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None or len(ids) < 4:
        raise ValueError("No ArUco markers detected.")
    ids_flat = ids.flatten().tolist()
    missing  = [mid for mid in REQUIRED_IDS if mid not in ids_flat]
    if missing:
        raise ValueError(f"Missing marker IDs: {missing}")
    return corners, ids


# ---------------------------------------------------------------------------
# Main processing routine
# ---------------------------------------------------------------------------
def process_slab_image(
    input_path,
    output_path,
    stone_thickness_mm: float = 30.0,     # accepted but unused
    frame_width_mm:  float = 4064,
    frame_height_mm: float = 2286,
    debug_path: str | None = 'static/debug_markers.jpg'
) -> bool:
    """
    Two‑stage processing:
    1) Pre‑crop around ArUco markers (+ ≤244 px bottom margin) to shrink image.
    2) Perspective‑correct, crop frame, extend bottom by 300 px, save at 25.4 PPI.
    """

    # ---------------------------------------------------------------------
    # Stage 0 · Load & EXIF
    # ---------------------------------------------------------------------
    pil_orig = Image.open(input_path)
    exif_text = _dump_exif(pil_orig)
    pil_orig.close()

    image = cv2.imread(input_path)
    if image is None:
        raise ValueError(f"Cannot load image: {input_path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # ---------------------------------------------------------------------
    # Stage 1 · Detect markers & pre‑crop
    # ---------------------------------------------------------------------
    corners, ids = _detect_markers(gray)
    all_pts = np.concatenate([c.reshape(-1,2) for c in corners], axis=0)
    x_min, y_min = np.min(all_pts, axis=0)
    x_max, y_max = np.max(all_pts, axis=0)

    # ensure ints and add bottom margin (up to PRE_MARGIN_PX, but not beyond image)
    h, w = image.shape[:2]
    pre_top    = int(max(y_min - 10, 0))          # small safety pad
    pre_left   = int(max(x_min - 10, 0))
    pre_right  = int(min(x_max + 10, w-1))
    pre_bottom = int(min(y_max + PRE_MARGIN_PX, h-1))

    pre_cropped = image[pre_top:pre_bottom, pre_left:pre_right]
    gray_pre    = cv2.cvtColor(pre_cropped, cv2.COLOR_BGR2GRAY)

    # re‑detect on the smaller image (coordinates are local now)
    corners_pre, ids_pre = _detect_markers(gray_pre)
    id_to_corners = {id_[0]: c.reshape(4,2) for c,id_ in zip(corners_pre, ids_pre)}

    # ---------------------------------------------------------------------
    # Stage 2 · Perspective transform on smaller image
    # ---------------------------------------------------------------------
    src_pts = np.array([
        id_to_corners[1][0],   # ID1  TL
        id_to_corners[18][1],  # ID18 TR
        id_to_corners[43][2],  # ID43 BR
        id_to_corners[14][3]   # ID14 BL
    ], dtype=np.float32)

    px_per_mm = TARGET_PPI / 25.4
    dst_w = int(frame_width_mm  * px_per_mm)
    dst_h = int(frame_height_mm * px_per_mm)

    dst_pts = np.array([
        [0, 0],
        [dst_w - 1, 0],
        [dst_w - 1, dst_h - 1],
        [0, dst_h - 1]
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(pre_cropped, M, (dst_w, dst_h))

    # ---------------------------------------------------------------------
    # Compute interior crop (remove markers)
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

    h2, w2 = warped.shape[:2]
    left   = int(np.clip(left_boundary,   0, w2-1))
    right  = int(np.clip(right_boundary,  0, w2-1))
    top    = int(np.clip(top_boundary,    0, h2-1))
    bottom = int(np.clip(bottom_boundary + BOTTOM_EXTRA_PX, 0, h2-1))

    if left >= right or top >= bottom:
        raise ValueError("Invalid crop boundaries after perspective transform.")

    final_img = warped[top:bottom, left:right]

    # ---------------------------------------------------------------------
    # Save image + info
    # ---------------------------------------------------------------------
    out_pil = Image.fromarray(cv2.cvtColor(final_img, cv2.COLOR_BGR2RGB))
    out_pil.save(output_path, dpi=(TARGET_PPI, TARGET_PPI))

    info_path = os.path.splitext(output_path)[0] + "_info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"Output PPI: {TARGET_PPI}\n\n")
        f.write("EXIF Information (original file):\n")
        f.write(exif_text + "\n")

    # optional debug overlay
    if debug_path:
        dbg = pre_cropped.copy()
        cv2.aruco.drawDetectedMarkers(dbg, corners_pre, ids_pre)
        os.makedirs(os.path.dirname(debug_path), exist_ok=True)
        cv2.imwrite(debug_path, dbg)

    return True
