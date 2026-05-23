import cv2
import numpy as np


class MPHandPose:
    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.8,
        backend_id: int = 0,
        target_id: int = 0,
    ):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.backend_id = backend_id
        self.target_id = target_id
        self.input_size = np.array([224, 224])
        self.PALM_LANDMARKS_INDEX_OF_PALM_BASE = 0
        self.PALM_LANDMARKS_INDEX_OF_MIDDLE_FINGER_BASE = 2
        self.PALM_BOX_PRE_SHIFT_VECTOR = [0, 0]
        self.PALM_BOX_PRE_ENLARGE_FACTOR = 4
        self.PALM_BOX_SHIFT_VECTOR = [0, -0.4]
        self.PALM_BOX_ENLARGE_FACTOR = 3
        self.HAND_BOX_SHIFT_VECTOR = [0, -0.1]
        self.HAND_BOX_ENLARGE_FACTOR = 1.65

        self.model = cv2.dnn.readNet(self.model_path)
        self.model.setPreferableBackend(self.backend_id)
        self.model.setPreferableTarget(self.target_id)

    def _crop_and_pad_from_palm(self, image, palm_bbox, for_rotation: bool = False):
        wh_palm_bbox = palm_bbox[1] - palm_bbox[0]
        shift_vector = self.PALM_BOX_PRE_SHIFT_VECTOR if for_rotation else self.PALM_BOX_SHIFT_VECTOR
        shift_vector = shift_vector * wh_palm_bbox
        palm_bbox = palm_bbox + shift_vector

        center_palm_bbox = np.sum(palm_bbox, axis=0) / 2
        wh_palm_bbox = palm_bbox[1] - palm_bbox[0]
        enlarge_scale = self.PALM_BOX_PRE_ENLARGE_FACTOR if for_rotation else self.PALM_BOX_ENLARGE_FACTOR
        new_half_size = wh_palm_bbox * enlarge_scale / 2
        palm_bbox = np.array([center_palm_bbox - new_half_size, center_palm_bbox + new_half_size])
        palm_bbox = palm_bbox.astype(np.int32)
        palm_bbox[:, 0] = np.clip(palm_bbox[:, 0], 0, image.shape[1])
        palm_bbox[:, 1] = np.clip(palm_bbox[:, 1], 0, image.shape[0])

        image = image[palm_bbox[0][1]:palm_bbox[1][1], palm_bbox[0][0]:palm_bbox[1][0], :]
        side_len = int(np.linalg.norm(image.shape[:2]) if for_rotation else max(image.shape[:2]))
        pad_h = side_len - image.shape[0]
        pad_w = side_len - image.shape[1]
        left = pad_w // 2
        top = pad_h // 2
        right = pad_w - left
        bottom = pad_h - top
        image = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, None, (0, 0, 0))
        bias = palm_bbox[0] - [left, top]
        return image, palm_bbox, bias

    def _preprocess(self, image, palm):
        pad_bias = np.array([0, 0], dtype=np.int32)
        palm_bbox = palm[0:4].reshape(2, 2)
        image, palm_bbox, bias = self._crop_and_pad_from_palm(image, palm_bbox, True)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pad_bias += bias

        palm_bbox -= pad_bias
        palm_landmarks = palm[4:18].reshape(7, 2) - pad_bias
        p1 = palm_landmarks[self.PALM_LANDMARKS_INDEX_OF_PALM_BASE]
        p2 = palm_landmarks[self.PALM_LANDMARKS_INDEX_OF_MIDDLE_FINGER_BASE]
        radians = np.pi / 2 - np.arctan2(-(p2[1] - p1[1]), p2[0] - p1[0])
        radians = radians - 2 * np.pi * np.floor((radians + np.pi) / (2 * np.pi))
        angle = np.rad2deg(radians)

        center_palm_bbox = np.sum(palm_bbox, axis=0) / 2
        rotation_matrix = cv2.getRotationMatrix2D(center_palm_bbox, angle, 1.0)
        rotated_image = cv2.warpAffine(image, rotation_matrix, (image.shape[1], image.shape[0]))

        homogeneous_coord = np.c_[palm_landmarks, np.ones(palm_landmarks.shape[0])]
        rotated_palm_landmarks = np.array([
            np.dot(homogeneous_coord, rotation_matrix[0]),
            np.dot(homogeneous_coord, rotation_matrix[1]),
        ])
        rotated_palm_bbox = np.array([
            np.amin(rotated_palm_landmarks, axis=1),
            np.amax(rotated_palm_landmarks, axis=1),
        ])

        crop, rotated_palm_bbox, _ = self._crop_and_pad_from_palm(rotated_image, rotated_palm_bbox)
        blob = cv2.resize(crop, dsize=self.input_size, interpolation=cv2.INTER_AREA).astype(np.float32)
        blob = blob / 255.0
        return blob[np.newaxis, :, :, :], rotated_palm_bbox, angle, rotation_matrix, pad_bias

    def infer(self, image, palm):
        input_blob, rotated_palm_bbox, angle, rotation_matrix, pad_bias = self._preprocess(image, palm)
        self.model.setInput(input_blob)
        output_blob = self.model.forward(self.model.getUnconnectedOutLayersNames())
        return self._postprocess(output_blob, rotated_palm_bbox, angle, rotation_matrix, pad_bias)

    def _postprocess(self, blob, rotated_palm_bbox, angle, rotation_matrix, pad_bias):
        landmarks, conf, handedness, landmarks_word = blob
        conf = conf[0][0]
        if conf < self.conf_threshold:
            return None

        landmarks = landmarks[0].reshape(-1, 3)
        landmarks_word = landmarks_word[0].reshape(-1, 3)

        wh_rotated_palm_bbox = rotated_palm_bbox[1] - rotated_palm_bbox[0]
        scale_factor = wh_rotated_palm_bbox / self.input_size
        landmarks[:, :2] = (landmarks[:, :2] - self.input_size / 2) * max(scale_factor)
        landmarks[:, 2] = landmarks[:, 2] * max(scale_factor)

        coords_rotation_matrix = cv2.getRotationMatrix2D((0, 0), angle, 1.0)
        rotated_landmarks = np.dot(landmarks[:, :2], coords_rotation_matrix[:, :2])
        rotated_landmarks = np.c_[rotated_landmarks, landmarks[:, 2]]
        rotated_landmarks_world = np.dot(landmarks_word[:, :2], coords_rotation_matrix[:, :2])
        rotated_landmarks_world = np.c_[rotated_landmarks_world, landmarks_word[:, 2]]

        rotation_component = np.array([
            [rotation_matrix[0][0], rotation_matrix[1][0]],
            [rotation_matrix[0][1], rotation_matrix[1][1]],
        ])
        translation_component = np.array([rotation_matrix[0][2], rotation_matrix[1][2]])
        inverted_translation = np.array([
            -np.dot(rotation_component[0], translation_component),
            -np.dot(rotation_component[1], translation_component),
        ])
        inverse_rotation_matrix = np.c_[rotation_component, inverted_translation]

        center = np.append(np.sum(rotated_palm_bbox, axis=0) / 2, 1)
        original_center = np.array([
            np.dot(center, inverse_rotation_matrix[0]),
            np.dot(center, inverse_rotation_matrix[1]),
        ])
        landmarks[:, :2] = rotated_landmarks[:, :2] + original_center + pad_bias

        bbox = np.array([
            np.amin(landmarks[:, :2], axis=0),
            np.amax(landmarks[:, :2], axis=0),
        ])
        wh_bbox = bbox[1] - bbox[0]
        shift_vector = self.HAND_BOX_SHIFT_VECTOR * wh_bbox
        bbox = bbox + shift_vector
        center_bbox = np.sum(bbox, axis=0) / 2
        wh_bbox = bbox[1] - bbox[0]
        new_half_size = wh_bbox * self.HAND_BOX_ENLARGE_FACTOR / 2
        bbox = np.array([center_bbox - new_half_size, center_bbox + new_half_size])

        return np.r_[
            bbox.reshape(-1),
            landmarks.reshape(-1),
            rotated_landmarks_world.reshape(-1),
            handedness[0][0],
            conf,
        ]
