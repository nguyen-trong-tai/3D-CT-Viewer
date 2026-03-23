# Migration Blueprint: Modal Volume -> Cloudflare R2 + Redis

## Muc tieu

Tai lieu nay mo ta cach tai cau truc backend hien tai de chuyen tu mo hinh luu tru file tren Modal Volume sang:

- Cloudflare R2 cho object storage
- Redis cho state, progress, queue, lock, batch session

Blueprint nay duoc viet dua tren code hien tai trong repo, dac biet la:

- `backend/storage/repository.py`
- `backend/api/routers/cases.py`
- `backend/api/routers/ct_data.py`
- `backend/api/routers/processing.py`
- `backend/api/routers/mesh.py`
- `backend/services/pipeline.py`
- `backend/modal_app.py`
- `backend/config.py`

Tai lieu nay khong chua code. Muc tieu la dua ra structure dich, cac buoc migration, va danh sach nhung phan nen giu, doi, tach, hoac loai bo.

---

## 1. Hien trang kien truc

Backend hien tai dang theo mo hinh:

- `CaseRepository` vua la repository, vua la file store, vua la status store
- Trang thai case duoc luu trong `status.json`
- CT, mask, SDF, mesh duoc luu thanh file trong folder case
- API routers goi truc tiep repository va tu xu ly nhieu chi tiet storage/runtime
- `modal_app.py` dang vua lo deploy worker, vua lam cau noi de commit/reload volume

### Storage layout hien tai

Moi case dang co dang:

```text
{STORAGE_ROOT}/{case_id}/
  status.json
  ct_volume.npy
  ct_metadata.json
  extra_metadata.json
  mask_volume.npy
  sdf_volume.npy
  mesh.glb
```

### Van de chinh

- File system dang la abstraction trung tam, khien doi storage kho
- API layer biet qua nhieu ve Modal
- `repository.py` chiu qua nhieu trach nhiem
- `status` dang la derived state tu file local
- Batch session dang de trong memory process, khong ben vung
- `mmap` local file la pattern doc chinh, khong phu hop neu artifact nam o R2

---

## 2. Nguyen tac thiet ke dich

Sau migration, backend nen theo 4 lop ro rang:

1. `api/`
   Nhan request, validate input, goi service, tra response

2. `services/`
   Orchestrate workflow upload/process/delete/read artifact

3. `storage/`
   Cung cap abstraction luu tru:
   - object store
   - state store
   - temp local cache

4. `processing/`
   Compute thuan: parse DICOM/NIfTI, segment, tinh SDF, tao mesh, convert GLB

### Vai tro cua tung he thong

- `Cloudflare R2`
  - Luu artifact lon
  - Luu metadata JSON dang object neu can
  - Nguon su that cho artifact da tao

- `Redis`
  - Luu status, progress, pipeline stage
  - Luu batch upload session
  - Luu queue, lock, runtime state
  - Nguon su that cho operational state

- `Temp local disk`
  - Luu file tam trong worker luc dang upload/parse/process
  - Khong phai noi luu chinh

---

## 3. Cau truc project de xuat

Co the chuyen backend ve dang:

```text
backend/
  api/
    routers/
      cases.py
      ct_data.py
      mesh.py
      processing.py
    dependencies.py
    router.py

  core/
    config.py
    enums.py
    exceptions.py

  domain/
    schemas.py
    models.py

  processing/
    loader.py
    segmentation.py
    sdf.py
    mesh.py
    glb_converter.py

  services/
    case_service.py
    upload_service.py
    pipeline_service.py
    artifact_service.py

  storage/
    object_store/
      base.py
      r2.py
    state_store/
      base.py
      redis.py
    temp_store/
      local_temp.py
    repositories/
      case_repository.py
      artifact_repository.py

  workers/
    modal_worker.py

  MIGRATION_BLUEPRINT_R2_REDIS.md
```

### Giai thich nhanh

- `core/`
  Chua config, enum, exception dung chung

- `domain/`
  Chua schema/model nghiep vu

- `storage/object_store/`
  Adapter cho R2

- `storage/state_store/`
  Adapter cho Redis

- `storage/temp_store/`
  Quan ly thu muc temp local

- `storage/repositories/`
  Ghep object store + state store thanh abstraction nghiep vu

- `workers/`
  Chua code dac thu runtime nhu Modal

---

## 4. Data model de xuat

## 4.1 Artifact trong R2

Su dung convention key:

```text
cases/{case_id}/ct/volume.npy
cases/{case_id}/ct/metadata.json
cases/{case_id}/meta/extra_metadata.json
cases/{case_id}/mask/volume.npy
cases/{case_id}/sdf/volume.npy
cases/{case_id}/mesh/reconstruction.glb
```

Co the bo sung:

```text
cases/{case_id}/uploads/source.zip
cases/{case_id}/uploads/manifest.json
cases/{case_id}/logs/pipeline.json
```

### Nguyen tac

- Key naming on dinh ngay tu dau
- Khong dua runtime temp vao key persistent
- Co the overwrite artifact theo version neu workflow don gian
- Neu can audit/retry sau nay, bo sung `runs/{run_id}/...`

## 4.2 State trong Redis

De xuat namespace:

```text
case:{case_id}:status
case:{case_id}:pipeline
case:{case_id}:artifacts
case:{case_id}:lock:processing
batch:{case_id}
queue:case-processing
```

### Gia tri luu trong Redis

`case:{case_id}:status`

- status
- message
- created_at
- updated_at
- current_stage
- progress_percent

`case:{case_id}:pipeline`

- load_volume
- segmentation
- sdf
- mesh
- started_at
- finished_at
- error

`case:{case_id}:artifacts`

- ct_volume = true/false
- ct_metadata = true/false
- extra_metadata = true/false
- mask = true/false
- sdf = true/false
- mesh = true/false
- mesh_key
- ct_key
- mask_key

### Khong nen luu trong Redis

- File `.npy`
- GLB binary
- DICOM raw bytes lon
- SDF raw data

---

## 5. Mapping tu code hien tai sang code moi

## 5.1 `backend/storage/repository.py`

### Hien tai

- Chua tat ca logic:
  - create/delete case
  - update/get status
  - save/load CT
  - save/load mask
  - save/load SDF
  - save/load mesh
  - artifact existence

### Van de

- Coupling rat chat voi filesystem
- Khong tach object storage va state store
- Kho test va kho thay implementation

### Dinh huong moi

Tach thanh:

- `storage/object_store/base.py`
- `storage/object_store/r2.py`
- `storage/state_store/base.py`
- `storage/state_store/redis.py`
- `storage/repositories/case_repository.py`

### Nen loai bo hoac giam vai tro

- `_case_dir`
- `_save_json`, `_load_json` theo file-local
- `get_mesh_path`
- `*.exists()` dua tren local path
- Tu duy "case ton tai = folder ton tai"

## 5.2 `backend/api/routers/cases.py`

### Hien tai

File nay dang:

- tao case
- validate upload
- ghi temp file
- quan ly batch session
- update status
- quyet dinh local background hay Modal worker
- commit/reload Modal volume

### Van de

- Router qua day logic
- Chua runtime-specific helper
- `_batch_sessions` la in-memory state

### Dinh huong moi

Giu router chi con:

- nhan request
- goi `CaseService` / `UploadService`
- tra response

### Nen tach ra

- `process_single_upload_task`
- `process_dicom_directory_task`
- `_batch_sessions`
- `is_running_in_modal`
- `_commit_if_modal`
- `_reload_if_modal`

## 5.3 `backend/api/routers/processing.py`

### Hien tai

- trigger pipeline
- doc mask
- doc SDF status
- chua helper Modal

### Dinh huong moi

- Router chi goi `PipelineService`
- Stage status doc tu Redis
- Artifact doc tu `ArtifactService`

### Nen bo

- `_reload_if_modal`
- logic branch local/Modal trong router

## 5.4 `backend/api/routers/ct_data.py`

### Hien tai

- doc CT full volume
- doc single slice bang `mmap`
- doc metadata va extra metadata

### Dinh huong moi

- Metadata co the doc tu Redis hoac R2 JSON
- Full volume co the stream tu backend sau khi doc R2, hoac tra presigned URL
- Slice endpoint can dung local temp cache hoac design lai

### Can xem xet lai

- `load_ct_volume_mmap`
- response strategy cho artifact lon

## 5.5 `backend/api/routers/mesh.py`

### Hien tai

- tra `FileResponse` truc tiep tu local path

### Dinh huong moi

Co 2 huong:

1. Backend proxy/stream file tu R2
2. Backend tra presigned URL tu R2

De clean va scale tot hon, uu tien presigned URL cho mesh.

## 5.6 `backend/services/pipeline.py`

### Hien tai

- pipeline logic hop ly
- nhung state progression dang dua nhieu vao artifact existence

### Dinh huong moi

- van giu pipeline orchestration tai day
- nhung status stage phai ghi truc tiep vao Redis
- artifact sau moi stage phai upload len R2
- local disk chi la workspace tam

### Nen doi

- `get_pipeline_status()` khong suy dien chu yeu tu file existence
- `mask_exists`, `sdf_exists`, `mesh_exists` nen tro thanh artifact manifest check

## 5.7 `backend/modal_app.py`

### Hien tai

- deployment + GPU job + upload processors + volume bridge

### Dinh huong moi

- chi con worker runtime cho Modal
- khong con commit/reload data volume cho artifact
- chi set env, warm model, goi service/process worker

### Nen loai bo

- `data_volume`
- logic `commit()` / `reload()` de dong bo artifact

## 5.8 `backend/config.py`

### Hien tai

- lay `STORAGE_ROOT` lam trung tam
- co side effect `mkdir`

### Dinh huong moi

Tach thanh config:

- app
- temp storage
- R2
- Redis
- processing

### Bien moi de xuat

- `TEMP_STORAGE_ROOT`
- `R2_ACCOUNT_ID`
- `R2_BUCKET`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_PUBLIC_BASE_URL`
- `REDIS_URL`
- `REDIS_KEY_PREFIX`

---

## 6. Service design de xuat

## 6.1 `CaseService`

Trach nhiem:

- create/delete case
- get case status
- list artifacts
- clear state + object khi delete

## 6.2 `UploadService`

Trach nhiem:

- nhan upload
- ghi temp local
- parse source file neu can
- dua artifact chuan len R2
- update Redis state
- quan ly batch upload session bang Redis

## 6.3 `PipelineService`

Trach nhiem:

- start pipeline
- lock case
- cap nhat stage status vao Redis
- doc input artifact tu R2
- xu ly local
- upload output artifact len R2

## 6.4 `ArtifactService`

Trach nhiem:

- lay metadata artifact
- tra presigned URL hoac stream
- resolve object key tu artifact type

---

## 7. Endpoint strategy de xuat

## 7.1 Endpoints nen doc Redis

- `GET /cases/{case_id}/status`
- `GET /cases/{case_id}/pipeline`
- `GET /cases/{case_id}/artifacts`

## 7.2 Endpoints nen doc R2 hoac tra presigned URL

- `GET /cases/{case_id}/mesh`
- `GET /cases/{case_id}/ct/volume`
- `GET /cases/{case_id}/mask/volume`

## 7.3 Endpoints can can nhac ky

- `GET /cases/{case_id}/ct/slices/{index}`
- `GET /cases/{case_id}/mask/slices/{index}`

Ly do:

- Hien tai phu thuoc vao `mmap` local
- R2 khong hop cho random slice access theo kieu nay neu khong co cache

### 3 lua chon

1. Giu endpoint slice, nhung moi request tai artifact ve temp cache roi cat slice
2. Precompute slice/tile va luu rieng
3. Giam vai tro endpoint slice, frontend tu load full volume khi hop ly

Khuyen nghi:

- Giai doan migration dau: giu endpoint, dung local temp cache
- Giai doan sau moi toi uu them

---

## 8. Temp storage strategy

Du khong con Modal volume la storage chinh, ban van can local temp storage.

De xuat:

- `TEMP_STORAGE_ROOT=/tmp/viewr_ct` tren Linux/Modal
- temp folder tach theo:
  - upload temp
  - processing workspace
  - cache artifact

```text
{TEMP_STORAGE_ROOT}/uploads/
{TEMP_STORAGE_ROOT}/processing/{case_id}/
{TEMP_STORAGE_ROOT}/cache/{case_id}/
```

### Nguyen tac

- Temp file phai co cleanup policy
- Khong co gia tri business quan trong tren local temp
- Worker co the xoa bat ky luc nao sau khi dong bo len R2

---

## 9. Queue, lock, va batch session

## 9.1 Queue

Neu ban muon worker poll job, Redis co the luu:

- `queue:case-processing`

Mỗi item gom:

- case_id
- requested_at
- parameters

Neu van dung co che spawn cua Modal, queue co the khong can o phase 1.

## 9.2 Lock

Can co lock de tranh 2 pipeline chay cung 1 case:

- `case:{case_id}:lock:processing`

Lock nen co TTL de tranh deadlock khi worker crash.

## 9.3 Batch session

Thay vi `_batch_sessions` trong memory process, dua sang Redis:

- `batch:{case_id}`

Thong tin:

- temp upload manifest
- files_received
- expected_files
- created_at

Set TTL cho batch session.

---

## 10. Rollout plan de xuat

## Phase 0 - Chuan hoa abstraction

Muc tieu:

- tach service va storage interface
- giu behavior cu

Viec can lam:

- tach `CaseRepository` thanh abstraction tot hon
- day logic khoi router
- gom Modal-specific code vao `workers/`

## Phase 1 - Dua Redis vao truoc

Muc tieu:

- status/pipeline/artifacts khong con dua vao `status.json`

Viec can lam:

- tao `RedisStateStore`
- `status`, `pipeline`, `batch session`, `lock` chay bang Redis
- file artifact van tam thoi de local/Modal volume

Ket qua:

- thay doi operational state truoc
- giam coupling nhieu nhat o API va pipeline

## Phase 2 - Dua R2 vao artifact layer

Muc tieu:

- artifact duoc luu vao R2

Viec can lam:

- tao `R2ObjectStore`
- upload CT metadata, mask, SDF, mesh len R2
- endpoint mesh/full volume bat dau doc tu R2

## Phase 3 - Bo shared Modal volume

Muc tieu:

- Modal volume khong con la data store chinh

Viec can lam:

- bo `data_volume`
- bo commit/reload logic
- local temp chi la workspace ngan han

## Phase 4 - Toi uu hoa

Muc tieu:

- toi uu chi phi va hieu nang

Viec can lam:

- presigned URL cho mesh/full volume
- cache local cho slice endpoint
- lifecycle cleanup cho R2
- cleanup batch/temp state trong Redis

---

## 11. Danh sach file nen sua, doi ten, them moi

## 11.1 Nen sua manh

- `backend/storage/repository.py`
- `backend/api/routers/cases.py`
- `backend/api/routers/processing.py`
- `backend/api/routers/ct_data.py`
- `backend/api/routers/mesh.py`
- `backend/services/pipeline.py`
- `backend/modal_app.py`
- `backend/config.py`
- `backend/api/dependencies.py`
- `backend/README.md`

## 11.2 Nen them moi

- `backend/storage/object_store/base.py`
- `backend/storage/object_store/r2.py`
- `backend/storage/state_store/base.py`
- `backend/storage/state_store/redis.py`
- `backend/storage/temp_store/local_temp.py`
- `backend/storage/repositories/case_repository.py`
- `backend/services/case_service.py`
- `backend/services/upload_service.py`
- `backend/services/artifact_service.py`
- `backend/workers/modal_worker.py`

## 11.3 Co the xoa sau khi migration on dinh

- file-based helper gan chat voi local path trong `repository.py`
- `_batch_sessions` in-memory
- helper `is_running_in_modal`, `_commit_if_modal`, `_reload_if_modal` trong routers
- moi assumption "artifact ton tai vi file ton tai tren local disk"

---

## 12. Danh sach cleanup cu the theo file

## `backend/storage/repository.py`

Loai bo hoac thay the:

- path-centric methods
- local file JSON persistence la state store chinh
- `get_mesh_path()`
- `case_exists()` dua tren folder

Giu lai ve y tuong:

- interface nghiep vu muc cao `save/load/update/list/delete`

## `backend/api/routers/cases.py`

Loai bo:

- in-memory batch session
- runtime detection
- Modal volume sync helper
- background task implementation chi tiet

Giu lai:

- contract API

## `backend/api/routers/processing.py`

Loai bo:

- runtime-specific branch logic trong endpoint

Giu lai:

- process trigger endpoint
- status endpoint contract

## `backend/api/routers/mesh.py`

Loai bo:

- phu thuoc `FileResponse` tu local path la cach duy nhat

Giu lai:

- endpoint contract `/cases/{case_id}/mesh`

## `backend/modal_app.py`

Loai bo:

- storage bridge dua tren Modal volume

Giu lai:

- warm model
- GPU worker runtime
- deployment config

---

## 13. Risks can chu y

## 13.1 Slice access se thay doi dac tinh hieu nang

Khi bo local filesystem la storage chinh, doc 1 slice ngau nhien se khong con re nhu `mmap`.

Can chap nhan:

- tam thoi cham hon
- hoac them local cache
- hoac doi response strategy

## 13.2 Nhat quan state

Neu upload artifact len R2 thanh cong nhung update Redis that bai, se sinh state lech.

Khuyen nghi:

- artifact upload xong moi commit manifest/status
- retry co kiem soat
- log ro moi stage

## 13.3 Delete case

Xoa case gio la xoa tren 2 he thong:

- R2 object prefix
- Redis keys

Can co service delete tap trung, khong de endpoint xoa le tung noi.

## 13.4 Batch upload dang do

Neu upload chunk dang do, can TTL va cleanup policy cho:

- batch session trong Redis
- temp files local

---

## 14. Khuyen nghi implementation thu tu thuc te

Neu muon di an toan va it vo code nhat, lam theo thu tu:

1. Tach logic khoi routers
2. Dua Redis vao cho status, pipeline, batch session, lock
3. Giu artifact tren local trong giai doan ngan
4. Dua mesh sang R2 truoc
5. Dua CT/mask/SDF sang R2 sau
6. Chuyen endpoint mesh sang presigned URL
7. Sau cung moi bo Modal volume

Ly do:

- Mesh la artifact doc don gian nhat khi dua len R2
- `status/pipeline` la phan de tach nhat sang Redis
- CT/mask slice endpoints la phan nhay cam nhat nen de sau

---

## 15. Definition of done

Migration duoc xem la hoan tat khi:

- Khong con artifact business-critical nam tren Modal volume
- Status va pipeline state duoc doc tu Redis
- Artifact duoc doc tu R2 hoac qua presigned URL
- Routers khong con helper Modal-specific
- `processing/` khong phu thuoc storage/runtime
- Batch session khong con nam trong memory process
- `repository` khong con path-centric monolith

---

## 16. Checklist thao tac

- [ ] Tach `config` thanh app/temp/R2/Redis settings
- [ ] Tạo abstraction cho object store
- [ ] Tạo abstraction cho state store
- [ ] Dua batch session sang Redis
- [ ] Dua case status sang Redis
- [ ] Dua pipeline stage status sang Redis
- [ ] Refactor router de goi service thay vi lam viec truc tiep voi storage/runtime
- [ ] Tạo temp local store rieng
- [ ] Dua mesh artifact sang R2
- [ ] Dua CT metadata sang R2 hoac Redis manifest
- [ ] Dua CT/mask/SDF artifact sang R2
- [ ] Refactor delete case thanh xoa dong bo R2 + Redis
- [ ] Bo logic Modal volume commit/reload
- [ ] Cap nhat README backend

---

## 17. Mot huong chia task cho refactor

Neu lam theo pull request nho, co the chia:

### PR 1

- Tach service layer ra khoi routers
- Chua thay storage backend

### PR 2

- Them Redis state store
- Chuyen status/pipeline/batch session sang Redis

### PR 3

- Them R2 object store
- Chuyen mesh sang R2

### PR 4

- Chuyen CT/mask/SDF sang R2
- Them local temp cache

### PR 5

- Xoa Modal volume coupling
- Don dep docs/config/dependencies

---

## 18. Ket luan

Refactor nay khong chi la doi noi luu file. Day la viec tach backend thanh:

- compute layer sach
- storage layer thay duoc implementation
- runtime layer tach biet
- API layer mong

Neu lam dung thu tu, ban co the migration dan dan ma khong can rewrite toan bo pipeline.
