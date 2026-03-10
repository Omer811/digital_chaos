from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


Point = Dict[str, float]
Edge = Dict[str, Point]


@dataclass
class Ball:
    x: float
    y: float
    vx: float
    vy: float


def reflect(vx: float, vy: float, nx: float, ny: float) -> Tuple[float, float]:
    dot = vx * nx + vy * ny
    return vx - 2.0 * dot * nx, vy - 2.0 * dot * ny


def trace_alpha(age: float, fade_on: bool, fade_seconds: float) -> float:
    if not fade_on:
        return 0.8
    s = max(1e-6, fade_seconds)
    # Smooth fade that reaches ~0 by fade_seconds.
    t = max(0.0, 1.0 - (age / s))
    return t * t


def boundary_edges(boundary: List[Point]) -> List[Edge]:
    return [{"a": boundary[i], "b": boundary[(i + 1) % len(boundary)]} for i in range(len(boundary))]


def point_in_polygon(point: Point, polygon: List[Point]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]["x"], polygon[i]["y"]
        xj, yj = polygon[j]["x"], polygon[j]["y"]
        den = (yj - yi) if abs(yj - yi) > 1e-9 else 1e-9
        intersect = ((yi > point["y"]) != (yj > point["y"])) and (
            point["x"] < (xj - xi) * (point["y"] - yi) / den + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def closest_point_on_segment(p: Point, a: Point, b: Point) -> Point:
    abx = b["x"] - a["x"]
    aby = b["y"] - a["y"]
    apx = p["x"] - a["x"]
    apy = p["y"] - a["y"]
    ab_len2 = abx * abx + aby * aby
    if ab_len2 <= 0:
        return {"x": a["x"], "y": a["y"], "t": 0.0}
    t = (apx * abx + apy * aby) / ab_len2
    t = max(0.0, min(1.0, t))
    return {"x": a["x"] + abx * t, "y": a["y"] + aby * t, "t": t}


def closest_edge(point: Point, boundary: List[Point]) -> Optional[Dict[str, object]]:
    best = None
    best_d2 = float("inf")
    for edge in boundary_edges(boundary):
        cp = closest_point_on_segment(point, edge["a"], edge["b"])
        dx = point["x"] - cp["x"]
        dy = point["y"] - cp["y"]
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2 = d2
            best = {"edge": edge, "cp": cp, "d2": d2}
    return best


def segment_intersection(p1: Point, p2: Point, p3: Point, p4: Point) -> Optional[Point]:
    s1x = p2["x"] - p1["x"]
    s1y = p2["y"] - p1["y"]
    s2x = p4["x"] - p3["x"]
    s2y = p4["y"] - p3["y"]
    denom = -s2x * s1y + s1x * s2y
    if abs(denom) < 1e-6:
        return None
    s = (-s1y * (p1["x"] - p3["x"]) + s1x * (p1["y"] - p3["y"])) / denom
    t = (s2x * (p1["y"] - p3["y"]) - s2y * (p1["x"] - p3["x"])) / denom
    if 0.0 <= s <= 1.0 and 0.0 <= t <= 1.0:
        return {"t": t, "x": p1["x"] + t * s1x, "y": p1["y"] + t * s1y}
    return None


def closest_collision(start: Point, end: Point, boundary: List[Point]) -> Optional[Dict[str, object]]:
    hit = None
    hit_edge = None
    for edge in boundary_edges(boundary):
        info = segment_intersection(start, end, edge["a"], edge["b"])
        if info and (hit is None or info["t"] < hit["t"]):
            hit = info
            hit_edge = edge
    if hit is None or hit_edge is None:
        return None
    ex = hit_edge["b"]["x"] - hit_edge["a"]["x"]
    ey = hit_edge["b"]["y"] - hit_edge["a"]["y"]
    length = math.hypot(ex, ey) or 1.0
    return {"hit": hit, "nx": -ey / length, "ny": ex / length}


def orient_normal_inside(hit: Point, nx: float, ny: float, boundary: List[Point]) -> Tuple[float, float]:
    probe = {"x": hit["x"] + nx * 0.5, "y": hit["y"] + ny * 0.5}
    if point_in_polygon(probe, boundary):
        return nx, ny
    return -nx, -ny


def advance_ball(ball: Ball, boundary: List[Point], dt: float) -> None:
    remaining = dt
    eps = 0.05
    for _ in range(8):
        if remaining <= 1e-6:
            break
        start = {"x": ball.x, "y": ball.y}
        end = {"x": ball.x + ball.vx * remaining, "y": ball.y + ball.vy * remaining}

        collision = closest_collision(start, end, boundary)
        if collision:
            t = max(0.0, min(1.0, float(collision["hit"]["t"])))
            ball.x = float(collision["hit"]["x"])
            ball.y = float(collision["hit"]["y"])
            nx, ny = orient_normal_inside(collision["hit"], float(collision["nx"]), float(collision["ny"]), boundary)
            ball.vx, ball.vy = reflect(ball.vx, ball.vy, nx, ny)
            speed = math.hypot(ball.vx, ball.vy) or 1.0
            ball.x += nx * eps + (ball.vx / speed) * eps
            ball.y += ny * eps + (ball.vy / speed) * eps
            remaining *= (1.0 - t)
            continue

        if not point_in_polygon(end, boundary):
            nearest = closest_edge(end, boundary)
            if nearest:
                ex = nearest["edge"]["b"]["x"] - nearest["edge"]["a"]["x"]
                ey = nearest["edge"]["b"]["y"] - nearest["edge"]["a"]["y"]
                length = math.hypot(ex, ey) or 1.0
                nx, ny = -ey / length, ex / length
                nx, ny = orient_normal_inside(nearest["cp"], nx, ny, boundary)
                ball.vx, ball.vy = reflect(ball.vx, ball.vy, nx, ny)
                speed = math.hypot(ball.vx, ball.vy) or 1.0
                ball.x = nearest["cp"]["x"] + nx * eps + (ball.vx / speed) * eps
                ball.y = nearest["cp"]["y"] + ny * eps + (ball.vy / speed) * eps
                remaining *= 0.5
                continue

        ball.x = end["x"]
        ball.y = end["y"]
        break

