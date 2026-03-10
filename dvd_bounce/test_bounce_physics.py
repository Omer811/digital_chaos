from __future__ import annotations

import math
import unittest

from bounce_physics import (
    Ball,
    advance_ball,
    point_in_polygon,
    reflect,
    segment_intersection,
    trace_alpha,
)


class BouncePhysicsTests(unittest.TestCase):
    def test_reflect_axis_aligned(self) -> None:
        vx, vy = reflect(1.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(vx, -1.0, places=8)
        self.assertAlmostEqual(vy, 0.0, places=8)

        vx, vy = reflect(1.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(vx, 1.0, places=8)
        self.assertAlmostEqual(vy, 0.0, places=8)

    def test_segment_intersection(self) -> None:
        hit = segment_intersection(
            {"x": 0.0, "y": 0.0},
            {"x": 10.0, "y": 0.0},
            {"x": 5.0, "y": -5.0},
            {"x": 5.0, "y": 5.0},
        )
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit["x"], 5.0, places=8)

    def test_trace_alpha_fade_on_monotonic(self) -> None:
        a0 = trace_alpha(0.0, True, 10.0)
        a5 = trace_alpha(5.0, True, 10.0)
        a10 = trace_alpha(10.0, True, 10.0)
        self.assertGreater(a0, a5)
        self.assertGreater(a5, a10)
        self.assertGreaterEqual(a10, 0.0)
        self.assertLess(trace_alpha(1000.0, True, 10.0), 1e-4)

    def test_trace_alpha_fade_off_constant(self) -> None:
        self.assertAlmostEqual(trace_alpha(0.0, False, 10.0), 0.8, places=9)
        self.assertAlmostEqual(trace_alpha(1000.0, False, 10.0), 0.8, places=9)

    def test_angle_sweep_no_stall_or_escape(self) -> None:
        boundaries = [
            [
                {"x": 120.0, "y": 100.0},
                {"x": 780.0, "y": 100.0},
                {"x": 780.0, "y": 540.0},
                {"x": 120.0, "y": 540.0},
            ],
            [
                {"x": 200.0, "y": 140.0},
                {"x": 700.0, "y": 140.0},
                {"x": 820.0, "y": 320.0},
                {"x": 700.0, "y": 500.0},
                {"x": 200.0, "y": 500.0},
                {"x": 80.0, "y": 320.0},
            ],
            [
                {"x": 130.0, "y": 140.0},
                {"x": 760.0, "y": 140.0},
                {"x": 760.0, "y": 260.0},
                {"x": 520.0, "y": 260.0},
                {"x": 520.0, "y": 380.0},
                {"x": 760.0, "y": 380.0},
                {"x": 760.0, "y": 520.0},
                {"x": 130.0, "y": 520.0},
            ],
        ]
        dt = 1.0 / 120.0
        speed0 = 260.0
        frame_count = 700
        failures = []

        for boundary in boundaries:
            cx = sum(p["x"] for p in boundary) / len(boundary)
            cy = sum(p["y"] for p in boundary) / len(boundary)
            for angle_deg in range(0, 360, 2):
                rad = math.radians(angle_deg)
                ball = Ball(cx, cy, math.cos(rad) * speed0, math.sin(rad) * speed0)
                min_move = float("inf")
                max_speed_error = 0.0
                for _ in range(frame_count):
                    px, py = ball.x, ball.y
                    advance_ball(ball, boundary, dt)
                    moved = math.hypot(ball.x - px, ball.y - py)
                    min_move = min(min_move, moved)
                    speed = math.hypot(ball.vx, ball.vy)
                    max_speed_error = max(max_speed_error, abs(speed - speed0))

                outside = not point_in_polygon({"x": ball.x, "y": ball.y}, boundary)
                stopped = min_move < 1e-4
                speed_drift = max_speed_error > 1.5
                if outside or stopped or speed_drift:
                    failures.append((angle_deg, outside, stopped, speed_drift))

        self.assertEqual(
            failures,
            [],
            msg=f"Found {len(failures)} failing sweep cases. First: {failures[:10]}",
        )


if __name__ == "__main__":
    unittest.main()

