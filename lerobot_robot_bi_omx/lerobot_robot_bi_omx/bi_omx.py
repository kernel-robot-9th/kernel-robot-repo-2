from dataclasses import dataclass, field
from functools import cached_property

from lerobot.cameras import CameraConfig
from lerobot.processor import RobotAction, RobotObservation
from lerobot.robots.config import RobotConfig
from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig
from lerobot.robots.robot import Robot
from lerobot.teleoperators.config import TeleoperatorConfig
from lerobot.teleoperators.omx_leader import OmxLeader, OmxLeaderConfig
from lerobot.teleoperators.teleoperator import Teleoperator
from lerobot.utils.decorators import check_if_already_connected, check_if_not_connected


def _prefix(d: dict, p: str) -> dict:
    return {f"{p}_{k}": v for k, v in d.items()}


def _unprefix(d: dict, p: str) -> dict:
    return {k.removeprefix(f"{p}_"): v for k, v in d.items() if k.startswith(f"{p}_")}


@RobotConfig.register_subclass("bi_omx_follower")
@dataclass
class BiOmxFollowerConfig(RobotConfig):
    left_arm_port: str = "/dev/omx_follower_left"
    right_arm_port: str = "/dev/omx_follower"
    disable_torque_on_disconnect: bool = True
    max_relative_target: float | dict[str, float] | None = None
    use_degrees: bool = False
    # Cameras belong to the whole robot; keys are kept as given (e.g. top, wrist_left, wrist_right).
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    # Optional per-camera keep-rectangle [x1, y1, x2, y2]; everything outside is set to black.
    # Used at inference so a model trained on masked video sees the same masked view.
    mask_rois: dict[str, list[int]] = field(default_factory=dict)


class BiOmxFollower(Robot):
    """Two OMX follower arms driven as one robot. Joint keys are prefixed with left_/right_."""

    config_class = BiOmxFollowerConfig
    name = "bi_omx_follower"

    def __init__(self, config: BiOmxFollowerConfig):
        super().__init__(config)
        self.config = config

        def arm_config(side: str, port: str, cameras: dict) -> OmxFollowerConfig:
            return OmxFollowerConfig(
                id=f"{config.id}_{side}" if config.id else None,
                calibration_dir=config.calibration_dir,
                port=port,
                disable_torque_on_disconnect=config.disable_torque_on_disconnect,
                max_relative_target=config.max_relative_target,
                use_degrees=config.use_degrees,
                cameras=cameras,
            )

        # The right arm instance owns all cameras so they are connected/read/disconnected once.
        self.left_arm = OmxFollower(arm_config("left", config.left_arm_port, {}))
        self.right_arm = OmxFollower(arm_config("right", config.right_arm_port, config.cameras))
        self.cameras = self.right_arm.cameras

    @property
    def _motors_ft(self) -> dict[str, type]:
        return {**_prefix(self.left_arm._motors_ft, "left"), **_prefix(self.right_arm._motors_ft, "right")}

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._motors_ft, **self.right_arm._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._motors_ft

    @property
    def is_connected(self) -> bool:
        return self.left_arm.is_connected and self.right_arm.is_connected

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        self.left_arm.connect(calibrate)
        self.right_arm.connect(calibrate)

    @property
    def is_calibrated(self) -> bool:
        return self.left_arm.is_calibrated and self.right_arm.is_calibrated

    def calibrate(self) -> None:
        self.left_arm.calibrate()
        self.right_arm.calibrate()

    def configure(self) -> None:
        self.left_arm.configure()
        self.right_arm.configure()

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        left = self.left_arm.get_observation()
        right = self.right_arm.get_observation()
        cam_keys = set(self.cameras)
        obs = _prefix(left, "left")
        obs.update(_prefix({k: v for k, v in right.items() if k not in cam_keys}, "right"))
        for k in cam_keys:
            img = right[k]
            if k in self.config.mask_rois:
                x1, y1, x2, y2 = self.config.mask_rois[k]
                masked = img.copy()
                masked[:y1] = 0
                masked[y2:] = 0
                masked[:, :x1] = 0
                masked[:, x2:] = 0
                img = masked
            obs[k] = img
        return obs

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        sent_left = self.left_arm.send_action(_unprefix(action, "left"))
        sent_right = self.right_arm.send_action(_unprefix(action, "right"))
        return {**_prefix(sent_left, "left"), **_prefix(sent_right, "right")}

    @check_if_not_connected
    def disconnect(self):
        # Try both arms even if one fails, so neither is left with torque on.
        errors = []
        for arm in (self.left_arm, self.right_arm):
            try:
                arm.disconnect()
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        if errors:
            raise errors[0]


@TeleoperatorConfig.register_subclass("bi_omx_leader")
@dataclass
class BiOmxLeaderConfig(TeleoperatorConfig):
    left_arm_port: str = "/dev/omx_leader_left"
    right_arm_port: str = "/dev/omx_leader"
    gripper_open_pos: float = 60.0


class BiOmxLeader(Teleoperator):
    """Two OMX leader arms read as one teleoperator. Action keys are prefixed with left_/right_."""

    config_class = BiOmxLeaderConfig
    name = "bi_omx_leader"

    def __init__(self, config: BiOmxLeaderConfig):
        super().__init__(config)
        self.config = config

        def arm_config(side: str, port: str) -> OmxLeaderConfig:
            return OmxLeaderConfig(
                id=f"{config.id}_{side}" if config.id else None,
                calibration_dir=config.calibration_dir,
                port=port,
                gripper_open_pos=config.gripper_open_pos,
            )

        self.left_arm = OmxLeader(arm_config("left", config.left_arm_port))
        self.right_arm = OmxLeader(arm_config("right", config.right_arm_port))

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {**_prefix(self.left_arm.action_features, "left"), **_prefix(self.right_arm.action_features, "right")}

    @cached_property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return self.left_arm.is_connected and self.right_arm.is_connected

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        self.left_arm.connect(calibrate)
        self.right_arm.connect(calibrate)

    @property
    def is_calibrated(self) -> bool:
        return self.left_arm.is_calibrated and self.right_arm.is_calibrated

    def calibrate(self) -> None:
        self.left_arm.calibrate()
        self.right_arm.calibrate()

    def configure(self) -> None:
        self.left_arm.configure()
        self.right_arm.configure()

    @check_if_not_connected
    def get_action(self) -> dict[str, float]:
        return {**_prefix(self.left_arm.get_action(), "left"), **_prefix(self.right_arm.get_action(), "right")}

    def send_feedback(self, feedback: dict[str, float]) -> None:
        raise NotImplementedError

    @check_if_not_connected
    def disconnect(self) -> None:
        self.left_arm.disconnect()
        self.right_arm.disconnect()
