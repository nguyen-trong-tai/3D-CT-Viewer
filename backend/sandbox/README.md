# Sandbox README

Thư mục `backend/sandbox` chứa pipeline thử nghiệm cho bài toán:

`Chest CT -> lung segmentation -> candidate detection -> patch extraction -> patch-based nodule segmentation -> local filtering -> map back -> mask fusion -> 3D post-processing -> final nodule mask`

README này tập trung vào 4 việc:

1. Chạy detector DeepLung riêng để debug candidate.
2. Chạy full nodule-mask pipeline trên Modal GPU.
3. Biết output nào cần mở khi detector hoặc segmentor có vấn đề.
4. Tìm đúng file code sau khi refactor.

## 1. Cấu trúc thư mục

- `deeplung_detector.py`
  - Wrapper inference cho DeepLung detector.
  - Nhận volume theo quy ước backend `(X, Y, Z)`.

- `transattunet_segmenter.py`
  - Wrapper inference cho TransAttUnet patch segmenter 2D.
  - Input patch mặc định `128 x 128`.

- `nodule_mask_pipeline/`
  - Package orchestration của full pipeline.
  - Đã thay cho file cũ `backend/sandbox/nodule_mask_pipeline.py`.
  - Các file chính:
    - `models.py`: config/result/data models
    - `contracts.py`: protocol/adapter cho detector và segmenter
    - `volume_ops.py`: resample/match shape
    - `stages.py`: logic theo từng stage
    - `pipeline.py`: orchestrator end-to-end

- `modal_deeplung_test.py`
  - Entry point Modal để test detector riêng.

- `modal_nodule_mask_test.py`
  - Entry point Modal để chạy full pipeline và lưu artifact debug.

- `checkpoints/`
  - Chứa weight của detector và segmenter.

- `NODULE_MASK_PIPELINE_REPORT.md`
  - Tài liệu chi tiết hơn về kiến trúc và data contract.

## 2. Điều kiện để chạy

### Local

- Đã cài `modal` CLI.
- Đã `modal token new` hoặc đã login sẵn.
- Repo đang đứng ở root, ví dụ `d:\Workspace\viewr_ct`.

### Modal volumes

Các script đang dùng các volume sau:

- `ct-data`: dữ liệu case đã được backend lưu.
- `data_raw`: dữ liệu raw để test trực tiếp từ DICOM/NIfTI/ZIP.
- `sandbox-output`: nơi lưu artifact output/debug.

### Model checkpoints

Các checkpoint đang được load từ repo:

- `backend/sandbox/checkpoints/detection/DeepLung.ckpt`
- `backend/sandbox/checkpoints/segmentation/TransAttUnet_v2.pth`

## 3. Input được hỗ trợ

Khi chạy qua `--volume-path`, script hỗ trợ:

- thư mục chứa DICOM `*.dcm`
- file `.nii`
- file `.nii.gz`
- file `.zip` chứa DICOM series
- file `.dcm`

Nếu truyền path tương đối, script sẽ hiểu đó là path bên trong volume `data_raw`.

Ví dụ:

```bash
modal run backend/sandbox/modal_deeplung_test.py::main --volume-path dataset/3000522.000000-NA-04919
```

## 4. Chạy DeepLung detector riêng

### Chạy theo `case_id`

```bash
modal run backend/sandbox/modal_deeplung_test.py::main --case-id <case_id>
```

Nếu case đã có lung mask trong repository và `--use-existing-mask true`, script sẽ dùng mask đó trước.

### Chạy theo `volume_path`

```bash
modal run backend/sandbox/modal_deeplung_test.py::main --volume-path dataset/3000522.000000-NA-04919
```

### Lưu JSON về local

```bash
modal run backend/sandbox/modal_deeplung_test.py::main --volume-path dataset/3000522.000000-NA-04919 --output-path backend/sandbox/deeplung_result.json
```

### Các tham số debug quan trọng

```bash
modal run backend/sandbox/modal_deeplung_test.py::main \
  --volume-path dataset/3000522.000000-NA-04919 \
  --score-threshold -3.0 \
  --nms-threshold 0.1 \
  --top-k 10
```

Ý nghĩa:

- `score-threshold`: ngưỡng logit trước NMS.
- `nms-threshold`: ngưỡng NMS 3D.
- `top-k`: số candidate tối đa giữ lại sau NMS.
- `use-existing-mask`: chỉ áp dụng khi chạy bằng `case_id`.

## 5. Chạy full nodule mask pipeline

### Chạy theo `case_id`

```bash
modal run backend/sandbox/modal_nodule_mask_test.py::main --case-id <case_id>
```

### Chạy theo `volume_path`

```bash
modal run backend/sandbox/modal_nodule_mask_test.py::main --volume-path dataset/3000522.000000-NA-04919
```

### Lưu JSON về local

```bash
modal run backend/sandbox/modal_nodule_mask_test.py::main --volume-path dataset/3000522.000000-NA-04919 --output-path backend/sandbox/nodule_mask_result.json
```

### Dùng hoặc bỏ existing lung mask

```bash
modal run backend/sandbox/modal_nodule_mask_test.py::main --case-id <case_id> --use-existing-mask false
```

## 6. Output sau khi chạy

### Detector-only

Artifact được lưu dưới:

```text
/sandbox_output/deeplung/<source-tag>/
```

Các file/nhóm file chính:

- `result.json`
  - Kết quả detector đã được làm gọn để JSON serialize được.
- `visualizations/`
  - Ảnh axial/coronal/sagittal cho từng candidate.
- `detector_debug/metadata.json`
  - Summary debug của detector.
- `detector_debug/clean_volume_zyx.npy`
  - Volume sau preprocess/crop để detector chạy.
- `detector_debug/raw_candidates_zyx.npy`
  - Candidate thô trước NMS.
- `detector_debug/post_nms_candidates_zyx.npy`
  - Candidate sau NMS.
- `detector_debug/selected_candidates_zyx.npy`
  - Candidate cuối cùng sau `top_k`.

### Full nodule-mask pipeline

Artifact được lưu dưới:

```text
/sandbox_output/nodule-mask/<source-tag>/
```

Các file/nhóm file chính:

- `result.json`
  - Payload tổng của pipeline.
- `final_mask_original.npy`
  - Final mask đã map về spacing/gốc của CT.
- `final_mask_resampled.npy`
  - Final mask ở không gian resample mục tiêu.
- `lung_mask.npy`
  - Lung mask dùng trong pipeline.
- `candidates.json`
  - Candidate records sau detector + local filtering state.

Artifacts debug để xem nhanh:

- `candidate_visualizations/`
  - Vị trí candidate trong CT.
- `detector_debug/`
  - Debug đầu ra detector.
- `segmentor_debug/`
  - Debug patch/slice của segmentor.
- `transattunet_raw_views/`
  - Probability thô từ segmentor trước local filtering.
- `filtered_local_views/`
  - Probability sau local filtering.
- `final_mask_views/`
  - Overlay final mask trên volume gốc.

## 7. Cách debug theo triệu chứng

### Trường hợp 1: detector không ra candidate

Mở theo thứ tự:

1. `result.json`
2. `detector_debug/metadata.json`
3. `detector_debug/clean_volume_zyx.npy`
4. `detector_debug/raw_candidates_zyx.npy`

Những điểm nên kiểm tra:

- `raw_candidate_count` có bằng `0` không.
- `extendbox_zyx` có quá nhỏ hoặc sai không.
- lung mask có rỗng không.
- `score-threshold` có đang quá cao không.

### Trường hợp 2: detector có candidate nhưng pipeline ra final mask rỗng

Mở theo thứ tự:

1. `candidates.json`
2. `transattunet_raw_views/`
3. `filtered_local_views/`
4. `segmentor_debug/candidate_xxx/metadata.json`

Những điểm nên kiểm tra:

- candidate có bị reject với `reason` như `empty_after_threshold` không.
- patch của segmentor có crop đúng vùng nodule không.
- local filtering có đang loại mất component trung tâm không.
- `foreground_threshold` có quá cao không.

### Trường hợp 3: segmentor crop sai vùng

Mở:

- `segmentor_debug/candidate_xxx/metadata.json`
- các file trong `segmentor_debug/candidate_xxx/slices/`

Ở đây bạn sẽ có:

- `input_zXXXX.npy`: input patch YX đưa vào model
- `probability_zXXXX.npy`: probability patch YX đầu ra
- `mapping`: thông tin map patch <-> slice gốc

Debug thường đi theo câu hỏi:

- patch có thật sự ôm đúng tâm candidate không
- tâm candidate ở slice nào
- mapping `slice_*` và `patch_*` có khớp vùng nhúng vào local volume không

### Trường hợp 4: final mask lệch so với CT gốc

Mở:

- `final_mask_resampled.npy`
- `final_mask_original.npy`
- `final_mask_views/`

Và kiểm tra:

- `target_spacing_xyz_mm`
- `input_spacing_xyz_mm`
- shape trước và sau resample trong `result.json`

## 8. Data contract quan trọng

### Quy ước axis

Ở tầng backend/sandbox, volume chuẩn là:

- `(X, Y, Z)`

Trong đó:

- `X`: trái-phải
- `Y`: trước-sau
- `Z`: axial slice index

DeepLung nội bộ sẽ tự chuyển sang `(Z, Y, X)` trong wrapper, nhưng API ngoài vẫn giữ `(X, Y, Z)`.

### Detector output

Detector trả:

- `candidates`
  - `center_xyz`
  - `score_logit`
  - `score_probability`
  - `diameter_mm`
- `debug`
- debug artifact cho preprocess/raw/post-NMS candidates

### Pipeline output

Pipeline trả:

- `final_mask_xyz`
- `final_mask_resampled_xyz`
- `probability_volume_resampled_xyz`
- `candidates`
- `candidate_debug_volumes`
- `component_stats`
- `debug`
- `detector_output`
- `segmentor_output`

## 9. Map nhanh code sau refactor

Nếu bạn muốn sửa nhanh đúng chỗ:

- sửa orchestration pipeline:
  - `backend/sandbox/nodule_mask_pipeline/pipeline.py`

- sửa detector stage / candidate processing / local filtering / mask post-process:
  - `backend/sandbox/nodule_mask_pipeline/stages.py`

- sửa data model/result/debug contract:
  - `backend/sandbox/nodule_mask_pipeline/models.py`

- sửa DeepLung wrapper:
  - `backend/sandbox/deeplung_detector.py`

- sửa TransAttUnet patch wrapper:
  - `backend/sandbox/transattunet_segmenter.py`

- sửa output artifact / visualization:
  - `backend/sandbox/modal_deeplung_test.py`
  - `backend/sandbox/modal_nodule_mask_test.py`

## 10. Ghi chú thực tế

- Các script sandbox chạy trên Modal GPU `A10G`.
- Dependency model inference được cài trong `modal.Image`, không cần cài local để chạy lệnh `modal run`.
- Nếu muốn hiểu sâu hơn về kiến trúc/refactor, đọc thêm:
  - `backend/sandbox/NODULE_MASK_PIPELINE_REPORT.md`
  - `backend/sandbox/checkpoints/README.md`

## 11. Lệnh mẫu nên dùng đầu tiên

### Kiểm tra detector

```bash
modal run backend/sandbox/modal_deeplung_test.py::main --volume-path dataset/3000522.000000-NA-04919 --output-path backend/sandbox/deeplung_result.json
```

### Kiểm tra full pipeline

```bash
modal run backend/sandbox/modal_nodule_mask_test.py::main --volume-path dataset/3000522.000000-NA-04919 --output-path backend/sandbox/nodule_mask_result.json
```

Nếu mục tiêu là debug vì sao final mask rỗng, hãy chạy full pipeline trước, sau đó mở lần lượt:

1. `result.json`
2. `candidates.json`
3. `detector_debug/`
4. `transattunet_raw_views/`
5. `filtered_local_views/`
6. `segmentor_debug/`
7. `final_mask_views/`
