# FMS 서버 (sim_server.py: 관제 PC API v1 + 시뮬레이터 화면 + 실제 핑키 연결) — 관제 PC 에서 띄움 (10-29)
# 빌드 컨텍스트 = 저장소 루트 (driving/graph 의 주행 그래프·실측 시간을 같이 넣음):
#   cd fms && docker compose up -d --build        (또는 저장소 루트에서  docker build -f fms/Dockerfile -t fms .)
FROM python:3.12-slim
RUN pip install --no-cache-dir pyyaml==6.0.2
WORKDIR /app
COPY driving/graph/graph.yaml driving/graph/edge_times.yaml driving/graph/
COPY driving/tools/real_walls.yaml driving/tools/left_wall_measured.json driving/tools/
COPY fms/*.py fms/rooms.yaml fms/robots.yaml fms/
COPY fms/static fms/static
ENV PYTHONUNBUFFERED=1 TZ=Asia/Seoul
WORKDIR /app/fms
EXPOSE 8770
ENTRYPOINT ["python3", "sim_server.py", "--host", "0.0.0.0", "--port", "8770"]
# 기본: robots.yaml 에 url 있는 로봇 = 실제 핑키, ready·loaded 는 관제 PC 가 보냄
CMD ["--real-table", "--no-auto-omx"]
