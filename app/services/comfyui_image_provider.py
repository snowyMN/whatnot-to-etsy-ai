from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import IMAGE_EDITOR_MODEL
from app.services.comfyui_client import ComfyUIClient, ComfyUIClientError
from app.services.image_editing_provider import (
    ImageEditRequest,
    ImageEditResult,
    ImageEditingProvider,
    ImageEditingProviderError,
)


class ComfyUIImageEditingProvider(ImageEditingProvider):
    def __init__(
        self,
        workflow_template_path: str,
        output_dir: str,
        model: str = IMAGE_EDITOR_MODEL,
        client: ComfyUIClient | None = None,
    ) -> None:
        self.workflow_template_path = Path(workflow_template_path)
        self.output_dir = Path(output_dir)
        self.model = model
        self.client = client or ComfyUIClient()

    def _load_template(self) -> dict[str, Any]:
        if not self.workflow_template_path.exists():
            raise ImageEditingProviderError(
                f"ComfyUI workflow template not found: {self.workflow_template_path}"
            )

        try:
            return json.loads(self.workflow_template_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ImageEditingProviderError(
                f"Invalid ComfyUI workflow JSON: {exc}"
            ) from exc

    def _inject_template_fields(self, workflow: dict[str, Any], request: ImageEditRequest) -> dict[str, Any]:
        # Expected template structure:
        # workflow["meta"]["app_placeholders"] with keys:
        # source_image_node, source_image_input_key, prompt_node, prompt_input_key,
        # width_node, width_input_key, height_node, height_input_key
        meta = workflow.get("meta", {})
        placeholders = meta.get("app_placeholders", {})

        required_keys = [
            "source_image_node",
            "source_image_input_key",
            "prompt_node",
            "prompt_input_key",
            "width_node",
            "width_input_key",
            "height_node",
            "height_input_key",
        ]

        missing = [key for key in required_keys if key not in placeholders]
        if missing:
            raise ImageEditingProviderError(
                "ComfyUI workflow template missing required placeholder keys: "
                + ", ".join(missing)
            )

        source_node = str(placeholders["source_image_node"])
        prompt_node = str(placeholders["prompt_node"])
        width_node = str(placeholders["width_node"])
        height_node = str(placeholders["height_node"])

        if source_node not in workflow or prompt_node not in workflow:
            raise ImageEditingProviderError("ComfyUI workflow nodes referenced in placeholders were not found.")

        workflow[source_node]["inputs"][placeholders["source_image_input_key"]] = str(
            request.source_image_path
        )
        workflow[prompt_node]["inputs"][placeholders["prompt_input_key"]] = request.prompt
        workflow[width_node]["inputs"][placeholders["width_input_key"]] = request.output_width
        workflow[height_node]["inputs"][placeholders["height_input_key"]] = request.output_height

        return workflow

    def edit_image(self, request: ImageEditRequest) -> ImageEditResult:
        try:
            workflow = self._load_template()
            workflow = self._inject_template_fields(workflow, request)

            prompt_id = self.client.queue_prompt(workflow)
            history_entry = self.client.wait_for_completion(prompt_id)
            filenames = self.client.extract_output_filenames(history_entry)
            if not filenames:
                raise ImageEditingProviderError("ComfyUI returned no output images.")

            output_filename = filenames[0]
            destination = self.output_dir / output_filename
            self.client.download_output_image(output_filename, destination)

            return ImageEditResult(
                output_image_path=destination,
                provider="comfyui",
                model=self.model,
                job_id=prompt_id,
                metadata={"output_filename": output_filename},
            )
        except ComfyUIClientError as exc:
            raise ImageEditingProviderError(str(exc)) from exc
