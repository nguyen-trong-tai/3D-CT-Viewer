import modal

image = modal.Image.debian_slim().pip_install(
    "fastapi",
    "uvicorn",
    "python-multipart",
    "numpy",
    "pydicom",
    "nibabel",
    "scikit-image",
    "scipy",
    "trimesh",
    "pydantic"
)

app = modal.App("ct-to-3d-backend")

@app.function(image=image, gpu="any") # GPU accessible for future ML extensions
@modal.asgi_app()
def fastapi_app():
    from main import app as web_app
    return web_app
