"""Closed-form top-down IK for ROBOTIS OMX-F (5-DOF).

Geometry (from open_manipulator_description/urdf/omx_f/omx_f_arm.urdf.xacro):
  joint1 (yaw)   at (-0.01125, 0, 0.034) from link0
  joint2 (pitch) +0.0635 z
  joint3 (pitch) +(0.0415, 0, 0.11315)
  joint4 (pitch) +(0.162, 0, 0)
  joint5 (roll)  +(0.0287, 0, 0)
  end_effector_link +(0.09193, -0.0016, 0) from link5

Pitch joints rotate about +y, so a positive angle tilts the chain forward/down.
"Top-down" means the tool x-axis (joint4 -> end effector) points to -z.
"""
import math

J1_X = -0.01125
SHOULDER_Z = 0.034 + 0.0635
L1_U, L1_V = 0.0415, 0.11315
L1 = math.hypot(L1_U, L1_V)
BETA = math.atan2(L1_V, L1_U)        # link2 angle above horizontal at q2 = 0
L2 = 0.162
TOOL = 0.0287 + 0.09193              # joint4 -> end_effector_link along tool axis


def wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def top_down_ik(x, y, z, grasp_yaw=None):
    """Joint angles [q1..q5] placing end_effector_link at (x, y, z) pointing down.

    grasp_yaw: desired yaw (base frame) of the finger closing direction; the
    closest equivalent modulo pi/2 (square blocks) is used. None -> q5 = 0.
    Returns None if unreachable.
    """
    dx = x - J1_X
    q1 = math.atan2(y, dx)
    r = math.hypot(dx, y)

    # wrist (joint4) sits straight above the end effector
    du = r
    dv = (z + TOOL) - SHOULDER_Z
    d2 = du * du + dv * dv
    c = (d2 - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    if abs(c) > 1.0:
        return None
    gamma = -math.acos(c)                       # elbow-up branch
    theta_a = math.atan2(dv, du) - math.atan2(L2 * math.sin(gamma), L1 + L2 * math.cos(gamma))
    theta_b = theta_a + gamma                   # absolute angle of link3

    q2 = BETA - theta_a
    q3 = -theta_b - q2
    q4 = math.pi / 2.0 - q2 - q3                # tool angle = -pi/2 (down)

    q5 = 0.0
    if grasp_yaw is not None:
        # with q5 = 0 the fingers close along the horizontal axis normal to the arm plane
        q5 = wrap(q1 + math.pi / 2.0 - grasp_yaw)
        q5 = (q5 + math.pi / 4.0) % (math.pi / 2.0) - math.pi / 4.0
    return [wrap(q1), q2, q3, q4, q5]


def fk_tool(q):
    """Forward kinematics of end_effector_link position (ignores the 1.6 mm lateral offset)."""
    q1, q2, q3, q4 = q[:4]
    ta = BETA - q2
    tb = -(q2 + q3)
    tt = -(q2 + q3 + q4)
    u = L1 * math.cos(ta) + L2 * math.cos(tb) + TOOL * math.cos(tt)
    v = SHOULDER_Z + L1 * math.sin(ta) + L2 * math.sin(tb) + TOOL * math.sin(tt)
    return (J1_X + u * math.cos(q1), u * math.sin(q1), v)
