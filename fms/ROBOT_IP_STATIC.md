# 핑키 3대 IP 고정 (관제 PC 에서 실행)

> 이 문서를 받은 Claude 에게: 관제 PC(이 PC)에서 아래 순서대로 실행한다. 각 단계의 **확인** 이 기대와 다르면
> 그 자리에서 멈추고 사용자에게 무엇이 달랐는지 보고한다. `sudo` 비밀번호는 직접 입력하지 말고, `sudo` 가 비밀번호를
> 물으면 그 명령을 사용자에게 보여 주고 직접 실행해 달라고 한다.

## 목적

핑키 로봇 3대가 team2 Wi-Fi(iptime AP, 10.42.0.x)에 붙을 때 **항상 같은 IP** 를 받게 한다.
FMS 의 `fms/robots.yaml` 이 이 IP 를 쓰므로, IP 가 바뀌면 FMS 가 로봇을 못 찾는다.

| 로봇 | MAC (wlan0) | 고정할 IP | 시리얼 (`:8080/status` 의 `robot.serial`) |
| --- | --- | --- | --- |
| pinky_6364 (FMS 1번) | 98:fe:54:07:63:65 | 10.42.0.171 | 0d4763d873e291b7 |
| pinky_ee3a (FMS 2번) | 88:a2:9e:46:ee:3b | 10.42.0.79 | 8ab6b3c36a27f120 |
| pinky_62f4 (FMS 3번) | 98:fe:54:07:62:f5 | 10.42.0.131 | 1cdda27b956a1efc |

IP 는 지금 받고 있는 값 그대로라 `robots.yaml` 은 고칠 필요 없다. (2026-10-30 확인)

## 망 구조 (2026-10-30 확인)

- 관제 PC 가 **10.42.0.1**, 이 망의 DHCP·DNS·게이트웨이 (임대 3600초). Linux NetworkManager 의 "다른 컴퓨터와 공유"
  (`ipv4.method shared`) → NetworkManager 가 띄운 **dnsmasq** 가 IP 를 나눠 준다.
- iptime 은 관제 PC 와 LAN 으로 연결된 **무선 AP** 역할 (team2_5G / team2_2_4G). iptime 의 DHCP 는 쓰지 않는다.
- 그래서 고정 IP 는 iptime 관리 화면이 아니라 **관제 PC 의 dnsmasq 설정**에 넣는다.

## 1. 확인: 정말 NetworkManager 공유 모드인가

```bash
nmcli -f NAME,TYPE,DEVICE con show --active
ip -4 addr | grep 10.42.0.1
pgrep -a dnsmasq | grep -i networkmanager
```

**확인**
- `10.42.0.1/24` 가 붙은 장치(보통 유선 `en…`/`eth…`)가 있다.
- 그 장치의 연결 이름(NAME)으로 `nmcli -g ipv4.method con show "<NAME>"` → `shared` 가 나온다.
- NetworkManager 가 띄운 dnsmasq 프로세스가 있다 (`--conf-dir=/etc/NetworkManager/dnsmasq-shared.d` 가 들어 있음).

셋 중 하나라도 아니면 **멈추고 보고** (다른 방식이면 아래 "다른 경우" 참고).

## 2. 지금 임대 상황 보기 (다른 기기가 그 IP 를 쓰고 있지 않은지)

```bash
sudo cat /var/lib/NetworkManager/dnsmasq-*.leases
```

**확인**: 10.42.0.171 / .79 / .131 이 있다면 각각 위 표의 MAC 이어야 한다. 다른 MAC 이 그 IP 를 갖고 있으면 **멈추고 보고**.

## 3. 고정 할당 파일 넣기

```bash
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo tee /etc/NetworkManager/dnsmasq-shared.d/pinky-robots.conf >/dev/null <<'EOF'
# 핑키 로봇 고정 IP (2026-10-30). FMS fms/robots.yaml 과 같아야 한다.
dhcp-host=98:fe:54:07:63:65,10.42.0.171,pinky-6364
dhcp-host=88:a2:9e:46:ee:3b,10.42.0.79,pinky-ee3a
dhcp-host=98:fe:54:07:62:f5,10.42.0.131,pinky-62f4
EOF
cat /etc/NetworkManager/dnsmasq-shared.d/pinky-robots.conf
```

## 4. 적용 (망이 몇 초 끊긴다)

**먼저 사용자에게 확인받는다**: 공유 연결을 다시 올리면 10.42.0.x 망 전체(로봇·다른 PC)가 수 초~수십 초 끊긴다.
FMS 로 로봇이 달리는 중이면 안 된다. FMS 를 쓰는 중이면 먼저 `cd fms && docker compose stop fms`.

```bash
sudo nmcli connection down "<1번에서 찾은 NAME>" && sudo nmcli connection up "<1번에서 찾은 NAME>"
pgrep -a dnsmasq | grep -i networkmanager     # 다시 떴는지
```

로봇은 Wi-Fi 가 다시 붙으면 DHCP 를 다시 받는다. 1~2분 기다린다.
(빨리 확인하려면 로봇 전원을 껐다 켜도 된다. 로봇은 켜지면 서비스가 저절로 뜬다.)

## 5. 확인: 로봇이 표의 IP 에 있는가

```bash
for ip in 171 79 131; do printf "10.42.0.$ip "; curl -s -m 3 http://10.42.0.$ip:8080/status | python3 -c "import json,sys; print(json.load(sys.stdin)['robot']['serial'])" 2>/dev/null || echo "응답 없음"; done
```

**기대**
```
10.42.0.171 0d4763d873e291b7
10.42.0.79 8ab6b3c36a27f120
10.42.0.131 1cdda27b956a1efc
```

응답 없는 로봇이 있으면 망 전체에서 찾아본다 (켜져 있는지, 다른 IP 를 받았는지):

```bash
for i in $(seq 2 254); do (curl -s -m 0.5 http://10.42.0.$i:8080/status | python3 -c "import json,sys; print('10.42.0.$i', json.load(sys.stdin)['robot']['serial'])" 2>/dev/null &); done; sleep 2
```

다른 IP 에 있으면: 그 로봇의 Wi-Fi 를 다시 붙이게 하거나(전원 껐다 켜기) 2번 임대 파일을 다시 보고 보고한다.
FMS 를 멈췄었다면 `cd fms && docker compose start fms`.

## 되돌리기

```bash
sudo rm /etc/NetworkManager/dnsmasq-shared.d/pinky-robots.conf
sudo nmcli connection down "<NAME>" && sudo nmcli connection up "<NAME>"
```

## 다른 경우

- **1번에서 공유 모드가 아니고 iptime 이 DHCP 를 하는 경우**: iptime 관리 화면(브라우저로 iptime 주소, 보통 `http://192.168.0.1`
  또는 게이트웨이 주소) → 관리도구 → 고급 설정 → 네트워크 관리 → 내부 네트워크 설정 → DHCP 서버 설정 → **수동 IP 할당**에
  위 표의 MAC·IP 세 줄을 넣고 적용. 관리자 비밀번호는 사용자가 직접 입력한다.
- **로봇을 바꾸거나 새 로봇을 넣을 때**: 로봇에서 `cat /sys/class/net/wlan0/address` (MAC), `grep Serial /proc/cpuinfo` (시리얼)
  → 3번 파일과 `fms/robots.yaml` 에 같이 넣는다.
