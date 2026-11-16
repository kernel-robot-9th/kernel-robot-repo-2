# eval_bi.py 복귀 관절값 설정

원본 백업: `eval_bi.py.bak.20261020`

기존 실행 명령에 아래 옵션을 추가합니다. `<...>`는 설명용 자리표시자입니다.
실제 로봇에서 확인한 값을 넣기 전에는 실행하지 않습니다.

```text
--return-via <경유 자세 왼쪽 관절값 6개>
--start-pose <시작 자세 왼쪽 관절값 6개>
--return-via-time 2.0
--return-home-time 2.0
```

측정한 왼쪽 경유 자세와 시작 자세가 기본값으로 들어 있습니다. 숫자를 입력하지 않아도 됩니다.
복귀를 끄려면 `--no-return`을 사용합니다. 자세를 덮어쓸 때는 두 옵션을 함께 지정합니다.
자세를 지정하면 평가 시간 종료 또는 외부 복귀 요청 시
현재 자세 → 경유 자세 → 시작 자세로 복귀합니다.
프로그램 시작 시 시작 자세로 자동 이동하는 옵션은 아닙니다.

각 자세의 값 순서:

```text
left_shoulder_pan left_shoulder_lift left_elbow_flex left_wrist_flex left_wrist_roll left_gripper
```

단위는 기존 LeRobot 관측/명령과 같은 정규화 값입니다.
몸체 관절은 -100~100, 그리퍼는 0~100입니다. degree/radian 값을 직접 넣지 않습니다.
실제 장치의 교정값을 사용한 관측에서 값을 얻어야 합니다.
경유 및 시작 자세의 그리퍼 값도 해당 구간에서 명령되므로,
거즈를 놓은 뒤 열린 상태를 유지하려면 두 자세에 맞는 열린 값을 넣습니다.

각 구간은 지정 시간 동안 관절 목표값을 보간합니다.
기본적으로 모든 관절이 목표값 ±2 안에 3회 연속 들어오는 것을 확인합니다.
구간 명령 완료 후 3초 안에 도착을 확인하지 못하면 예외로 중단합니다.
`--return-tolerance`, `--return-settle-time`으로 조정할 수 있습니다.
이 보간은 충돌 회피나 로봇별 속도·가속도 제한을 계산하지 않으므로,
경로와 이동 시간은 실제 작업 공간에 맞춰 확인해야 합니다.
Ctrl+C 또는 오류 시 복귀를 새로 시작하지 않고 기존 종료 절차를 수행합니다.
CLI 종료 시 기존과 같이 torque off되므로 시작 자세를 계속 유지하는 모드는 아닙니다.

## 다른 코드와 연결

`run_episode()`의 기존 인자 및 `(steps, action)` 반환 형태는 유지합니다.
복귀를 실행하면 반환되는 action은 마지막 시작 자세 명령입니다.
기존 초기화 코드에서 만든 robot, policy 등과 args를 그대로 사용하고,
통신 수신부가 설정하는 Event를 연결할 수 있습니다.

```python
from threading import Event
from eval_bi import run_episode

return_event = Event()
# 통신 수신부: 종료 신호를 받으면 return_event.set()
# 다음 에피소드를 시작하기 전 호출 측에서 return_event.clear()
steps, last_action = run_episode(
    robot, policy, preprocessor, postprocessor, features, args,
    should_return=lambda obs: return_event.is_set(),
)
```

콜백은 즉시 반환해야 합니다. 통신 대기는 별도 수신부에서 처리합니다.
로봇 포트는 평가/복귀 스레드 하나만 사용해야 합니다.
콜백은 추론 전후에 호출하며 추론 중 들어온 요청도 모델 명령 전송 전에 확인합니다.
오른쪽 위치 명령은 모델 출력에 있어도 버립니다. 오른쪽은 모델 입력용 관절 읽기만 수행하며,
초기 설정·사전 오류 해제·종료 시 토크 변경 대상에서 제외합니다. 따라서 오른쪽 연결은 관측용으로 필요합니다.
현재 ROS2 클라이언트나 소켓 수신부를 새로 구현한 것은 아닙니다.
그리퍼 개방/B구역 판정은 아직 자동 적용하지 않으며, 필요하면 콜백에서 관측값으로
종료 조건을 판단할 수 있습니다. 기준 자세와 개방 임계값은 실제 측정값이 필요합니다.

0.4초는 복귀 이동 시간으로 설정하지 않습니다. 개방 감지부터 복귀 명령까지의 지연은
카메라 읽기와 진행 중인 추론에 영향을 받으므로 이 코드만으로 0.4초를 보장하지 않습니다.
실제 장비에서 지연을 측정한 뒤 별도 제어 루프가 필요한지 판단해야 합니다.

모터 없이 로직 테스트:

```bash
/home/omen/anaconda3/envs/main_project/bin/python -m unittest discover -s tests -p test_eval_bi_return.py -v
```

기존 `--dry-run`에서는 모델 추론은 실행하지만 복귀 모터 명령은 보내지 않습니다.

측정 원본: `left_return_via_measured.json`, `left_start_pose_measured.json`.
왼쪽 전용 변경 직전 백업: `eval_bi.py.bak.before_left_only`.
