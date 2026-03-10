#!/usr/bin/env perl
use strict;
use warnings;

sub reflect {
  my ($vx, $vy, $nx, $ny) = @_;
  my $dot = $vx * $nx + $vy * $ny;
  return ($vx - 2 * $dot * $nx, $vy - 2 * $dot * $ny);
}

sub trace_alpha {
  my ($age, $fade_on, $fade_seconds) = @_;
  return 0.8 unless $fade_on;
  my $s = $fade_seconds > 1e-6 ? $fade_seconds : 1e-6;
  my $a = exp(-$age / $s);
  $a = 0 if $a < 0;
  $a = 1 if $a > 1;
  return $a;
}

sub point_in_polygon {
  my ($p, $poly) = @_;
  my $inside = 0;
  my $n = scalar(@$poly);
  for (my $i = 0, my $j = $n - 1; $i < $n; $j = $i++) {
    my ($xi, $yi) = ($poly->[$i]{x}, $poly->[$i]{y});
    my ($xj, $yj) = ($poly->[$j]{x}, $poly->[$j]{y});
    my $den = ($yj - $yi);
    $den = 1e-9 if abs($den) < 1e-9;
    my $intersect = (($yi > $p->{y}) != ($yj > $p->{y}))
      && ($p->{x} < ($xj - $xi) * ($p->{y} - $yi) / $den + $xi);
    $inside = !$inside if $intersect;
  }
  return $inside ? 1 : 0;
}

sub boundary_edges {
  my ($boundary) = @_;
  my @edges;
  my $n = scalar(@$boundary);
  for (my $i = 0; $i < $n; $i++) {
    push @edges, { a => $boundary->[$i], b => $boundary->[($i + 1) % $n] };
  }
  return \@edges;
}

sub closest_point_on_segment {
  my ($p, $a, $b) = @_;
  my $abx = $b->{x} - $a->{x};
  my $aby = $b->{y} - $a->{y};
  my $apx = $p->{x} - $a->{x};
  my $apy = $p->{y} - $a->{y};
  my $ab_len2 = $abx * $abx + $aby * $aby;
  $ab_len2 = 1 if $ab_len2 == 0;
  my $t = ($apx * $abx + $apy * $aby) / $ab_len2;
  $t = 0 if $t < 0;
  $t = 1 if $t > 1;
  return { x => $a->{x} + $abx * $t, y => $a->{y} + $aby * $t, t => $t };
}

sub closest_edge {
  my ($point, $boundary) = @_;
  my $best;
  my $best_d2 = 1e30;
  for my $edge (@{boundary_edges($boundary)}) {
    my $cp = closest_point_on_segment($point, $edge->{a}, $edge->{b});
    my $dx = $point->{x} - $cp->{x};
    my $dy = $point->{y} - $cp->{y};
    my $d2 = $dx * $dx + $dy * $dy;
    if ($d2 < $best_d2) {
      $best_d2 = $d2;
      $best = { edge => $edge, cp => $cp, d2 => $d2 };
    }
  }
  return $best;
}

sub segment_intersection {
  my ($p1, $p2, $p3, $p4) = @_;
  my $s1x = $p2->{x} - $p1->{x};
  my $s1y = $p2->{y} - $p1->{y};
  my $s2x = $p4->{x} - $p3->{x};
  my $s2y = $p4->{y} - $p3->{y};
  my $denom = (-$s2x * $s1y + $s1x * $s2y);
  return undef if abs($denom) < 1e-6;
  my $s = (-$s1y * ($p1->{x} - $p3->{x}) + $s1x * ($p1->{y} - $p3->{y})) / $denom;
  my $t = ( $s2x * ($p1->{y} - $p3->{y}) - $s2y * ($p1->{x} - $p3->{x})) / $denom;
  return undef unless $s >= 0 && $s <= 1 && $t >= 0 && $t <= 1;
  return { t => $t, x => $p1->{x} + ($t * $s1x), y => $p1->{y} + ($t * $s1y) };
}

sub closest_collision {
  my ($start, $end, $boundary) = @_;
  my $hit;
  my $hit_edge;
  for my $edge (@{boundary_edges($boundary)}) {
    my $info = segment_intersection($start, $end, $edge->{a}, $edge->{b});
    if ($info && (!$hit || $info->{t} < $hit->{t})) {
      $hit = $info;
      $hit_edge = $edge;
    }
  }
  return undef unless $hit && $hit_edge;
  my $ex = $hit_edge->{b}{x} - $hit_edge->{a}{x};
  my $ey = $hit_edge->{b}{y} - $hit_edge->{a}{y};
  my $len = sqrt($ex * $ex + $ey * $ey);
  $len = 1 if $len == 0;
  return { hit => $hit, nx => -$ey / $len, ny => $ex / $len };
}

sub orient_normal_inside {
  my ($hit, $nx, $ny, $boundary) = @_;
  my $probe = { x => $hit->{x} + $nx * 0.5, y => $hit->{y} + $ny * 0.5 };
  return ($nx, $ny) if point_in_polygon($probe, $boundary);
  return (-$nx, -$ny);
}

sub advance_ball {
  my ($ball, $boundary, $dt) = @_;
  my $remaining = $dt;
  my $max_bounces = 8;
  my $eps = 0.05;

  for (my $b = 0; $b < $max_bounces && $remaining > 1e-6; $b++) {
    my $start = { x => $ball->{x}, y => $ball->{y} };
    my $end = {
      x => $ball->{x} + $ball->{vx} * $remaining,
      y => $ball->{y} + $ball->{vy} * $remaining,
    };

    my $collision = closest_collision($start, $end, $boundary);
    if ($collision) {
      my $t = $collision->{hit}{t};
      $t = 0 if $t < 0;
      $t = 1 if $t > 1;
      $ball->{x} = $collision->{hit}{x};
      $ball->{y} = $collision->{hit}{y};
      my ($nx, $ny) = orient_normal_inside($collision->{hit}, $collision->{nx}, $collision->{ny}, $boundary);
      my ($rvx, $rvy) = reflect($ball->{vx}, $ball->{vy}, $nx, $ny);
      $ball->{vx} = $rvx;
      $ball->{vy} = $rvy;
      my $speed = sqrt($ball->{vx} * $ball->{vx} + $ball->{vy} * $ball->{vy});
      $speed = 1 if $speed == 0;
      $ball->{x} += $nx * $eps + ($ball->{vx} / $speed) * $eps;
      $ball->{y} += $ny * $eps + ($ball->{vy} / $speed) * $eps;
      $remaining *= (1 - $t);
      next;
    }

    if (!point_in_polygon($end, $boundary)) {
      my $nearest = closest_edge($end, $boundary);
      if ($nearest) {
        my $ex = $nearest->{edge}{b}{x} - $nearest->{edge}{a}{x};
        my $ey = $nearest->{edge}{b}{y} - $nearest->{edge}{a}{y};
        my $len = sqrt($ex * $ex + $ey * $ey);
        $len = 1 if $len == 0;
        my ($nx, $ny) = (-$ey / $len, $ex / $len);
        ($nx, $ny) = orient_normal_inside($nearest->{cp}, $nx, $ny, $boundary);
        my ($rvx, $rvy) = reflect($ball->{vx}, $ball->{vy}, $nx, $ny);
        $ball->{vx} = $rvx;
        $ball->{vy} = $rvy;
        my $speed = sqrt($ball->{vx} * $ball->{vx} + $ball->{vy} * $ball->{vy});
        $speed = 1 if $speed == 0;
        $ball->{x} = $nearest->{cp}{x} + $nx * $eps + ($ball->{vx} / $speed) * $eps;
        $ball->{y} = $nearest->{cp}{y} + $ny * $eps + ($ball->{vy} / $speed) * $eps;
        $remaining *= 0.5;
        next;
      }
    }

    $ball->{x} = $end->{x};
    $ball->{y} = $end->{y};
    $remaining = 0;
  }
}

sub run_core_tests {
  my @fails;
  my ($vx1, $vy1) = reflect(1, 0, 1, 0);
  push @fails, 'reflect-x' if abs($vx1 + 1) > 1e-6 || abs($vy1) > 1e-6;
  my ($vx2, $vy2) = reflect(1, 0, 0, 1);
  push @fails, 'reflect-y' if abs($vx2 - 1) > 1e-6 || abs($vy2) > 1e-6;
  my $hit = segment_intersection({x=>0,y=>0},{x=>10,y=>0},{x=>5,y=>-5},{x=>5,y=>5});
  push @fails, 'segment-intersection' if !$hit || abs($hit->{x} - 5) > 1e-6;
  my $a0 = trace_alpha(0, 1, 10);
  my $a5 = trace_alpha(5, 1, 10);
  my $a10 = trace_alpha(10, 1, 10);
  push @fails, 'trace-alpha-monotonic' unless ($a0 > $a5 && $a5 > $a10 && $a10 > 0);
  push @fails, 'trace-alpha-tail' unless abs(trace_alpha(1000, 1, 10)) < 1e-3;
  push @fails, 'trace-alpha-off' unless abs(trace_alpha(1000, 0, 10) - 0.8) < 1e-9;
  return @fails;
}

sub run_angle_sweep_for_boundary {
  my ($name, $boundary, $angle_step, $frame_count, $dt, $speed0) = @_;
  my @failures;

  for (my $angle = 0; $angle < 360; $angle += $angle_step) {
    my $rad = $angle * 3.141592653589793 / 180.0;

    my $cx = 0;
    my $cy = 0;
    $cx += $_->{x} for @$boundary;
    $cy += $_->{y} for @$boundary;
    $cx /= scalar(@$boundary);
    $cy /= scalar(@$boundary);

    my $ball = {
      x => $cx,
      y => $cy,
      vx => cos($rad) * $speed0,
      vy => sin($rad) * $speed0,
    };

    my $min_move = 1e30;
    my $max_speed_error = 0;

    for (my $i = 0; $i < $frame_count; $i++) {
      my $px = $ball->{x};
      my $py = $ball->{y};
      advance_ball($ball, $boundary, $dt);
      my $moved = sqrt(($ball->{x} - $px)**2 + ($ball->{y} - $py)**2);
      $min_move = $moved if $moved < $min_move;
      my $speed = sqrt($ball->{vx}**2 + $ball->{vy}**2);
      my $err = abs($speed - $speed0);
      $max_speed_error = $err if $err > $max_speed_error;
    }

    my $near = closest_edge({x=>$ball->{x}, y=>$ball->{y}}, $boundary);
    my $outside = !point_in_polygon({x=>$ball->{x}, y=>$ball->{y}}, $boundary);
    my $far_outside = $outside && (!$near || $near->{d2} > 4);
    my $stopped = $min_move < 1e-4;
    my $speed_drift = $max_speed_error > 1.5;

    if ($stopped || $speed_drift || $far_outside) {
      push @failures, {
        boundary => $name,
        angle => $angle,
        stopped => $stopped ? 1 : 0,
        speed_drift => $speed_drift ? 1 : 0,
        far_outside => $far_outside ? 1 : 0,
      };
    }
  }

  return @failures;
}

sub main {
  my @core_failures = run_core_tests();

  my @boundaries = (
    [ 'rectangle', [
      {x=>120,y=>100},{x=>780,y=>100},{x=>780,y=>540},{x=>120,y=>540}
    ]],
    [ 'hexagon', [
      {x=>200,y=>140},{x=>700,y=>140},{x=>820,y=>320},{x=>700,y=>500},{x=>200,y=>500},{x=>80,y=>320}
    ]],
    [ 'concave', [
      {x=>130,y=>140},{x=>760,y=>140},{x=>760,y=>260},{x=>520,y=>260},{x=>520,y=>380},{x=>760,y=>380},{x=>760,y=>520},{x=>130,y=>520}
    ]],
  );

  my @sweep_failures;
  for my $entry (@boundaries) {
    my ($name, $poly) = @$entry;
    push @sweep_failures, run_angle_sweep_for_boundary($name, $poly, 2, 700, 1/120, 260);
  }

  print "Core tests: ", (@core_failures ? "FAIL" : "PASS"), "\n";
  if (@core_failures) {
    print "  failures: ", join(', ', @core_failures), "\n";
  }

  my $cases = scalar(@boundaries) * int(360 / 2);
  print "Angle sweep cases: $cases\n";
  print "Sweep failures: ", scalar(@sweep_failures), "\n";

  if (@sweep_failures) {
    my $shown = 0;
    for my $f (@sweep_failures) {
      last if $shown >= 20;
      print "  [$f->{boundary}] angle=$f->{angle} stopped=$f->{stopped} speed_drift=$f->{speed_drift} far_outside=$f->{far_outside}\n";
      $shown++;
    }
    print "  (showing first 20 failures)\n" if @sweep_failures > 20;
  }

  if (@core_failures || @sweep_failures) {
    exit 1;
  }
  print "All bounce regression tests passed.\n";
}

main();
