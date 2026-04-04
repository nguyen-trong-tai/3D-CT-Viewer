
import numpy as np
import nibabel as nib

class HUPreprocessor:
    """Chuẩn hóa HU volume cho lung CT."""

    # Lung window chuẩn lâm sàng
    LUNG_WINDOW_CENTER = -600
    LUNG_WINDOW_WIDTH  = 1500   # range: [-1350, 150] HU

    # HU thresholds cho segmentation
    HU_AIR_MAX    = -400   # phổi + background < -400
    HU_BODY_MIN   = -200   # body/soft tissue > -200
    HU_CLIP_MIN   = -1024
    HU_CLIP_MAX   =  3071

    @staticmethod
    def clip_hu(volume: np.ndarray) -> np.ndarray:
        """Clip về range HU vật lý hợp lệ."""
        return np.clip(volume, HUPreprocessor.HU_CLIP_MIN, HUPreprocessor.HU_CLIP_MAX)

    @staticmethod
    def window_normalize(volume: np.ndarray,
                         center: int = LUNG_WINDOW_CENTER,
                         width:  int = LUNG_WINDOW_WIDTH) -> np.ndarray:
        """
        Apply lung window rồi normalize về [0, 1].
        Dùng cho visualization và deep learning input.
        """
        hu_min = center - width / 2
        hu_max = center + width / 2
        windowed = np.clip(volume, hu_min, hu_max)
        return ((windowed - hu_min) / (hu_max - hu_min)).astype(np.float32)

    @staticmethod
    def get_body_mask(volume: np.ndarray) -> np.ndarray:
        """
        Tách body (bệnh nhân) ra khỏi air hoàn toàn.
        Body gồm tất cả tissue: HU > -200.
        Dùng để sau này loại bed/table.
        """
        body = volume > HUPreprocessor.HU_BODY_MIN

        # Fill holes để có solid body mask
        for i in range(body.shape[0]):
            body[i] = ndimage.binary_fill_holes(body[i])

        # 3D closing để nối các phần bị đứt
        body = ndimage.binary_closing(body, structure=np.ones((3, 5, 5)))
        return body


# Expose constants ra ngoài class để dùng nhanh
HU_AIR_MAX  = HUPreprocessor.HU_AIR_MAX
HU_BODY_MIN = HUPreprocessor.HU_BODY_MIN