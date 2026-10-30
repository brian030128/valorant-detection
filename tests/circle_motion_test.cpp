#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>

struct MouseReport { uint8_t buttons; int8_t wheel; int16_t dx, dy; };
#include "../mouse-spoofing/firmware/m2k_stream/circle_motion.h"

int main() {
  for (int radius : {1, 240, 1000}) {
    for (uint32_t period : {500u, 1000u, 10000u}) {
      for (uint8_t buttons : {uint8_t(0), uint8_t(1)}) {
        CircleMotion circle;
        circle.start(radius, period, 3, buttons);
        int x = radius, y = 0;
        unsigned stationary = 0;
        for (uint32_t i = 0; i < period * 3; ++i) {
          auto report = circle.next();
          assert(circle.active && report.buttons == buttons && report.wheel == 0);
          x += report.dx; y += report.dy;
          assert(std::abs(x) <= radius && std::abs(y) <= radius);
          assert(std::abs(std::hypot(x, y) - radius) <= 0.71);
          if (!report.dx && !report.dy) ++stationary;
          if ((i + 1) % period == 0) assert(x == radius && y == 0);
        }
        // Default test has a fresh nonzero delta on every 1 ms circle sample.
        if (radius == 240 && period == 1000) assert(stationary == 0);
        auto release = circle.next();
        assert(!circle.active && release.buttons == 0 && release.dx == 0 && release.dy == 0);
        auto idle = circle.next();
        assert(idle.buttons == 0 && idle.dx == 0 && idle.dy == 0);
      }
    }
  }
  CircleMotion cancelled;
  cancelled.start(240, 1000, 3, 1);
  cancelled.next();
  cancelled.active = false;
  auto release = cancelled.next();
  assert(release.buttons == 0 && release.dx == 0 && release.dy == 0);
  std::cout << "Circle motion: closed paths, per-slot deltas, release and cancellation passed\n";
}
