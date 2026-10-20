// =============================================================================
// 파일   : src/features/maps/mapGeometry.ts
// 역할   : 맵 좌표(미터, ROS map 프레임) ↔ 맵 이미지 픽셀 변환 — ROS map_server yaml 규칙 그대로 (2026-10-19)
// 작성일 : 2026-10-19
// 구성   :
//   - FALLBACK_SIZE_PX     이미지가 없는 맵(숫자만 등록)을 격자로 그릴 때의 크기
//   - mapImageSize()       맵의 그림 크기 (이미지 크기 또는 FALLBACK)
//   - metersToPixel()      (x_m, y_m) → 이미지 픽셀 (왼쪽 위 원점, 아래로 +)
//   - pixelToMeters()      이미지 픽셀 → (x_m, y_m)
//   - headingToSvgVector() 로봇 방향(yaw_rad) → 이미지 위 화살표 방향
// map_server: origin = 이미지 왼쪽 아래 모서리의 맵 좌표(x, y)와 이미지 회전(yaw). 이미지 y는 아래로, 맵 y는 위로 증가
// =============================================================================
import type { MapInfo } from '../../api/types'

export const FALLBACK_SIZE_PX = { width_px: 800, height_px: 600 }

/** 맵을 그릴 크기. [입력] map [출력] { width_px, height_px } */
export function mapImageSize(map: MapInfo): { width_px: number; height_px: number } {
  return map.image_width_px && map.image_height_px
    ? { width_px: map.image_width_px, height_px: map.image_height_px }
    : FALLBACK_SIZE_PX
}

/** 맵 좌표(미터) → 이미지 픽셀. origin 회전을 풀고 해상도로 나눈 뒤 y를 뒤집는다.
 *  [입력] x_m, y_m / map  [출력] { px, py } (이미지 왼쪽 위 기준)
 */
export function metersToPixel(x_m: number, y_m: number, map: MapInfo): { px: number; py: number } {
  const { height_px } = mapImageSize(map)
  const dx_m = x_m - map.origin_x_m
  const dy_m = y_m - map.origin_y_m
  const cos = Math.cos(map.origin_yaw_rad)
  const sin = Math.sin(map.origin_yaw_rad)
  const along_x_m = cos * dx_m + sin * dy_m      // 이미지 가로축 방향 거리
  const along_y_m = -sin * dx_m + cos * dy_m     // 이미지 세로축(위로) 방향 거리
  return { px: along_x_m / map.resolution_m_per_pixel, py: height_px - along_y_m / map.resolution_m_per_pixel }
}

/** 이미지 픽셀 → 맵 좌표(미터). metersToPixel의 역변환.
 *  [입력] px, py / map  [출력] { x_m, y_m }
 */
export function pixelToMeters(px: number, py: number, map: MapInfo): { x_m: number; y_m: number } {
  const { height_px } = mapImageSize(map)
  const along_x_m = px * map.resolution_m_per_pixel
  const along_y_m = (height_px - py) * map.resolution_m_per_pixel
  const cos = Math.cos(map.origin_yaw_rad)
  const sin = Math.sin(map.origin_yaw_rad)
  return {
    x_m: map.origin_x_m + cos * along_x_m - sin * along_y_m,
    y_m: map.origin_y_m + sin * along_x_m + cos * along_y_m,
  }
}

/** 맵 프레임 방향(yaw, 반시계 +) → 이미지 위 단위 벡터. 이미지 y가 아래로라 부호를 뒤집는다.
 *  [입력] yaw_rad / map  [출력] { dx, dy }
 */
export function headingToSvgVector(yaw_rad: number, map: MapInfo): { dx: number; dy: number } {
  const imageAngle_rad = yaw_rad - map.origin_yaw_rad
  return { dx: Math.cos(imageAngle_rad), dy: -Math.sin(imageAngle_rad) }
}

/** 이미지 위 끌기 벡터 → 맵 프레임 방향(yaw). headingToSvgVector의 역.
 *  [입력] dx, dy (픽셀) / map  [출력] yaw_rad (-π..π)
 */
export function svgVectorToHeading(dx: number, dy: number, map: MapInfo): number {
  const yaw_rad = Math.atan2(-dy, dx) + map.origin_yaw_rad
  return Math.atan2(Math.sin(yaw_rad), Math.cos(yaw_rad))
}
