from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import requests

from app.config import COMFYUI_BASE_URL, COMFYUI_POLL_INTERVAL_SECONDS, COMFYUI_TIMEOUT_SECONDS


class ComfyUIClientError(RuntimeError):
    """Raised when ComfyUI API interactions fail."""


class ComfyUIClient:
    def __init__(
        self,
        base_url: str = COMFYUI_BASE_URL,
        timeout_seconds: int = COMFYUI_TIMEOUT_SECONDS,
        poll_interval_seconds: float = COMFYUI_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}
        try:
            response = requests.post(
                f"{self.base_url}/prompt",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ComfyUIClientError(f"Failed to submit workflow to ComfyUI: {exc}") from exc

        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIClientError("ComfyUI response missing prompt_id.")
        return prompt_id

    def wait_for_completion(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout_seconds
        history_url = f"{self.base_url}/history/{prompt_id}"

        while time.time() < deadline:
            try:
                response = requests.get(history_url, timeout=self.timeout_seconds)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as exc:
                raise ComfyUIClientError(f"Failed polling ComfyUI history: {exc}") from exc

            if prompt_id in data:
                return data[prompt_id]

            time.sleep(self.poll_interval_seconds)

        raise ComfyUIClientError("ComfyUI workflow timed out waiting for completion.")

    def extract_output_filenames(self, history_entry: dict[str, Any]) -> list[str]:
        outputs = history_entry.get("outputs", {})
        filenames: list[str] = []

        for node_data in outputs.values():
            images = node_data.get("images", [])
            for image in images:
                filename = image.get("filename")
                if filename:
                    filenames.append(filename)

        return filenames

    def download_output_image(self, filename: str, destination_path: Path) -> Path:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        view_url = f"{self.base_url}/view"

        try:
            response = requests.get(
                view_url,
                params={"filename": filename},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ComfyUIClientError(f"Failed downloading ComfyUI output image: {exc}") from exc

        destination_path.write_bytes(response.content)
        return destination_path
