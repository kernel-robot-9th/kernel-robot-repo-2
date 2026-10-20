"""Shared pieces for the vla_sim launch files (not a launch file itself)."""


def wrist_camera_urdf(prefix='', topic='wrist_camera'):
    """URDF snippet: a camera on <prefix>link5 looking down the tool axis between the fingers.

    link5 frame: +x along the tool (down in a top-down grasp), fingers close along y,
    finger plates span z = +-0.021. The camera sits beside the plates (-z) behind the
    fingertips and pitches toward the grasp point (~x = 0.09).
    """
    return f"""
  <link name="{prefix}wrist_camera_link">
    <visual>
      <geometry><box size="0.008 0.012 0.012"/></geometry>
    </visual>
    <inertial>
      <mass value="0.001"/>
      <inertia ixx="1e-8" ixy="0" ixz="0" iyy="1e-8" iyz="0" izz="1e-8"/>
    </inertial>
  </link>
  <joint name="{prefix}wrist_camera_joint" type="fixed">
    <parent link="{prefix}link5"/>
    <child link="{prefix}wrist_camera_link"/>
    <origin xyz="0.02 0 -0.035" rpy="0 -0.46 0"/>
  </joint>
  <gazebo reference="{prefix}wrist_camera_link">
    <sensor name="{prefix}wrist_camera" type="camera">
      <always_on>true</always_on>
      <update_rate>10</update_rate>
      <topic>{topic}/image_raw</topic>
      <camera>
        <camera_info_topic>{topic}/camera_info</camera_info_topic>
        <horizontal_fov>1.2</horizontal_fov>
        <image><width>320</width><height>240</height><format>R8G8B8</format></image>
        <clip><near>0.01</near><far>2</far></clip>
      </camera>
    </sensor>
  </gazebo>
"""
