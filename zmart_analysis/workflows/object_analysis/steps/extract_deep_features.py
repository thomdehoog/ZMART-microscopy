"""extract_deep_features -- optional DINO embeddings for object crops."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _contracts import to_builtin  # noqa: E402
from _object_crops import extract_object_crops  # noqa: E402


METADATA = {
    "description": "Extract optional DINO embeddings for object crops",
    "version": "1.0",
    "max_workers": 1,
    "environment": "SMART--object_analysis--vision",
}


def run(pipeline_data: dict, state: dict, **params) -> dict:
    inp = pipeline_data["input"]
    backend = _setting(inp, params, "backend", "dinov2")
    input_intensity_scale = _normalize_intensity_scale(
        _setting(inp, params, "input_intensity_scale", None)
    )
    min_eccentricity = params.get("min_eccentricity_to_align", 0.4)
    crop_result = extract_object_crops(
        image=pipeline_data["detect_objects"].get(
            "image", pipeline_data["detect_objects"]["image_2d"]
        ),
        masks=pipeline_data["detect_objects"]["masks"],
        tile_id=inp["tile_id"],
        crop_size_px=int(params.get("crop_size_px", 128)),
        mask=bool(params.get("mask", False)),
        drop_incomplete=bool(params.get("drop_incomplete_crops", True)),
        align_orientation=bool(params.get("align_orientation", False)),
        min_eccentricity_to_align=(
            0.4 if min_eccentricity is None else float(min_eccentricity)
        ),
        output_dir=_setting(inp, params, "output_dir", None),
    )
    objects = list(crop_result["objects"])
    labels = [int(obj["label"]) for obj in objects]

    if backend == "mock":
        vectors = _mock_embeddings(
            objects,
            dim=int(_setting(inp, params, "embedding_dim", 8)),
        )
        model_name = "mock"
        embedding_metadata = {}
    elif backend == "dinov2":
        model_name = _setting(inp, params, "model_name", "dinov2_vitb14")
        model_cache_dir = _setting(inp, params, "model_cache_dir", None)
        input_size_px = int(_setting(inp, params, "input_size_px", 224))
        batch_size = int(_setting(inp, params, "batch_size", 8))
        vectors = _dinov2_embeddings(
            objects,
            state,
            model_name=model_name,
            input_size_px=input_size_px,
            batch_size=batch_size,
            device=_setting(inp, params, "device", None),
            disable_xformers=bool(_setting(inp, params, "disable_xformers", True)),
            model_cache_dir=model_cache_dir,
            input_intensity_scale=input_intensity_scale,
        )
        embedding_metadata = {
            "input_size_px": input_size_px,
            "batch_size": batch_size,
            "patch_size_px": DINO_PATCH_SIZES["dinov2"],
            "model_cache_dir": str(model_cache_dir) if model_cache_dir else "",
            "input_intensity_scale": _intensity_scale_metadata(input_intensity_scale),
        }
    elif backend == "dinov3":
        model_name = _setting(
            inp, params, "model_name", "dinov3_vitb16"
        )
        model_cache_dir = _setting(inp, params, "model_cache_dir", None)
        input_size_px = int(_setting(inp, params, "input_size_px", 256))
        batch_size = int(_setting(inp, params, "batch_size", 8))
        vectors = _dinov3_embeddings(
            objects,
            state,
            model_name=model_name,
            input_size_px=input_size_px,
            batch_size=batch_size,
            device=_setting(inp, params, "device", None),
            model_cache_dir=model_cache_dir,
            input_intensity_scale=input_intensity_scale,
        )
        embedding_metadata = {
            "input_size_px": input_size_px,
            "batch_size": batch_size,
            "patch_size_px": DINO_PATCH_SIZES["dinov3"],
            "model_cache_dir": str(model_cache_dir) if model_cache_dir else "",
            "input_intensity_scale": _intensity_scale_metadata(input_intensity_scale),
        }
    else:
        raise ValueError("backend must be 'mock', 'dinov2', or 'dinov3'.")

    pipeline_data["extract_deep_features"] = {
        "embeddings": to_builtin({
            "label": labels,
            "vectors": vectors,
            "model": model_name,
            "backend": backend,
            "crop_policy": crop_result.get("crop_policy", {}),
            **embedding_metadata,
        }),
        "objects": to_builtin([
            {
                key: value
                for key, value in obj.items()
                if key not in {"crop_image", "crop_mask"}
            }
            for obj in objects
        ]),
        "tile_artifacts": to_builtin(crop_result.get("tile_artifacts", {})),
    }
    return pipeline_data


DINO_PATCH_SIZES = {
    "dinov2": 14,
    "dinov3": 16,
}

DINOV3_HF_TO_HUB = {
    "facebook/dinov3-vits16-pretrain-lvd1689m": "dinov3_vits16",
    "facebook/dinov3-vits16plus-pretrain-lvd1689m": "dinov3_vits16plus",
    "facebook/dinov3-vitb16-pretrain-lvd1689m": "dinov3_vitb16",
    "facebook/dinov3-vitl16-pretrain-lvd1689m": "dinov3_vitl16",
    "facebook/dinov3-vith16plus-pretrain-lvd1689m": "dinov3_vith16plus",
    "facebook/dinov3-vit7b16-pretrain-lvd1689m": "dinov3_vit7b16",
}

DINOV3_HUB_TO_HF = {value: key for key, value in DINOV3_HF_TO_HUB.items()}

DINOV2_WEIGHT_FILES = {
    "dinov2_vits14": "dinov2_vits14_pretrain.pth",
    "dinov2_vitb14": "dinov2_vitb14_pretrain.pth",
    "dinov2_vitl14": "dinov2_vitl14_pretrain.pth",
    "dinov2_vitg14": "dinov2_vitg14_pretrain.pth",
    "dinov2_vits14_reg": "dinov2_vits14_reg4_pretrain.pth",
    "dinov2_vitb14_reg": "dinov2_vitb14_reg4_pretrain.pth",
    "dinov2_vitl14_reg": "dinov2_vitl14_reg4_pretrain.pth",
    "dinov2_vitg14_reg": "dinov2_vitg14_reg4_pretrain.pth",
}

DINOV3_WEIGHT_PATTERNS = {
    "dinov3_vits16": "dinov3_vits16_pretrain_lvd1689m-*.pth",
    "dinov3_vits16plus": "dinov3_vits16plus_pretrain_lvd1689m-*.pth",
    "dinov3_vitb16": "dinov3_vitb16_pretrain_lvd1689m-*.pth",
    "dinov3_vitl16": "dinov3_vitl16_pretrain_lvd1689m-*.pth",
    "dinov3_vith16plus": "dinov3_vith16plus_pretrain_lvd1689m-*.pth",
    "dinov3_vit7b16": "dinov3_vit7b16_pretrain_lvd1689m-*.pth",
}


def _setting(inp: dict, params: dict, key: str, default):
    return inp[key] if key in inp else params.get(key, default)


def _mock_embeddings(objects: list[dict], *, dim: int) -> list[list[float]]:
    vectors = []
    for obj in objects:
        image = np.asarray(obj["crop_image"], dtype=float)
        mask = np.asarray(obj["crop_mask"], dtype=bool)
        values = image[mask] if mask.any() and image.ndim == 2 else image.reshape(-1)
        base = np.asarray([
            float(obj["label"]),
            float(values.mean()) if values.size else 0.0,
            float(values.std()) if values.size else 0.0,
            float(mask.sum()),
        ])
        if dim <= len(base):
            vector = base[:dim]
        else:
            vector = np.resize(base, dim)
        vectors.append(_l2_normalize(vector).tolist())
    return vectors


def _dinov2_embeddings(
    objects: list[dict],
    state: dict,
    *,
    model_name: str,
    input_size_px: int,
    batch_size: int,
    device,
    disable_xformers: bool,
    model_cache_dir,
    input_intensity_scale,
) -> list[list[float]]:
    if not objects:
        return []

    if disable_xformers:
        import os

        # DINOv2 runs correctly without xFormers. On some Windows Torch
        # environments, importing xFormers can raise a DLL-level fatal error,
        # so keep the optional acceleration off unless explicitly requested.
        os.environ.setdefault("XFORMERS_DISABLED", "1")

    import torch
    _configure_torch_home(torch, model_cache_dir, subdir="dinov2")
    _prepare_dinov2_local_checkpoint(model_name, model_cache_dir)

    if batch_size <= 0:
        raise ValueError("batch_size must be > 0.")
    _validate_input_size_px(input_size_px, backend="dinov2")

    device = device or _default_torch_device(torch)
    model_key = (model_name, device)
    if state.get("dinov2_model_key") != model_key:
        model = torch.hub.load("facebookresearch/dinov2", model_name)
        model.eval().to(device)
        state["dinov2_model"] = model
        state["dinov2_model_key"] = model_key
    model = state["dinov2_model"]

    vectors = []
    with torch.no_grad():
        for start in range(0, len(objects), batch_size):
            batch_objects = objects[start:start + batch_size]
            batch = _crop_batch(
                batch_objects,
                input_size_px,
                torch,
                input_intensity_scale=input_intensity_scale,
            ).to(device)
            features = _forward_dinov2(model, batch, torch)
            features = torch.nn.functional.normalize(features, p=2, dim=1)
            vectors.extend(features.cpu().numpy().astype(float).tolist())
    return vectors


def _dinov3_embeddings(
    objects: list[dict],
    state: dict,
    *,
    model_name: str,
    input_size_px: int,
    batch_size: int,
    device,
    model_cache_dir,
    input_intensity_scale,
) -> list[list[float]]:
    if not objects:
        return []

    import torch
    _configure_torch_home(torch, model_cache_dir, subdir="dinov3")

    if batch_size <= 0:
        raise ValueError("batch_size must be > 0.")
    _validate_input_size_px(input_size_px, backend="dinov3")

    device = device or _default_torch_device(torch)
    hub_name = _dinov3_hub_name(model_name)
    weights_path = _resolve_dinov3_weights(hub_name, model_cache_dir)
    model_key = (model_name, device, str(weights_path) if weights_path else "")
    if state.get("dinov3_model_key") != model_key:
        if weights_path is not None:
            model = _load_dinov3_torch_hub_model(torch, hub_name, weights_path)
        else:
            try:
                from transformers import AutoModel
            except ImportError as exc:
                raise ImportError(
                    "The dinov3 backend requires either local .pth weights in "
                    "model_cache_dir or the 'transformers' package in the "
                    "SMART--object_analysis--vision environment."
                ) from exc
            model = AutoModel.from_pretrained(DINOV3_HUB_TO_HF.get(hub_name, model_name))
        model.eval().to(device)
        state["dinov3_model"] = model
        state["dinov3_model_key"] = model_key
    model = state["dinov3_model"]

    vectors = []
    with torch.inference_mode():
        for start in range(0, len(objects), batch_size):
            batch_objects = objects[start:start + batch_size]
            batch = _crop_batch(
                batch_objects,
                input_size_px,
                torch,
                input_intensity_scale=input_intensity_scale,
            ).to(device)
            features = _forward_dinov3(model, batch, torch)
            features = torch.nn.functional.normalize(features, p=2, dim=1)
            vectors.extend(features.cpu().numpy().astype(float).tolist())
    return vectors


def _validate_input_size_px(input_size_px: int, *, backend: str):
    if input_size_px <= 0:
        raise ValueError("input_size_px must be > 0.")
    patch_size = DINO_PATCH_SIZES[backend]
    if input_size_px % patch_size:
        raise ValueError(
            f"{backend} input_size_px must be a multiple of its patch size "
            f"({patch_size}); got {input_size_px}."
        )


def _configure_torch_home(torch, model_cache_dir, *, subdir: str):
    if not model_cache_dir:
        return None
    cache_root = Path(model_cache_dir) / subdir / "torch_hub"
    cache_root.mkdir(parents=True, exist_ok=True)
    torch.hub.set_dir(str(cache_root))
    return cache_root


def _prepare_dinov2_local_checkpoint(model_name: str, model_cache_dir):
    if not model_cache_dir:
        return None
    filename = DINOV2_WEIGHT_FILES.get(str(model_name))
    if filename is None:
        return None
    base = Path(model_cache_dir)
    target = base / "dinov2" / "torch_hub" / "checkpoints" / filename
    if target.exists() and target.stat().st_size > 0:
        return target

    candidates = (
        base / "v2" / filename,
        base / "dinov2" / filename,
        base / filename,
    )
    source = next(
        (
            path
            for path in candidates
            if path.exists()
            and path.is_file()
            and not path.name.endswith(".part")
            and path.stat().st_size > 0
        ),
        None,
    )
    if source is None:
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    return target


def _dinov3_hub_name(model_name: str) -> str:
    model_name = str(model_name)
    return DINOV3_HF_TO_HUB.get(model_name, model_name)


def _resolve_dinov3_weights(model_name: str, model_cache_dir):
    if not model_cache_dir:
        return None
    pattern = DINOV3_WEIGHT_PATTERNS.get(model_name)
    if pattern is None:
        return None
    base = Path(model_cache_dir)
    search_dirs = [base / "dinov3", base / "v3", base]
    candidates = []
    for directory in search_dirs:
        if directory.exists():
            candidates.extend(path for path in directory.glob(pattern) if path.is_file())
    candidates = [path for path in candidates if not path.name.endswith(".part") and path.stat().st_size > 0]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]


def _load_dinov3_torch_hub_model(torch, hub_name: str, weights_path: Path):
    """Load a DINOv3 hub architecture and apply local weights directly.

    DINOv3's hub helper converts local paths to file:// URLs before loading
    weights. That breaks for mapped network drives on Windows, so local .pth
    files are loaded with torch.load and applied to a pretrained=False model.
    """
    model = torch.hub.load(
        "facebookresearch/dinov3",
        hub_name,
        pretrained=False,
    )
    state_dict = _load_torch_state_dict(torch, weights_path)
    model.load_state_dict(state_dict, strict=True)
    return model


def _load_torch_state_dict(torch, weights_path: Path):
    try:
        state = torch.load(str(weights_path), map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(str(weights_path), map_location="cpu")

    if not isinstance(state, dict):
        raise ValueError(f"DINOv3 weights at {weights_path} did not contain a state dict.")

    for key in ("state_dict", "model", "teacher"):
        nested = state.get(key)
        if isinstance(nested, dict):
            state = nested
            break

    if state and all(isinstance(key, str) and key.startswith("module.") for key in state):
        state = {key.removeprefix("module."): value for key, value in state.items()}

    return state


def _default_torch_device(torch) -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _crop_batch(objects: list[dict], input_size_px: int, torch, *, input_intensity_scale=None):
    tensors = []
    for obj in objects:
        rgb = _as_rgb(np.asarray(obj["crop_image"]))
        rgb = _raw_image_to_float01(rgb, intensity_scale=input_intensity_scale)
        tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).float().unsqueeze(0)
        tensor = torch.nn.functional.interpolate(
            tensor,
            size=(input_size_px, input_size_px),
            mode="bilinear",
            align_corners=False,
        )
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        tensors.append((tensor - mean) / std)
    return torch.cat(tensors, dim=0)


def _forward_dinov2(model, batch, torch):
    if hasattr(model, "forward_features"):
        features = model.forward_features(batch)
        if isinstance(features, dict):
            if "x_norm_clstoken" in features:
                return features["x_norm_clstoken"]
            if "x_norm_patchtokens" in features:
                return features["x_norm_patchtokens"].mean(dim=1)
        return features
    return model(batch)


def _forward_dinov3(model, batch, torch):
    if hasattr(model, "forward_features"):
        features = model.forward_features(batch)
        if isinstance(features, dict):
            if "x_norm_clstoken" in features:
                return features["x_norm_clstoken"]
            if "x_norm_patchtokens" in features:
                return features["x_norm_patchtokens"].mean(dim=1)
        return features
    try:
        outputs = model(pixel_values=batch)
    except TypeError:
        outputs = model(batch)
    pooled = getattr(outputs, "pooler_output", None)
    if pooled is not None:
        return pooled
    hidden = getattr(outputs, "last_hidden_state", None)
    if hidden is None and isinstance(outputs, dict):
        hidden = outputs.get("last_hidden_state")
    if hidden is None and isinstance(outputs, (tuple, list)) and outputs:
        hidden = outputs[0]
    if hidden is None:
        raise RuntimeError("DINOv3 model output did not contain a CLS representation.")
    return hidden[:, 0, :]


def _as_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return np.repeat(image[:, :, None], 3, axis=2)
    if image.ndim == 3:
        if image.shape[0] <= 4 and image.shape[2] > 4:
            raise ValueError(
                f"Cannot convert crop with shape {image.shape} to RGB. "
                "Expected a 2D crop or a channel-last 2D+channels crop."
            )
        n_channels = image.shape[2]
        if n_channels >= 3:
            return image[:, :, :3]
        if n_channels == 2:
            first_two = image[:, :, :2]
            if np.issubdtype(first_two.dtype, np.integer):
                mean_fill = (
                    first_two.astype(np.float32).mean(axis=2, keepdims=True)
                    .round()
                    .astype(first_two.dtype)
                )
            else:
                mean_fill = first_two.mean(axis=2, keepdims=True)
            return np.concatenate([first_two, mean_fill], axis=2)
        if n_channels >= 1:
            pad = np.repeat(image[:, :, -1:], 3 - n_channels, axis=2)
            return np.concatenate([image, pad], axis=2)
    raise ValueError(
        f"Cannot convert crop with shape {image.shape} to RGB. "
        "Expected a 2D crop or a channel-last 2D+channels crop."
    )


def _raw_image_to_float01(image: np.ndarray, *, intensity_scale=None) -> np.ndarray:
    if intensity_scale is not None:
        scale = _normalize_intensity_scale(intensity_scale)
        image = image.astype(np.float32, copy=False)
        if image.ndim == 2:
            lo = scale["lo"][0]
            hi = scale["hi"][0]
        elif image.ndim == 3:
            lo = scale["lo"][:image.shape[-1]].reshape(1, 1, -1)
            hi = scale["hi"][:image.shape[-1]].reshape(1, 1, -1)
        else:
            raise ValueError(
                f"Cannot scale DINO crop with shape {image.shape}. "
                "Expected a 2D or channel-last crop."
            )
        return np.clip((image - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)

    if image.dtype == np.bool_:
        return image.astype(np.float32)
    if np.issubdtype(image.dtype, np.integer):
        info = np.iinfo(image.dtype)
        return (image.astype(np.float32) / float(info.max)).astype(np.float32)
    image = image.astype(np.float32, copy=False)
    if image.size and (float(image.min()) < 0.0 or float(image.max()) > 1.0):
        raise ValueError(
            "Float DINO crop images must already be in [0, 1]. "
            "Apply any intensity normalization in an upstream preprocessing step."
        )
    return image


def _normalize_intensity_scale(scale):
    if scale is None or scale is False or (isinstance(scale, str) and not scale):
        return None
    if not isinstance(scale, dict):
        raise ValueError("input_intensity_scale must be a dict with 'lo' and 'hi' values.")
    if "lo" not in scale or "hi" not in scale:
        raise ValueError("input_intensity_scale must contain 'lo' and 'hi'.")

    lo = np.asarray(scale["lo"], dtype=np.float32).reshape(-1)
    hi = np.asarray(scale["hi"], dtype=np.float32).reshape(-1)
    if lo.size == 0 or hi.size == 0:
        raise ValueError("input_intensity_scale 'lo' and 'hi' cannot be empty.")
    if lo.size == 1:
        lo = np.repeat(lo, 3)
    if hi.size == 1:
        hi = np.repeat(hi, 3)
    if lo.size < 3:
        lo = np.pad(lo, (0, 3 - lo.size), mode="edge")
    if hi.size < 3:
        hi = np.pad(hi, (0, 3 - hi.size), mode="edge")
    lo = lo[:3]
    hi = hi[:3]
    bad = hi <= lo
    if np.any(bad):
        hi = hi.copy()
        hi[bad] = lo[bad] + 1.0
    return {
        "mode": str(scale.get("mode", "shared_foreground")),
        "foreground": bool(scale.get("foreground", False)),
        "lo": lo,
        "hi": hi,
    }


def _intensity_scale_metadata(scale):
    if scale is None:
        return {"mode": "dtype_max"}
    return {
        "mode": scale["mode"],
        "foreground": bool(scale.get("foreground", False)),
        "lo": [float(v) for v in scale["lo"]],
        "hi": [float(v) for v in scale["hi"]],
    }


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector.astype(float)
    return (vector / norm).astype(float)
