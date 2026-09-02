# d3bouur_description

The URDF/xacro robot model: base + 4 wheels, for visualizing D3BOUUR in RViz
and (eventually) simulating it in Gazebo.

## Status: **BUILT, NOT YET VERIFIED** (for simulation) / **CONFIRMED WORKING** (for the model itself)

Splitting the status in two because the two claims are genuinely different:

- **The model itself parses correctly** — `xacro urdf/d3bouur.urdf.xacro` expands
  cleanly and `check_urdf` accepts the result with no errors, so the URDF is
  structurally valid.
- **It has never been spawned into Gazebo.** Simulation setup was paused
  deliberately before that step (see the top-level `CLAUDE.md`) — this model
  hasn't been tested against physics, hasn't had sensors/plugins added, and
  hasn't been checked visually in RViz or Gazebo.

## Testing

```bash
cd src/d3bouur_description
xacro urdf/d3bouur.urdf.xacro > /tmp/d3bouur.urdf
check_urdf /tmp/d3bouur.urdf
```

Or, to view it in RViz (this launches RViz but does not spawn into Gazebo):

```bash
ros2 launch d3bouur_description display.launch.py
```

## Next step (not started)

Spawning into a Gazebo Harmonic scene — the deliberate stopping point this
package was left at.
