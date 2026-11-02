# 노트북 ↔ Pinky ROS 2 연결 설정과 확인

이 문서는 노트북 (서버)과 Pinky (Raspberry Pi, ROS 2 Jazzy) 사이의 ROS 연결을 처음부터 설정하는 안내입니다. 2026-10-21에 이 환경에서 실제로 수행하고 성공한 순서대로 적었습니다.

## 환경

| 장치 | 사용자 | IP (Wi-Fi) | 비고 |
|---|---|---|---|
| 노트북 (서버) | `zubayda` | `192.168.129.121` | |
| Pinky (Raspberry Pi) | `pinky@raspi` | `192.168.129.116` | 네트워크가 2개 더 있음: `192.168.180.53`과 `192.168.4.1` (Pinky 자체 핫스팟) |

* ROS 2: 양쪽 모두 **Jazzy**. RMW: 기본값 (Fast DDS), `RMW_IMPLEMENTATION`은 설정하지 않음.
* 노트북, Pinky, 휴대폰은 같은 Wi-Fi 네트워크에 있음. 네트워크 이름과 비밀번호는 이 파일에 적지 않았습니다: 팀에 물어보세요.
* IP 주소는 DHCP로 받으므로 바뀔 수 있습니다. 공유기에서 고정해 두는 것이 좋습니다. 바뀌면 아래 IP를 갱신하세요.

## 1단계. ROS_DOMAIN_ID 올바르게 설정

두 기기에서 같아야 하고 **0–101 범위**여야 합니다.

> 처음에는 양쪽 다 `9090`이었습니다. 이 값은 동작하지 않습니다: DDS는 0–232만 받습니다. 그래서 `90`으로 바꿨습니다.

두 기기 모두 `~/.bashrc`에 추가:

```bash
export ROS_DOMAIN_ID=90
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

새 터미널을 여세요 (또는 `source ~/.bashrc`).

## 2단계. 설정 비교

두 기기 모두에서 실행:

```bash
printenv | grep -E 'ROS_|RMW'
hostname -I
```

예상 결과 (양쪽 동일):

```
ROS_DOMAIN_ID=90
ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ROS_DISTRO=jazzy
```

다음은 **없어야** 합니다: `ROS_LOCALHOST_ONLY=1`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`. 양쪽의 `RMW_IMPLEMENTATION`도 달라서는 안 됩니다.

## 3단계. 네트워크 확인 (ping)

노트북에서:

```bash
ping 192.168.129.116
```

`64 bytes from ...`가 나오면 네트워크는 정상입니다. 응답이 없으면 문제는 ROS가 아니라 Wi-Fi입니다: 공유기가 기기끼리 분리했을 수 있습니다 (client isolation).

## 4단계. talker / listener 테스트

```bash
ros2 run demo_nodes_cpp talker      # Pinky에서
ros2 run demo_nodes_cpp listener    # 노트북에서
```

노트북에 `I heard: [Hello World: N]`가 나와야 합니다.

> 이 환경에서는 ping이 되는데도 여기서 listener가 아무것도 출력하지 않고 멈춰 있었습니다. 원인: Pinky에 네트워크가 3개 있어서, ROS가 멀티캐스트로 자동 검색할 때 노트북이 Pinky를 찾지 못했습니다. 5단계로 해결했습니다.

## 5단계. 기기끼리 직접 지정 (ROS_STATIC_PEERS)

노트북의 `~/.bashrc`에:

```bash
export ROS_STATIC_PEERS=192.168.129.116    # Pinky IP
```

Pinky의 `~/.bashrc`에:

```bash
export ROS_STATIC_PEERS=192.168.129.121    # 노트북 IP
```

양쪽 모두:

```bash
source ~/.bashrc
ros2 daemon stop
```

새 터미널에서 4단계를 반복합니다. 결과:

```
[INFO] [listener]: I heard: [Hello World: 19]
[INFO] [listener]: I heard: [Hello World: 20]
```

✅ 이것으로 연결되었습니다.

## 최종 `~/.bashrc` (연결 부분)

노트북:

```bash
export ROS_DOMAIN_ID=90
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_STATIC_PEERS=192.168.129.116
```

Pinky:

```bash
export ROS_DOMAIN_ID=90
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_STATIC_PEERS=192.168.129.121
```

Pinky의 드라이버가 systemd 서비스로 자동 실행된다면 `.bashrc`는 영향을 주지 않습니다: 서비스 파일에도 같은 변수를 넣고 Pinky를 재부팅하세요.

## 문제와 해결

| 증상 | 가능한 원인 | 해결 |
|---|---|---|
| `ros2` 명령이 오류를 내거나 노드가 시작되지 않음 | `ROS_DOMAIN_ID`가 232보다 큼 | 0–101 범위의 값 (1단계) |
| ping 안 됨 | Wi-Fi가 기기를 분리했거나 IP가 바뀜 | `hostname -I`로 IP 확인, 다른 네트워크나 공유기 설정 |
| ping은 되는데 listener가 조용함 | 멀티캐스트가 안 되거나 Pinky에 네트워크가 여러 개 | 5단계 (`ROS_STATIC_PEERS`) |
| 5단계 후에도 조용함 | 오래된 daemon이나 오래된 터미널 | `ros2 daemon stop`, 새 터미널; 노트북 방화벽 확인: `sudo ufw status` (임시로 `sudo ufw disable`) |
| 여전히 조용함 | Fast DDS가 잘못된 네트워크를 사용 | 아래 "예비 해결책" |
| 어제는 됐는데 오늘은 안 됨 | IP가 바뀜 | `hostname -I` 후 `ROS_STATIC_PEERS` 갱신 |

### 예비 해결책: Pinky에서 ROS를 Wi-Fi 네트워크로만 제한

이 환경에서는 필요 없었지만, 5단계로 안 되면 시도해 보세요. Pinky에 `~/fastdds_wifi.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor>
      <transport_id>wifi_only</transport_id>
      <type>UDPv4</type>
      <interfaceWhiteList><address>192.168.129.116</address></interfaceWhiteList>
    </transport_descriptor>
  </transport_descriptors>
  <participant profile_name="default" is_default_profile="true">
    <rtps>
      <userTransports><transport_id>wifi_only</transport_id></userTransports>
      <useBuiltinTransports>false</useBuiltinTransports>
    </rtps>
  </participant>
</profiles>
```

```bash
export FASTRTPS_DEFAULT_PROFILES_FILE=~/fastdds_wifi.xml
ros2 daemon stop
```

## 다음 단계

연결이 되면 센서를 확인합니다: [checking_sensors.md](checking_sensors.md).
