from pathlib import Path

import cv2
import numpy as np


class MPPalmDet:
    def __init__(
        self,
        model_path: str,
        nms_threshold: float = 0.3,
        score_threshold: float = 0.5,
        top_k: int = 5000,
        backend_id: int = 0,
        target_id: int = 0,
    ):
        self.model_path = model_path
        self.nms_threshold = nms_threshold
        self.score_threshold = score_threshold
        self.top_k = top_k
        self.backend_id = backend_id
        self.target_id = target_id
        self.input_size = np.array([192, 192])

        self.model = cv2.dnn.readNet(self.model_path)
        self.model.setPreferableBackend(self.backend_id)
        self.model.setPreferableTarget(self.target_id)
        self.anchors = self._load_anchors()

    def _load_anchors(self) -> np.ndarray:
        anchors_path = Path(__file__).parent / "palm_anchors.npy"
        return np.load(anchors_path)

    def _preprocess(self, image: np.ndarray):
        pad_bias = np.array([0.0, 0.0])
        ratio = min(self.input_size / image.shape[:2])

        if image.shape[0] != self.input_size[0] or image.shape[1] != self.input_size[1]:
            ratio_size = (np.array(image.shape[:2]) * ratio).astype(np.int32)
            image = cv2.resize(image, (ratio_size[1], ratio_size[0]))
            pad_h = self.input_size[0] - ratio_size[0]
            pad_w = self.input_size[1] - ratio_size[1]
            pad_bias[0] = left = pad_w // 2
            pad_bias[1] = top = pad_h // 2
            right = pad_w - left
            bottom = pad_h - top
            image = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, None, (0, 0, 0))

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = image.astype(np.float32) / 255.0
        pad_bias = (pad_bias / ratio).astype(np.int32)
        return image[np.newaxis, :, :, :], pad_bias

    def infer(self, image: np.ndarray) -> np.ndarray:
        height, width, _ = image.shape
        input_blob, pad_bias = self._preprocess(image)
        self.model.setInput(input_blob)
        output_blob = self.model.forward(self.model.getUnconnectedOutLayersNames())
        return self._postprocess(output_blob, np.array([width, height]), pad_bias)

    def _postprocess(self, output_blob, original_shape: np.ndarray, pad_bias: np.ndarray) -> np.ndarray:
        score = output_blob[1][0, :, 0]
        box_delta = output_blob[0][0, :, 0:4]
        landmark_delta = output_blob[0][0, :, 4:]
        scale = max(original_shape)

        score = score.astype(np.float64)
        score = 1 / (1 + np.exp(-score))

        cxy_delta = box_delta[:, :2] / self.input_size
        wh_delta = box_delta[:, 2:] / self.input_size
        xy1 = (cxy_delta - wh_delta / 2 + self.anchors) * scale
        xy2 = (cxy_delta + wh_delta / 2 + self.anchors) * scale
        boxes = np.concatenate([xy1, xy2], axis=1)
        boxes -= [pad_bias[0], pad_bias[1], pad_bias[0], pad_bias[1]]

        keep_idx = cv2.dnn.NMSBoxes(
            boxes.tolist(),
            score.tolist(),
            self.score_threshold,
            self.nms_threshold,
            top_k=self.top_k,
        )
        if len(keep_idx) == 0:
            return np.empty(shape=(0, 19))

        keep_idx = np.array(keep_idx).reshape(-1)
        selected_score = score[keep_idx]
        selected_box = boxes[keep_idx]
        selected_landmarks = landmark_delta[keep_idx].reshape(-1, 7, 2)
        selected_landmarks = selected_landmarks / self.input_size
        selected_anchors = self.anchors[keep_idx]

        for idx, landmark in enumerate(selected_landmarks):
            landmark += selected_anchors[idx]
            selected_landmarks[idx] = landmark * scale - pad_bias

        return np.c_[
            selected_box.reshape(-1, 4),
            selected_landmarks.reshape(-1, 14),
            selected_score.reshape(-1, 1),
        ]
